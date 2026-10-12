"""Reversible machine DNS/browser configuration owned by the service.

The journal lives in the administrator-only agent data directory. Each original
value is persisted before its first mutation, including across service crashes.
"""

from __future__ import annotations

import json
import subprocess
import threading
from pathlib import Path


class WindowsNetwork:
    def run(self, script):
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-Command",
                "$ErrorActionPreference='Stop'; " + script,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=45,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        if result.returncode:
            raise RuntimeError(result.stderr.strip() or "Windows DNS configuration failed")
        return result.stdout.strip()

    def snapshot(self):
        # NameServer distinguishes static settings from addresses learned by DHCP/RA.
        raw = self.run(r"""
        $routes = @(Get-NetRoute | Where-Object {
            $_.DestinationPrefix -in @('0.0.0.0/0', '::/0')
        } | Select-Object -ExpandProperty InterfaceIndex -Unique)
        $items = @(Get-NetAdapter | Where-Object {
            $_.Status -eq 'Up' -and $_.InterfaceIndex -in $routes
        } | ForEach-Object {
            $a = $_
            foreach ($family in @('IPv4', 'IPv6')) {
                $proto = if ($family -eq 'IPv4') { 'Tcpip' } else { 'Tcpip6' }
                $p = 'HKLM:\SYSTEM\CurrentControlSet\Services\' + $proto + '\Parameters\Interfaces\' + $a.InterfaceGuid
                $static = (Get-ItemProperty -LiteralPath $p -Name NameServer -ErrorAction SilentlyContinue).NameServer
                [pscustomobject]@{ id = "$($a.InterfaceGuid)/$family"; guid = "$($a.InterfaceGuid)";
                    family = $family; servers = @($static -split '[,;\s]+' | Where-Object { $_ }) }
            }
        })
        ConvertTo-Json -InputObject $items -Compress -Depth 5
        """)
        return json.loads(raw)

    def set_dns(self, item, restore=False):
        import uuid

        guid = str(uuid.UUID(item["guid"].strip("{}")))
        family = item["family"]
        if family not in ("IPv4", "IPv6"):
            raise ValueError("Invalid DNS address family")
        import ipaddress

        servers = item["servers"] if restore else (["127.0.0.1"] if family == "IPv4" else ["::1"])
        addresses = ",".join("'" + str(ipaddress.ip_address(s)) + "'" for s in servers)
        action = "-ServerAddresses @(" + addresses + ")" if servers else "-ResetServerAddresses"
        self.run(
            f"$a = Get-NetAdapter -IncludeHidden | Where-Object {{ $_.InterfaceGuid -eq '{{{guid}}}' }}; "
            "if (-not $a) { throw 'Saved network adapter is unavailable; journal retained' }; "
            f"$a | Get-DnsClientServerAddress -AddressFamily {family} | "
            f"Set-DnsClientServerAddress {action}"
        )

    def browser_snapshot(self):
        import winreg

        entries = []
        for path, name, value, kind in (
            (r"SOFTWARE\Policies\Microsoft\Edge", "DnsOverHttpsMode", "off", winreg.REG_SZ),
            (r"SOFTWARE\Policies\Google\Chrome", "DnsOverHttpsMode", "off", winreg.REG_SZ),
            (r"SOFTWARE\Policies\Mozilla\Firefox\DNSOverHTTPS", "Enabled", 0, winreg.REG_DWORD),
            (r"SOFTWARE\Policies\Mozilla\Firefox\DNSOverHTTPS", "Locked", 1, winreg.REG_DWORD),
        ):
            old = None
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, path) as key:
                    old = list(winreg.QueryValueEx(key, name))
            except FileNotFoundError:
                pass
            entries.append({"path": path, "name": name, "value": value, "kind": kind, "old": old})
        return entries

    def set_browser(self, item, restore=False):
        import winreg

        with winreg.CreateKeyEx(
            winreg.HKEY_LOCAL_MACHINE, item["path"], 0, winreg.KEY_SET_VALUE
        ) as key:
            if restore and item["old"] is None:
                try:
                    winreg.DeleteValue(key, item["name"])
                except FileNotFoundError:
                    pass
            else:
                value, kind = item["old"] if restore else (item["value"], item["kind"])
                winreg.SetValueEx(key, item["name"], 0, kind, value)

    def flush(self):
        self.run("Clear-DnsClientCache")


class WebProtection:
    def __init__(self, core, journal: Path, network=None, ready=None):
        self.core, self.journal = core, journal
        self.network = network or WindowsNetwork()
        self.halt = threading.Event()
        self.thread = None
        self.policy_key = None
        self.ready = ready or (lambda: True)

    def save(self, state):
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.journal.with_suffix(".tmp")
        temporary.write_text(json.dumps(state), encoding="utf-8")
        temporary.replace(self.journal)

    def restore(self):
        if not self.journal.exists():
            return
        state = json.loads(self.journal.read_text(encoding="utf-8"))
        state["restoring"] = True
        self.save(state)
        errors = []
        for group, setter in (
            ("adapters", self.network.set_dns),
            ("browsers", self.network.set_browser),
        ):
            for item in list(state[group]):
                try:
                    setter(item, restore=True)
                    state[group].remove(item)
                    self.save(state)
                except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
                    errors.append(str(exc))
        if errors:
            raise RuntimeError("; ".join(errors))
        self.network.flush()
        self.journal.unlink()
        self.policy_key = None

    def enable(self):
        if not self.ready():
            raise RuntimeError("DNS proxy is not running on both loopback addresses")
        if self.journal.exists():
            previous = json.loads(self.journal.read_text(encoding="utf-8"))
            if previous.get("restoring"):
                self.restore()
        state = (
            json.loads(self.journal.read_text(encoding="utf-8"))
            if self.journal.exists()
            else {"adapters": [], "browsers": self.network.browser_snapshot()}
        )
        current = self.network.snapshot()
        if not current:
            raise RuntimeError("No active network adapter")
        saved = {item["id"] for item in state["adapters"]}
        for item in current:
            if item["id"] not in saved:
                state["adapters"].append(item)
        self.save(state)
        for item in state["browsers"]:
            self.network.set_browser(item)
        changed = False
        for item in current:
            expected = ["127.0.0.1"] if item["family"] == "IPv4" else ["::1"]
            if item["servers"] != expected:
                self.network.set_dns(item)
                changed = True
        context = self.core.filter_context()
        key = (context[0], context[1].get("version")) if context else None
        if changed or key != self.policy_key:
            self.network.flush()
        self.policy_key = key

    def tick(self):
        try:
            if self.core.filter_context():
                self.enable()
                self.core._web_protection = "active"
            else:
                self.restore()
                self.core._web_protection = "inactive"
            self.core._web_protection_error = None
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as exc:
            self.core._web_protection = "error"
            self.core._web_protection_error = str(exc)
            try:
                self.restore()
            except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as rollback:
                self.core._web_protection_error += f"; restore: {rollback}"

    def start(self):
        def work():
            while not self.halt.is_set():
                self.tick()
                self.halt.wait(10)

        self.thread = threading.Thread(target=work, name="ogk-web-protection", daemon=True)
        self.thread.start()

    def stop(self):
        self.halt.set()
        if self.thread:
            self.thread.join()
        self.restore()


if __name__ == "__main__":
    import argparse
    import os

    parser = argparse.ArgumentParser(description="Restore agent-owned DNS and browser settings")
    parser.add_argument("--restore", action="store_true", required=True)
    parser.add_argument(
        "--data-dir",
        type=Path,
        default=Path(
            os.environ.get(
                "OGK_AGENT_DATA_DIR",
                str(Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "OpenGuardKids"),
            )
        ),
    )
    args = parser.parse_args()
    WebProtection(None, args.data_dir / "network-backup.json").restore()
