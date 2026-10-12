"""Visible F2 enforcement. No window titles, full URLs, or executable paths in events."""

import hashlib
import logging
import os
import threading
import time
from pathlib import Path

from common.domains import domain_name, event_domain, normalize_safety_domains
from common.filter_categories import CATEGORY_LABELS, DEFAULT_ACTIONS, classify_domain

LOGGER = logging.getLogger(__name__)


def matches_domain(host, domains):
    return any(host == item or host.endswith("." + item) for item in domains)


def domain_decision(host, rules):
    host = domain_name(host)
    if not rules or not rules.get("enabled") or rules.get("dns_proxy_enabled", True) is False:
        return None
    if matches_domain(host, normalize_safety_domains(rules.get("safety_domains", []))):
        return None
    if matches_domain(host, rules.get("domain_block", [])):
        return "Trang web nằm trong danh sách bị chặn."
    if rules.get("domain_mode") == "allowlist" and not matches_domain(
        host, rules.get("domain_allow", [])
    ):
        return "Trang web không nằm trong danh sách cho phép."
    if matches_domain(host, rules.get("domain_allow", [])):
        return None
    category = classify_domain(host, rules.get("category_overrides"))
    if rules.get("category_actions", DEFAULT_ACTIONS).get(category) == "block":
        return f"Trang web thuộc nhóm {CATEGORY_LABELS[category]} đang bị chặn."
    return None


def trusted_windows_process(name, filename):
    """Only exempt protected names from administrator-owned Windows locations.

    Resolving links prevents an executable in a user directory from gaining an
    exemption by using a familiar filename or a junction into another directory.
    Windows directory ACLs are a prerequisite (the child must be a standard user).
    """
    root = os.environ.get("SystemRoot")
    if not root:
        return False
    executable = Path(filename).resolve()
    windows = Path(root).resolve()
    if executable.name.casefold() != name.casefold():
        return False
    if name.casefold() == "explorer.exe":
        return executable == windows / "explorer.exe"
    return executable.parent in {windows / "System32", windows / "SysWOW64"} or (
        windows / "SystemApps" in executable.parents
    )


SAFE_SEARCH_HOSTS = {
    host: "forcesafesearch.google.com"
    for suffix in ("com", "com.vn", "co.uk", "com.au", "ca", "fr", "de", "co.jp", "co.in")
    for host in (f"google.{suffix}", f"www.google.{suffix}")
}
SAFE_SEARCH_HOSTS.update({
    host: "strict.bing.com" for host in ("bing.com", "www.bing.com", "edgeservices.bing.com")
})


def app_decision(name, sha256, rules):
    if not rules or not rules.get("enabled"):
        return None
    # Hash is authoritative when a filename changes. A matching name with a
    # different hash cannot impersonate an allowed executable.
    if any(item["sha256"].lower() == sha256.lower() for item in rules.get("app_block", [])):
        return "Ứng dụng nằm trong danh sách bị chặn."
    if rules.get("app_mode") == "allowlist" and not any(
        item["sha256"].lower() == sha256.lower() for item in rules.get("app_allow", [])
    ):
        return "Ứng dụng không nằm trong danh sách cho phép."
    return None


class AppController:
    def __init__(self, core):
        self.core = core
        self.stop_event = threading.Event()
        self.thread = None
        self.hashes = {}
        self.seen = {}
        self.context_key = None

    def start(self):
        self.thread = threading.Thread(target=self.run, name="ogk-app-control", daemon=True)
        self.thread.start()

    def stop(self):
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=5)

    def file_hash(self, filename):
        stat = os.stat(filename)
        key = (filename, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)
        if key not in self.hashes:
            digest = hashlib.sha256()
            with open(filename, "rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            if len(self.hashes) > 500:
                self.hashes.clear()
            self.hashes[key] = digest.hexdigest()
        return self.hashes[key]

    def scan(self):
        import psutil
        import win32process
        from win32ts import ProcessIdToSessionId

        context = self.core.activity_context()
        if not context:
            self.seen.clear()
            return
        child_id, rules, tray_pid = context
        context_key = (child_id, tray_pid, rules.get("_activity_epoch", 0))
        if context_key != self.context_key:
            self.seen.clear()
            self.context_key = context_key
        session_id = ProcessIdToSessionId(tray_pid)
        if session_id == 0:
            return
        live = {}
        # Never terminate SYSTEM/services or a different Windows session.
        protected = {
            "explorer.exe",
            "sihost.exe",
            "ctfmon.exe",
            "dwm.exe",
            "winlogon.exe",
            "taskhostw.exe",
            "fontdrvhost.exe",
            "lockapp.exe",
            "searchhost.exe",
            "startmenuexperiencehost.exe",
            "runtimebroker.exe",
            "shellexperiencehost.exe",
            "applicationframehost.exe",
            "textinputhost.exe",
            "userinit.exe",
            "logonui.exe",
        }
        for pid in win32process.EnumProcesses():
            if pid in {0, 4, os.getpid(), tray_pid}:
                continue
            try:
                if ProcessIdToSessionId(pid) != session_id:
                    continue
                process = psutil.Process(pid)
                name = process.name()
                filename = process.exe()
                if name.lower() in protected and trusted_windows_process(name, filename):
                    continue
                identity = (child_id, pid, process.create_time())
                # The service owns file access and computes this identity for the
                # parent-facing picker. File paths never leave the device. Failure
                # to read a file must not suppress ordinary usage reporting while
                # filtering is disabled.
                try:
                    sha256 = self.file_hash(filename)
                    self.core.record_observed_app(child_id, name, sha256)
                except (OSError, ValueError):
                    if rules.get("enabled"):
                        continue
                    sha256 = ""
                reason = app_decision(name, sha256, rules)
                if reason:
                    # Re-read identity/executable before killing to avoid a PID reuse race.
                    if process.create_time() != identity[2] or process.exe() != filename:
                        continue
                    process.kill()
                    self.core.record_activity(child_id, "blocked_app", name, reason, rules)
                else:
                    live[identity] = (name, time.monotonic(), rules)
                    if identity in self.seen:
                        old_name, started, old_rules = self.seen[identity]
                        elapsed = max(0, int(time.monotonic() - started))
                        if elapsed:
                            if elapsed <= 5:
                                self.core.record_activity(
                                    child_id,
                                    "app_stop",
                                    old_name,
                                    "",
                                    old_rules,
                                    duration_sec=elapsed,
                                )
                            live[identity] = (name, started + elapsed, rules)
                        else:
                            live[identity] = self.seen[identity]
                    else:
                        self.core.record_activity(child_id, "app_start", name, "", rules)
            except (psutil.Error, OSError, ValueError):
                continue
        for identity, (name, started, old_rules) in self.seen.items():
            if identity not in live and identity[0] == child_id:
                self.core.record_activity(
                    child_id,
                    "app_stop",
                    name,
                    "",
                    old_rules,
                    duration_sec=min(5, max(0, int(time.monotonic() - started))),
                )
        self.seen = live

    def run(self):
        while not self.stop_event.is_set():
            try:
                self.scan()
            except Exception:
                LOGGER.exception("Application controller scan failed")
            self.stop_event.wait(1)


class DNSProxy:
    """UDP and TCP DNS, with bounded forwarding and no query logging."""

    def __init__(self, core, host="127.0.0.1", port=53, upstream="1.1.1.1", upstream_port=53):
        import ipaddress

        if ipaddress.ip_address(upstream).is_loopback:
            raise ValueError("DNS upstream must not loop back to the proxy")
        self.core = core
        self.host, self.port = host, port
        self.upstream, self.upstream_port = upstream, upstream_port
        self.servers = []
        self.recent_blocks = {}
        self.recent_queries = {}
        self.lock = threading.Lock()

    def resolve(self, request, handler):
        from dnslib import RCODE, DNSRecord

        context = self.core.activity_context()
        try:
            host = domain_name(str(request.q.qname))
        except ValueError:
            host = None
        if context and host and context[1].get("dns_proxy_enabled", True):
            child_id, rules, _ = context
            with self.lock:
                now = time.monotonic()
                query_key = (child_id, event_domain(host), rules.get("_activity_epoch", 0))
                if now - self.recent_queries.get(query_key, -10) >= 5:
                    self.core.record_activity(child_id, "domain_query", query_key[1], "", rules)
                    self.recent_queries[query_key] = now
                if len(self.recent_queries) > 1000:
                    self.recent_queries = {
                        key: ts for key, ts in self.recent_queries.items() if now - ts < 5
                    }
            reason = domain_decision(host, rules)
            if reason:
                # Browsers issue A/AAAA/retry queries together. Coalesce nearby
                # blocked events; the Tray separately limits popups per session.
                key = (child_id, event_domain(host), reason, rules.get("_activity_epoch", 0))
                with self.lock:
                    now = time.monotonic()
                    if now - self.recent_blocks.get(key, -10) >= 5:
                        self.core.record_activity(child_id, "blocked_domain", key[1], reason, rules)
                        self.recent_blocks[key] = now
                    if len(self.recent_blocks) > 1000:
                        self.recent_blocks = {
                            k: ts for k, ts in self.recent_blocks.items() if now - ts < 5
                        }
                reply = request.reply()
                reply.header.rcode = RCODE.NXDOMAIN
                return reply
            if rules.get("enabled") and rules.get("safe_search", True) and host in SAFE_SEARCH_HOSTS:
                return self.safe_search_reply(request, handler, SAFE_SEARCH_HOSTS[host])
        try:
            raw = request.send(
                self.upstream, self.upstream_port, tcp=handler.protocol == "tcp", timeout=3
            )
            reply = DNSRecord.parse(raw)
            if reply.header.tc and handler.protocol != "tcp":
                reply = DNSRecord.parse(
                    request.send(self.upstream, self.upstream_port, tcp=True, timeout=3)
                )
            if reply.header.id != request.header.id or reply.q != request.q:
                raise ValueError("Mismatched upstream DNS reply")
            return reply
        except (OSError, ValueError):
            reply = request.reply()
            reply.header.rcode = RCODE.SERVFAIL
            return reply

    def safe_search_reply(self, request, handler, target):
        from dnslib import CNAME, QTYPE, RCODE, RR, DNSRecord

        reply = request.reply()
        reply.header.ad = 0  # Locally synthesized data is not DNSSEC authenticated.
        reply.add_answer(RR(request.q.qname, QTYPE.CNAME, ttl=60, rdata=CNAME(target)))
        if request.q.qtype == QTYPE.CNAME:
            return reply
        if request.q.qtype not in (QTYPE.A, QTYPE.AAAA):
            # Do not forward HTTPS/SVCB records with alternative endpoint hints.
            return reply
        query = DNSRecord.question(target, QTYPE[request.q.qtype])
        try:
            raw = query.send(self.upstream, self.upstream_port, tcp=handler.protocol == "tcp", timeout=3)
            answer = DNSRecord.parse(raw)
            if answer.header.tc and handler.protocol != "tcp":
                answer = DNSRecord.parse(query.send(self.upstream, self.upstream_port, tcp=True, timeout=3))
            if answer.header.id != query.header.id or answer.q != query.q or answer.header.rcode != RCODE.NOERROR:
                raise ValueError("Invalid SafeSearch upstream answer")
            for record in answer.rr:
                if record.rtype in (QTYPE.A, QTYPE.AAAA, QTYPE.CNAME):
                    reply.add_answer(record)
            return reply
        except (OSError, ValueError):
            failure = request.reply()
            failure.header.rcode = RCODE.SERVFAIL
            return failure
    def start(self):
        from dnslib.server import DNSLogger, DNSServer

        try:
            for tcp in (False, True):
                server = DNSServer(
                    self,
                    port=self.port,
                    address=self.host,
                    tcp=tcp,
                    logger=DNSLogger(
                        log="-request,-reply,-truncated,-error,-recv,-send,-data", prefix=False
                    ),
                )
                self.servers.append(server)
                server.start_thread()
        except OSError:
            self.stop()
            raise

    def stop(self):
        for server in self.servers:
            server.stop()
        self.servers.clear()


def executable_identity(filename):
    """Local CLI helper: only filename and hash may be copied into app rules."""
    return {"name": Path(filename).name, "sha256": AppController(None).file_hash(filename)}


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Get executable name and SHA-256 for an app rule")
    parser.add_argument("filename")
    print(json.dumps(executable_identity(parser.parse_args().filename), ensure_ascii=False))
