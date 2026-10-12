import copy
import json
from types import SimpleNamespace

import pytest

from agent.web_protection import WebProtection, WindowsNetwork


class Network:
    def __init__(self):
        self.adapters = [
            {"id": "a/IPv4", "guid": "a", "family": "IPv4", "servers": ["9.9.9.9"]},
            {"id": "a/IPv6", "guid": "a", "family": "IPv6", "servers": []},
        ]
        self.browser = "automatic"
        self.fail = False
        self.flushes = 0

    def snapshot(self):
        return copy.deepcopy(self.adapters)

    def browser_snapshot(self):
        return [{"old": self.browser}]

    def set_browser(self, item, restore=False):
        self.browser = item["old"] if restore else "off"

    def set_dns(self, item, restore=False):
        if self.fail and not restore and item["family"] == "IPv6":
            raise RuntimeError("injected failure")
        target = next((a for a in self.adapters if a["id"] == item["id"]), None)
        if target is None:
            raise RuntimeError("Missing adapter")
        target["servers"] = (
            item["servers"] if restore else (["127.0.0.1"] if item["family"] == "IPv4" else ["::1"])
        )

    def flush(self):
        self.flushes += 1


def fixture(tmp_path):
    core = SimpleNamespace(dns_filter_context=lambda: ("child", {"version": 1}, 42))
    network = Network()
    return WebProtection(core, tmp_path / "backup.json", network), core, network


def test_enable_repeat_and_restore_static_dhcp_browser(tmp_path):
    manager, core, network = fixture(tmp_path)
    original = network.snapshot()
    manager.tick()
    manager.tick()
    assert core._web_protection == "active"
    assert network.flushes == 1
    assert network.browser == "off"
    assert network.adapters[1]["servers"] == ["::1"]
    core.dns_filter_context = lambda: None
    manager.tick()
    assert network.snapshot() == original
    assert network.browser == "automatic"
    assert not manager.journal.exists()


def test_partial_failure_rolls_back(tmp_path):
    manager, core, network = fixture(tmp_path)
    original = network.snapshot()
    network.fail = True
    manager.tick()
    assert core._web_protection == "error"
    assert "injected failure" in core._web_protection_error
    assert network.snapshot() == original
    assert network.browser == "automatic"


def test_crash_restart_preserves_original_and_new_adapter(tmp_path):
    manager, core, network = fixture(tmp_path)
    original = network.snapshot()
    manager.tick()
    network.adapters.append({"id": "b/IPv4", "guid": "b", "family": "IPv4", "servers": []})
    restarted = WebProtection(core, manager.journal, network)
    restarted.tick()
    restarted.stop()
    assert network.adapters == original + [
        {"id": "b/IPv4", "guid": "b", "family": "IPv4", "servers": []}
    ]


def test_failed_restore_keeps_journal_for_retry(tmp_path):
    manager, _, network = fixture(tmp_path)
    manager.tick()
    missing = network.adapters.pop()
    with pytest.raises(RuntimeError):
        manager.restore()
    state = json.loads(manager.journal.read_text())
    assert len(state["adapters"]) == 1
    assert state["adapters"][0]["servers"] == []
    network.adapters.append(missing)
    manager.restore()
    assert network.adapters[-1]["servers"] == []
    assert not manager.journal.exists()


def test_backend_targets_family_and_restores_automatic_without_shell_injection():
    network = WindowsNetwork()
    commands = []
    network.run = commands.append
    item = {"guid": "{12345678-1234-1234-1234-123456789012}", "family": "IPv6", "servers": []}
    network.set_dns(item)
    assert "-AddressFamily IPv6" in commands[-1]
    assert "@('::1')" in commands[-1]
    network.set_dns(item, restore=True)
    assert "-ResetServerAddresses" in commands[-1]
    item["servers"] = ["'; Write-Output unsafe"]
    with pytest.raises(ValueError):
        network.set_dns(item, restore=True)


def test_proxy_failure_restores_configuration(tmp_path):
    manager, core, network = fixture(tmp_path)
    original = network.snapshot()
    manager.tick()
    manager.ready = lambda: False
    manager.tick()
    assert core._web_protection == "error"
    assert network.snapshot() == original
    assert network.browser == "automatic"


def test_policy_change_flushes_dns_cache(tmp_path):
    manager, core, network = fixture(tmp_path)
    manager.tick()
    core.dns_filter_context = lambda: ("child", {"version": 2}, 42)
    manager.tick()
    assert network.flushes == 2


def test_incomplete_restore_must_finish_before_reenable(tmp_path):
    manager, core, network = fixture(tmp_path)
    manager.tick()
    missing = network.adapters.pop()
    with pytest.raises(RuntimeError):
        manager.restore()
    manager.tick()
    assert core._web_protection == "error"
    assert network.browser == "automatic"
    network.adapters.append(missing)
    manager.tick()
    assert core._web_protection == "active"
    assert network.browser == "off"
    manager.stop()
    assert network.browser == "automatic"
