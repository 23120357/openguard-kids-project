"""Measure F2 DNS filtering without changing the machine's DNS or live policy.

Run python -m scripts.check_f2_dns --output output/f2-dns.json.
Use --live only after configuring the lab agent with the emitted lab policy.
"""

import argparse
import csv
import json
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace

from dnslib import AAAA, QTYPE, RCODE, RR, A, DNSRecord
from dnslib.server import BaseResolver, DNSLogger, DNSServer

from agent.filtering import DNSProxy
from common.filter_categories import DEFAULT_ACTIONS

ROOT = Path(__file__).resolve().parents[1]


class SafeUpstream(BaseResolver):
    """Offline fixture: never browse or resolve the real domains in the matrix."""

    def resolve(self, request, handler):
        reply = request.reply()
        rdata = AAAA("2001:db8::1") if request.q.qtype == QTYPE.AAAA else A("192.0.2.1")
        reply.add_answer(RR(request.q.qname, request.q.qtype, ttl=30, rdata=rdata))
        return reply


def lab_policy(cases):
    return {
        "enabled": True, "version": 1, "app_mode": "blocklist", "app_allow": [], "app_block": [],
        "domain_mode": "blocklist", "domain_allow": [], "safety_domains": ["tongdai111.vn"],
        "domain_block": [item["domain"] for item in cases if item["expected"] == "block"],
        "safe_search": True, "category_actions": dict(DEFAULT_ACTIONS),
    }


def measure(cases, host, ports):
    results = []
    for tcp, port in ports:
        for qtype in ("A", "AAAA"):
            for item in cases:
                # Exercise both root and subdomain matching for every block case.
                names = [item["domain"]]
                if item["expected"] == "block":
                    names.append("www." + item["domain"])
                for name in names:
                    row = {**item, "queried": name, "transport": "tcp" if tcp else "udp", "qtype": qtype}
                    try:
                        query = DNSRecord.question(name, qtype)
                        answer = DNSRecord.parse(query.send(host, port, tcp=tcp, timeout=3))
                        valid = answer.q == query.q and answer.header.id == query.header.id
                        row["rcode"] = RCODE[answer.header.rcode]
                        row["passed"] = valid and (
                            answer.header.rcode == RCODE.NXDOMAIN if item["expected"] == "block"
                            else answer.header.rcode == RCODE.NOERROR and any(
                                rr.rtype == getattr(QTYPE, qtype) for rr in answer.rr
                            )
                        )
                    except (OSError, ValueError) as exc:
                        row.update(passed=False, error=str(exc))
                    results.append(row)
    groups = {}
    for row in results:
        groups.setdefault((row["domain"], row["expected"]), []).append(row["passed"])
    blocked_ok = sum(all(values) for (domain, expected), values in groups.items() if expected == "block")
    education_ok = sum(all(values) for (domain, expected), values in groups.items() if expected == "allow")
    return {
        "blocked_pass": blocked_ok, "blocked_total": 50,
        "education_pass": education_ok, "education_total": 20,
        "passed": blocked_ok >= 48 and education_ok == 20,
        "results": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Query an already configured lab agent")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=53)
    parser.add_argument("--output", type=Path, default=ROOT / "output/f2-dns.json")
    args = parser.parse_args()
    with (ROOT / "tests/assets/f2_dns_cases.csv").open(encoding="utf-8") as stream:
        cases = list(csv.DictReader(stream))
    policy = lab_policy(cases)
    upstreams = []
    proxy = None
    try:
        if args.live:
            result = measure(cases, args.host, [(False, args.port), (True, args.port)])
        else:
            logger = DNSLogger(log="-request,-reply,-truncated,-error,-recv,-send,-data", prefix=False)
            udp = DNSServer(SafeUpstream(), address="127.0.0.1", port=0, logger=logger)
            upstreams.append(udp)
            tcp = DNSServer(SafeUpstream(), address="127.0.0.1", port=udp.server.server_address[1], tcp=True, logger=logger)
            upstreams.append(tcp)
            for server in upstreams:
                server.start_thread()
            core = SimpleNamespace(activity_context=lambda: ("lab", policy, 1), record_activity=lambda *args: None)
            # DNSProxy rejects loopback in production to avoid forwarding loops.
            proxy = DNSProxy(core, port=0)
            proxy.upstream = "127.0.0.1"
            proxy.upstream_port = udp.server.server_address[1]
            proxy.start()
            result = measure(cases, "127.0.0.1", [(bool(i), server.server.server_address[1]) for i, server in enumerate(proxy.servers)])
    finally:
        if proxy:
            proxy.stop()
        for server in upstreams:
            server.stop()
    result.update(mode="live" if args.live else "isolated", measured_at=datetime.now(UTC).isoformat())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    args.output.with_suffix('.policy.json').write_text(json.dumps(policy, indent=2), encoding="utf-8")
    print(json.dumps({key: value for key, value in result.items() if key != "results"}))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
