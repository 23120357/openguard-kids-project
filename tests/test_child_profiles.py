"""Multi-child profile selection on one enrolled development device."""

import time
from copy import deepcopy
from datetime import UTC, datetime

import pytest
from argon2 import PasswordHasher
from fastapi.testclient import TestClient
from sqlalchemy import inspect

from agent.core import AgentCore
from agent.ipc_protocol import new_request
from agent.remote_sync import verified_profiles_document
from agent.time_control import ALL_ALLOWED_DAY, F1Controller, MemoryTimeStore, TimePolicy
from server.app.database import build_database, migrate_development_schema
from server.app.policy_signing import verify_policy
from tests.conftest import pair, sign_in


def device_headers(tokens):
    return {"Authorization": "Bearer " + tokens["access_token"]}


def test_parent_pin_profiles_and_per_child_device_policy(parent, child, app):
    second = parent.post("/api/children", json={"display_name": "Bé Bình", "pin": "654321"})
    assert second.status_code == 201
    second_id = second.json()["id"]
    invalid = parent.post("/api/children", json={"display_name": "Sai", "pin": "123"})
    assert invalid.status_code == 422
    listed = parent.get("/api/children").json()
    assert all(row["has_pin"] for row in listed)
    assert all("pin_hash" not in row for row in listed)

    tokens, _ = pair(parent, child)
    profiles = parent.get("/api/device/profiles", headers=device_headers(tokens)).json()
    assert {row["id"] for row in profiles["profiles"]} == {child["id"], second_id}
    assert profiles["primary_child_id"] == child["id"]
    envelope = dict(profiles)
    integrity = envelope.pop("integrity")
    assert verify_policy(envelope, integrity["signature"], tokens["policy_signing_key"])
    verified = verified_profiles_document(profiles, tokens["policy_signing_key"])
    assert len(verified["profiles"]) == 2
    with pytest.raises(ValueError, match="another device"):
        verified_profiles_document(profiles, tokens["policy_signing_key"], "wrong-device")
    tampered = deepcopy(profiles)
    tampered["profiles"][0]["display_name"] = "Altered"
    with pytest.raises(ValueError, match="signature"):
        verified_profiles_document(tampered, tokens["policy_signing_key"])

    changed = parent.put(f"/api/children/{second_id}/pin", json={"pin": "111222"})
    assert changed.status_code == 200
    refreshed = parent.get("/api/device/profiles", headers=device_headers(tokens)).json()
    assert refreshed != profiles
    assert all("pin_hash" not in row for row in parent.get("/api/children").json())

    updated = parent.put(
        f"/api/children/{second_id}/policy",
        json={"expected_version": 1, "weekday_minutes": 11, "weekend_minutes": 12},
    )
    assert updated.status_code == 200
    session = parent.post(
        "/api/device/session",
        headers=device_headers(tokens),
        json={"active_child_id": second_id, "active_user": "Bé Bình"},
    )
    assert session.status_code == 200
    assert session.json()["active_child_id"] == second_id
    assert parent.get("/api/policy", headers=device_headers(tokens)).json()["weekday_minutes"] == 11
    assert parent.get("/api/devices").json()[0]["active_child_id"] == second_id

    request = parent.post(
        "/api/device/requests",
        headers=device_headers(tokens),
        json={
            "request_id": "second-child-request",
            "child_id": second_id,
            "requester": "Bé Bình",
            "minutes": 17,
            "created_at": time.time(),
        },
    )
    assert request.status_code == 201
    assert parent.get("/api/time-requests").json()[0]["child_name"] == "Bé Bình"
    grant = parent.post(
        f"/api/devices/{tokens['device_id']}/commands",
        json={"command_type": "add_time", "minutes": 15},
    )
    assert grant.status_code == 202
    heartbeat = parent.post(
        "/api/heartbeat", headers=device_headers(tokens), json={"policy_version": 0}
    ).json()
    assert heartbeat["commands"][0]["child_id"] == second_id

    with TestClient(app) as other:
        sign_in(other, "other@example.test")
        foreign = other.post("/api/children", json={"display_name": "Khác", "pin": "999999"}).json()
    denied = parent.post(
        "/api/device/session",
        headers=device_headers(tokens),
        json={"active_child_id": foreign["id"]},
    )
    assert denied.status_code == 403


def test_agent_switches_child_without_sharing_daily_usage():
    class Clock:
        value = 100.0

        def __call__(self):
            return self.value

    clock = Clock()
    base = datetime(2026, 9, 28, 9, tzinfo=UTC).timestamp()
    policies = {
        "child-a": TimePolicy(1, True, 5, 5, (ALL_ALLOWED_DAY,) * 7),
        "child-b": TimePolicy(1, True, 10, 10, (ALL_ALLOWED_DAY,) * 7),
    }
    profiles = [
        {
            "id": child_id,
            "display_name": child_id,
            "pin_hash": PasswordHasher().hash(pin),
            "policy": policies[child_id],
        }
        for child_id, pin in (("child-a", "123456"), ("child-b", "654321"))
    ]
    controllers = {}

    def controller_factory(child_id, policy):
        controller = F1Controller(
            policy,
            MemoryTimeStore(),
            monotonic_clock=clock,
            wall_clock=lambda: base + clock.value,
            to_local_datetime=lambda value: datetime.fromtimestamp(value, UTC),
        )
        controllers[child_id] = controller
        return controller

    core = AgentCore(clock=clock, wall_clock=lambda: base + clock.value)
    core.configure_remote_pending()
    core.configure_profiles(profiles, controller_factory)
    assert {row["id"] for row in core.status()["profiles"]} == {"child-a", "child-b"}
    assert all("pin_hash" not in row for row in core.status()["profiles"])
    wrong = core.handle(new_request("start_session", {"child_id": "child-b", "pin": "123456"}))
    assert wrong["ok"] is False

    def heartbeat():
        return core.handle(
            new_request(
                "ui_heartbeat", {"visible": True, "idle_seconds": 0, "session_locked": False}
            )
        )

    assert core.handle(new_request("start_session", {"child_id": "child-a", "pin": "123456"}))["ok"]
    heartbeat()
    for _ in range(5):
        clock.value += 4
        heartbeat()
    assert controllers["child-a"].snapshot()["used_seconds"] == 20
    core.handle(new_request("end_session"))

    clock.value += 5
    assert core.handle(new_request("start_session", {"child_id": "child-b", "pin": "654321"}))["ok"]
    heartbeat()
    for _ in range(2):
        clock.value += 5
        heartbeat()
    assert controllers["child-b"].snapshot()["used_seconds"] == 10
    assert controllers["child-a"].snapshot()["used_seconds"] == 20

    core.apply_remote_command(
        {"id": "grant-b", "type": "add_time", "child_id": "child-b", "payload": {"minutes": 15}}
    )
    assert controllers["child-b"].store.load_state().extra_seconds == 900
    assert controllers["child-a"].store.load_state().extra_seconds == 0


def test_existing_development_database_gets_pin_and_active_profile_columns(tmp_path):
    engine, _ = build_database("sqlite:///" + (tmp_path / "old.db").as_posix())
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE children (id VARCHAR PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE policies (child_id VARCHAR PRIMARY KEY)")
        connection.exec_driver_sql("CREATE TABLE devices (id VARCHAR PRIMARY KEY)")
    migrate_development_schema(engine)
    migrate_development_schema(engine)
    assert "pin_hash" in {column["name"] for column in inspect(engine).get_columns("children")}
    assert "active_child_id" in {
        column["name"] for column in inspect(engine).get_columns("devices")
    }
    assert "policy_signing_key" in {
        column["name"] for column in inspect(engine).get_columns("devices")
    }
