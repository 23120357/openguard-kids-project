"""The parent-to-device setup contract, without requiring an installed service."""

import json
from datetime import UTC, datetime

from argon2 import PasswordHasher

from agent.core import AgentCore
from agent.ipc_protocol import new_request
from agent.remote_sync import RemoteConfig, enroll
from agent.time_control import ALL_ALLOWED_DAY, F1Controller, MemoryTimeStore, TimePolicy
from tests.conftest import pair


def test_new_child_has_default_policy_and_unique_username(parent, child):
    policy = parent.get(f"/api/children/{child['id']}/policy").json()
    assert policy["enabled"] is True
    assert policy["weekday_minutes"] == 90
    assert policy["weekend_minutes"] == 120
    duplicate = parent.post("/api/children", json={"display_name": "bé an", "pin": "654321"})
    assert duplicate.status_code == 409


def test_new_device_gets_its_own_policy_verification_key(parent, child, app):
    first, _ = pair(parent, child)
    second, _ = pair(parent, child)
    assert len(first["policy_signing_key"]) >= 32
    assert first["policy_signing_key"] != second["policy_signing_key"]
    assert first["policy_signing_key"] != app.state.settings.policy_signing_key


def test_pairing_then_username_pin_login_uses_child_policy():
    core = AgentCore(pairing_required=True)
    assert core.status()["enrollment"] == {"required": True, "enrolled": False}
    assert core.status()["enforcement_mode"] == "awaiting_pairing"
    assert (
        core.handle(new_request("start_session", {"username": "An", "pin": "123456"}))["ok"]
        is False
    )
    received = []
    core.set_enrollment_callback(received.append)
    assert core.handle(new_request("enroll_device", {"code": "abcd2345"}))["ok"]
    assert received == ["ABCD2345"]
    assert core.status()["enrollment"]["enrolled"] is True
    assert core.handle(new_request("enroll_device", {"code": "ABCD2345"}))["ok"] is False
    policy = TimePolicy(1, True, 42, 43, (ALL_ALLOWED_DAY,) * 7)
    core.configure_profiles(
        [
            {
                "id": "child-a",
                "display_name": "An",
                "pin_hash": PasswordHasher().hash("123456"),
                "policy": policy,
            }
        ],
        lambda child_id, child_policy: F1Controller(
            child_policy,
            MemoryTimeStore(),
            to_local_datetime=lambda value: datetime.fromtimestamp(value, UTC),
        ),
    )
    assert (
        core.handle(new_request("start_session", {"username": "An", "pin": "000000"}))["ok"]
        is False
    )
    assert (
        core.handle(new_request("start_session", {"username": "Unknown", "pin": "123456"}))["ok"]
        is False
    )
    login = core.handle(new_request("start_session", {"username": "aN", "pin": "123456"}))
    assert login["ok"] is True
    assert core.status()["active_child_id"] == "child-a"
    assert core._time_controller.policy.weekday_minutes == 42
    assert core._time_controller.policy.weekend_minutes == 43


def test_enrollment_persists_server_supplied_key_without_shared_env(
    tmp_path, parent, child, monkeypatch
):
    code = parent.post(
        "/api/enrollment-codes", json={"child_id": child["id"], "consent": True}
    ).json()["code"]

    class FakeClient:
        def __init__(self, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def post(self, path, json):
            return parent.post(path, json=json)

    monkeypatch.setattr("agent.remote_sync.httpx.Client", FakeClient)
    path = tmp_path / "remote-config.json"
    enroll(path, "http://127.0.0.1:8000", code, "Child PC")
    saved = RemoteConfig.load(path)
    assert saved.child_id == child["id"]
    assert len(saved.policy_signing_key) >= 32
    assert (
        json.loads(path.read_text(encoding="utf-8"))["policy_signing_key"]
        == saved.policy_signing_key
    )


def test_service_accepts_pairing_over_ipc_and_starts_sync(tmp_path, monkeypatch):
    import agent.windows_service as service

    config_path = tmp_path / "remote-config.json"
    (tmp_path / "bootstrap.json").write_text(
        json.dumps({"server_url": "http://127.0.0.1:8000", "device_name": "Lab PC"}),
        encoding="utf-8",
    )
    calls = []

    def fake_enroll(path, server_url, code, name):
        calls.append((server_url, code, name))
        RemoteConfig(server_url, "device-a", "access", "refresh", "a" * 40, "fingerprint").save(
            path
        )

    class FakeSync:
        def __init__(self, core, path, policy_path):
            self.started = False

        def start(self):
            self.started = True

    monkeypatch.setattr(service, "remote_config_path", lambda: config_path)
    monkeypatch.setattr(service, "enroll", fake_enroll)
    monkeypatch.setattr(service, "RemoteSync", FakeSync)
    runtime = service.ServiceRuntime()
    runtime._running = True
    result = runtime.core.handle(new_request("enroll_device", {"code": "ABCD2345"}))
    assert result["ok"] is True
    assert calls == [("http://127.0.0.1:8000", "ABCD2345", "Lab PC")]
    assert runtime.remote.started is True
    assert runtime.core.status()["enrollment"]["enrolled"] is True


def test_existing_offline_f1_installer_remains_available(tmp_path, monkeypatch):
    import agent.windows_service as service

    monkeypatch.setattr(service, "remote_config_path", lambda: tmp_path / "remote-config.json")
    controller = F1Controller(TimePolicy(1, True, 3, 3, (ALL_ALLOWED_DAY,) * 7), MemoryTimeStore())
    monkeypatch.setattr(service, "build_time_controller", lambda: controller)
    runtime = service.ServiceRuntime()
    assert runtime.core.status()["enrollment"]["required"] is False
    assert runtime.core._time_controller is controller
