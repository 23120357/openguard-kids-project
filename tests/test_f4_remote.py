import copy
import json
import time

import pytest

from agent.core import AgentCore
from agent.remote_sync import RemoteConfig, load_cached_remote_policy, verified_time_policy
from agent.time_control import ALL_ALLOWED_DAY, F1Controller, MemoryTimeStore, TimePolicy
from server.app.models import DeviceCommand
from server.app.policy_signing import sign_policy, verify_policy
from tests.conftest import pair


def auth_headers(tokens):
    return {"Authorization": "Bearer " + tokens["access_token"]}


def test_device_policy_is_versioned_and_signed(parent, child, app):
    tokens, _ = pair(parent, child)
    document = parent.get("/api/policy", headers=auth_headers(tokens)).json()
    integrity = document.pop("integrity")
    assert document["version"] == 1
    assert len(document["schedule"]) == 7
    assert verify_policy(document, integrity["signature"], tokens["policy_signing_key"])


def test_agent_rejects_tampered_policy_and_accepts_authentic_policy(parent, child, app):
    tokens, _ = pair(parent, child)
    document = parent.get("/api/policy", headers=auth_headers(tokens)).json()
    policy = verified_time_policy(document, tokens["policy_signing_key"])
    assert policy.weekday_minutes == 90
    tampered = copy.deepcopy(document)
    tampered["weekday_minutes"] = 1440
    with pytest.raises(ValueError, match="signature is invalid"):
        verified_time_policy(tampered, tokens["policy_signing_key"])


def test_agent_rejects_tampered_cached_policy_after_restart(tmp_path):
    key = "a-test-policy-key-with-at-least-32-characters"
    config_path = tmp_path / "remote-config.json"
    policy_path = tmp_path / "remote-policy.json"
    RemoteConfig("http://127.0.0.1:8000", "d", "a", "r", key, "f").save(config_path)
    policy = {
        "child_id": "c",
        "version": 2,
        "enabled": True,
        "weekday_minutes": 30,
        "weekend_minutes": 45,
        "schedule": [ALL_ALLOWED_DAY] * 7,
        "warnings_minutes": [10, 5, 1],
        "grace_seconds": 60,
        "idle_threshold_seconds": 300,
        "issued_at": 1.0,
    }
    document = {
        **policy,
        "integrity": {"algorithm": "hmac-sha256", "signature": sign_policy(policy, key)},
    }
    policy_path.write_text(json.dumps(document), encoding="utf-8")
    assert load_cached_remote_policy(config_path, policy_path).weekday_minutes == 30
    document["weekday_minutes"] = 1440
    policy_path.write_text(json.dumps(document), encoding="utf-8")
    with pytest.raises(ValueError, match="signature is invalid"):
        load_cached_remote_policy(config_path, policy_path)


def test_schedule_policy_update_is_audited_and_announced(parent, child, app):
    tokens, _ = pair(parent, child)
    schedule = [ALL_ALLOWED_DAY] * 7
    schedule[0] = "0" * 20 + "1" * 20 + "0" * 8
    response = parent.put(
        f"/api/children/{child['id']}/policy",
        json={
            "expected_version": 1,
            "enabled": True,
            "weekday_minutes": 45,
            "weekend_minutes": 75,
            "schedule": schedule,
        },
    )
    assert response.status_code == 200
    assert response.json()["version"] == 2
    heartbeat = parent.post(
        "/api/heartbeat",
        headers=auth_headers(tokens),
        json={"policy_version": 1, "used_seconds": 10},
    ).json()
    assert heartbeat["policy_version"] == 2
    assert heartbeat["heartbeat_after_seconds"] <= 60
    audit = parent.get("/api/audit").json()[0]
    assert audit["action"] == "policy_updated"
    assert audit["old_value"]["version"] == 1
    assert audit["new_value"]["schedule"][0] == schedule[0]


def test_policy_change_wakes_connected_agent(parent, child):
    tokens, _ = pair(parent, child)
    with parent.websocket_connect(
        "/api/device/ws?access_token=" + tokens["access_token"]
    ) as websocket:
        updated = parent.put(
            f"/api/children/{child['id']}/policy",
            json={"expected_version": 1, "weekday_minutes": 7, "weekend_minutes": 7},
        )
        assert updated.status_code == 200
        assert websocket.receive_json() == {"kind": "policy_changed", "child_id": child["id"]}


def test_device_time_status_populates_parent_dashboard(parent, child):
    tokens, _ = pair(parent, child)
    reported = parent.post(
        "/api/device/time-status",
        headers=auth_headers(tokens),
        json={
            "active_child_id": child["id"],
            "active_user": child["display_name"],
            "active_since": time.time(),
            "policy_version": 2,
            "used_seconds": 135,
            "remaining_seconds": 285,
            "quota_seconds": 420,
            "extra_seconds": 0,
            "active_usage": True,
        },
    )
    assert reported.status_code == 200
    device = parent.get("/api/devices").json()[0]
    assert device["used_seconds"] == 135
    assert device["remaining_seconds"] == 285
    assert device["active_usage"] is True
    assert device["active_user"] == child["display_name"]
    assert device["time_status_at"] is not None


def test_emergency_command_falls_back_to_heartbeat_and_child_audit(parent, child, app):
    tokens, _ = pair(parent, child)
    session = parent.post(
        "/api/device/session",
        headers=auth_headers(tokens),
        json={"active_child_id": child["id"], "active_user": child["display_name"]},
    )
    assert session.status_code == 200
    response = parent.post(
        f"/api/devices/{tokens['device_id']}/commands",
        json={"command_type": "add_time", "minutes": 15},
    )
    assert response.status_code == 202
    assert response.json()["realtime_delivered"] is False
    heartbeat = parent.post(
        "/api/heartbeat",
        headers=auth_headers(tokens),
        json={"policy_version": 1},
    ).json()
    assert heartbeat["commands"][0]["type"] == "add_time"
    assert heartbeat["commands"][0]["payload"] == {"minutes": 15}
    child_audit = parent.get("/api/device/audit", headers=auth_headers(tokens)).json()
    assert child_audit[0]["action"] == "emergency_command_created"
    assert child_audit[0]["actor"] == "parent@example.test"
    assert child_audit[0]["ip"] == "testclient"


def test_websocket_delivers_and_acknowledges_emergency_command(parent, child, app):
    tokens, _ = pair(parent, child)
    url = "/api/device/ws?access_token=" + tokens["access_token"]
    with parent.websocket_connect(url) as websocket:
        started = time.monotonic()
        response = parent.post(
            f"/api/devices/{tokens['device_id']}/commands",
            json={"command_type": "lock_now"},
        )
        message = websocket.receive_json()
        elapsed = time.monotonic() - started
        assert response.json()["realtime_delivered"] is True
        assert message["command"]["type"] == "lock_now"
        assert elapsed < 5
        command_id = message["command"]["id"]
        websocket.send_json(
            {"kind": "command_ack", "command_id": command_id, "result": "test_applied"}
        )
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        with app.state.sessions() as db:
            if db.get(DeviceCommand, command_id).status == "acknowledged":
                break
        time.sleep(0.01)
    with app.state.sessions() as db:
        assert db.get(DeviceCommand, command_id).status == "acknowledged"


def test_time_request_decisions_reach_agent_with_client_request_id(parent, child):
    tokens, _ = pair(parent, child)
    url = "/api/device/ws?access_token=" + tokens["access_token"]
    with parent.websocket_connect(url) as websocket:
        for client_id, approved in (("approved-request", True), ("rejected-request", False)):
            created = parent.post(
                "/api/device/requests",
                headers=auth_headers(tokens),
                json={
                    "request_id": client_id,
                    "child_id": child["id"],
                    "requester": child["display_name"],
                    "minutes": 18,
                    "created_at": time.time(),
                },
            )
            assert created.status_code == 201
            decided = parent.post(
                f"/api/time-requests/{created.json()['id']}/decision",
                json={"approved": approved},
            )
            assert decided.status_code == 200
            message = websocket.receive_json()
            if approved:
                assert message["kind"] == "command"
                assert message["command"]["payload"]["client_request_id"] == client_id
            else:
                assert message == {
                    "kind": "time_request_decision",
                    "client_request_id": client_id,
                    "status": "rejected",
                }
            audit = parent.get("/api/device/audit", headers=auth_headers(tokens)).json()
            decision = next(row for row in audit if row["action"] == "time_request_decided")
            assert decision["new_value"]["client_request_id"] == client_id


def test_core_applies_remote_lock_once_and_acks_after_tray_lock():
    controller = F1Controller(
        TimePolicy(
            version=1,
            enabled=True,
            weekday_minutes=90,
            weekend_minutes=120,
            schedule=(ALL_ALLOWED_DAY,) * 7,
        ),
        MemoryTimeStore(),
    )
    core = AgentCore(time_controller=controller)
    heartbeat = {
        "protocol_version": 1,
        "type": "ui_heartbeat",
        "request_id": "present",
        "payload": {"visible": True, "idle_seconds": 0, "session_locked": False},
    }
    assert core.handle(heartbeat)["ok"] is True
    command = {"id": "lock-1", "type": "lock_now", "payload": {}}
    core.apply_remote_command(command)
    core.apply_remote_command(command)
    assert core.status()["time_control"]["remote_command_id"] == "lock-1"
    result = core.handle(
        {
            "protocol_version": 1,
            "type": "ack_lock",
            "request_id": "ack",
            "payload": {"reason": "remote_lock", "command_id": "lock-1"},
        }
    )
    assert result["ok"] is True
    assert core.status()["time_control"].get("remote_command_id") is None
    assert core.drain_command_acks() == [
        {"command_id": "lock-1", "result": "workstation_lock_requested"}
    ]


def test_core_add_time_command_is_idempotent():
    store = MemoryTimeStore()
    controller = F1Controller(
        TimePolicy(
            version=1,
            enabled=True,
            weekday_minutes=90,
            weekend_minutes=120,
            schedule=(ALL_ALLOWED_DAY,) * 7,
        ),
        store,
    )
    controller.reduce_remaining_for_demo(900)
    core = AgentCore(time_controller=controller)
    command = {"id": "add-1", "type": "add_time", "payload": {"minutes": 15}}
    core.apply_remote_command(command)
    core.apply_remote_command(command)
    events = [event for event in store.events if event["type"] == "remote_time_added"]
    assert len(events) == 1
    assert core.drain_command_acks()[0]["result"] == "restored_900_seconds"
