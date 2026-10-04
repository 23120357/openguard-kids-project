import json
from datetime import UTC, datetime

import pytest
from argon2 import PasswordHasher

from agent import named_pipe
from agent.core import AgentCore
from agent.ipc_protocol import (
    MAX_MESSAGE_BYTES,
    PROTOCOL_VERSION,
    ProtocolError,
    decode_message,
    encode_message,
    new_request,
    parse_request,
    success_response,
)
from agent.time_control import ALL_ALLOWED_DAY, F1Controller, MemoryTimeStore, TimePolicy


class FakeClock:
    def __init__(self, value=100.0):
        self.value = value

    def __call__(self):
        return self.value


def enabled_controller(clock: FakeClock) -> F1Controller:
    policy = TimePolicy(
        version=1,
        enabled=True,
        weekday_minutes=30,
        weekend_minutes=60,
        schedule=(ALL_ALLOWED_DAY,) * 7,
    )
    return F1Controller(
        policy,
        MemoryTimeStore(),
        monotonic_clock=clock,
        wall_clock=lambda: datetime(2026, 9, 28, 9, tzinfo=UTC).timestamp() + clock.value,
        to_local_datetime=lambda value: datetime.fromtimestamp(value, UTC),
    )


def test_protocol_round_trip():
    request = new_request("ping")
    assert decode_message(encode_message(request)) == request
    assert parse_request(request).message_type == "ping"


def test_protocol_rejects_wrong_version_and_non_object():
    with pytest.raises(ProtocolError):
        parse_request(
            {
                "protocol_version": PROTOCOL_VERSION + 1,
                "request_id": "one",
                "type": "ping",
                "payload": {},
            }
        )
    with pytest.raises(ProtocolError):
        decode_message(json.dumps(["not", "an", "object"]).encode())


def test_protocol_rejects_oversized_message():
    with pytest.raises(ProtocolError):
        encode_message({"value": "x" * MAX_MESSAGE_BYTES})
    with pytest.raises(ProtocolError):
        decode_message(b"x" * (MAX_MESSAGE_BYTES + 1))


def test_service_status_caps_audit_before_named_pipe_encoding():
    core = AgentCore(
        child_name="Avery",
        child_pin_hash=PasswordHasher().hash("123456"),
        time_controller=enabled_controller(FakeClock()),
    )
    assert core.handle(new_request("start_session", {"pin": "123456"}))["ok"]
    large_change = {"schedule": [ALL_ALLOWED_DAY] * 7}
    core.set_child_audit(
        [
            {
                "id": str(index),
                "action": "policy_updated",
                "ts": 1.0,
                "actor": "parent@example.test",
                "ip": "127.0.0.1",
                "old_value": large_change,
                "new_value": large_change,
            }
            for index in range(50)
        ]
    )
    status = core.status()
    assert len(status["child_audit"]) == 5
    assert len(encode_message(success_response("status", status))) <= MAX_MESSAGE_BYTES


def test_oversized_pipe_response_does_not_crash_service(monkeypatch):
    request = new_request("get_status")
    written = []
    monkeypatch.setattr(
        named_pipe.win32file, "ReadFile", lambda _pipe, _size: (0, encode_message(request))
    )
    monkeypatch.setattr(
        named_pipe.win32file, "WriteFile", lambda _pipe, payload: written.append(payload)
    )
    monkeypatch.setattr(named_pipe.win32file, "FlushFileBuffers", lambda _pipe: None)
    server = named_pipe.NamedPipeServer(
        lambda message: success_response(message["request_id"], {"blob": "x" * MAX_MESSAGE_BYTES})
    )
    server._serve_client(object())
    response = decode_message(written[0])
    assert response["ok"] is False
    assert response["error"]["code"] == "response_too_large"


def test_core_status_is_transparent_when_f1_is_unavailable():
    clock = FakeClock()
    core = AgentCore(clock=clock, wall_clock=lambda: 1234.5)
    status = core.status()
    assert status["service"] == "running"
    assert status["service_started_at"] == 1234.5
    assert status["remaining_minutes"] is None
    assert status["agent_active"] is False
    assert status["capabilities"]["time_enforcement"] is False
    assert status["capabilities"]["activity_monitoring"] is False
    assert status["capabilities"]["dns_filtering"] is False


def test_ui_presence_expires():
    clock = FakeClock()
    core = AgentCore(clock=clock, time_controller=enabled_controller(clock))
    response = core.handle(
        new_request(
            "ui_heartbeat",
            {"visible": True, "idle_seconds": 0, "session_locked": False},
        )
    )
    assert response["ok"] is True
    assert response["data"]["ui_connected"] is True
    assert response["data"]["agent_active"] is True
    clock.value += core.UI_PRESENCE_TIMEOUT_SECONDS + 0.1
    status = core.status()
    assert status["ui_connected"] is False
    assert status["agent_active"] is False
    assert status["time_control"]["mode"] == "inert_no_tray"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"visible": 1, "idle_seconds": 0, "session_locked": False},
        {"visible": True, "idle_seconds": True, "session_locked": False},
        {"visible": True, "idle_seconds": -1, "session_locked": False},
        {"visible": True, "idle_seconds": 0, "session_locked": "no"},
    ],
)
def test_ui_heartbeat_rejects_untrusted_activity_payload(payload):
    response = AgentCore().handle(new_request("ui_heartbeat", payload))
    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_activity"


def test_time_event_acknowledgement_is_validated_and_forwarded():
    clock = FakeClock()
    store = MemoryTimeStore()
    controller = enabled_controller(clock)
    controller.store = store
    event = store.add_event("test", 1, "message", {})
    core = AgentCore(clock=clock, time_controller=controller)

    response = core.handle(new_request("ack_time_events", {"event_ids": [event["id"]]}))
    assert response["ok"] is True
    assert store.pending_events() == []

    invalid = core.handle(new_request("ack_time_events", {"event_ids": "not-a-list"}))
    assert invalid["error"]["code"] == "invalid_event_ids"


def test_demo_time_reduction_and_lock_acknowledgement():
    clock = FakeClock()
    controller = enabled_controller(clock)
    core = AgentCore(clock=clock, time_controller=controller)
    core.handle(
        new_request(
            "ui_heartbeat",
            {"visible": True, "idle_seconds": 0, "session_locked": False},
        )
    )

    reduced = core.handle(new_request("demo_reduce_time", {"seconds": 60}))
    assert reduced["ok"] is True
    assert reduced["data"]["reduced_seconds"] == 60

    acknowledged = core.handle(new_request("ack_lock", {"reason": "quota_exhausted"}))
    assert acknowledged["ok"] is True


@pytest.mark.parametrize("seconds", [None, True, 0, 3601, "60"])
def test_demo_time_reduction_rejects_invalid_seconds(seconds):
    response = AgentCore().handle(new_request("demo_reduce_time", {"seconds": seconds}))
    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_seconds"


def test_lock_acknowledgement_rejects_unknown_reason():
    response = AgentCore().handle(new_request("ack_lock", {"reason": "anything"}))
    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_lock_reason"


@pytest.mark.parametrize("minutes", [5, 15, 30, 120])
def test_more_time_request_is_queued_for_parent_dashboard(minutes):
    core = AgentCore(
        child_name="Avery",
        child_pin_hash=PasswordHasher().hash("123456"),
    )
    login = core.handle(new_request("start_session", {"pin": "123456"}))
    assert login["ok"] is True
    response = core.handle(new_request("request_more_time", {"minutes": minutes}))
    assert response["ok"] is True
    assert response["data"]["accepted"] is True
    assert response["data"]["delivery"] == "queued_for_parent_dashboard"
    assert response["data"]["requester"] == "Avery"
    assert core.status()["extra_time_requests_received"] == 1


def test_more_time_request_keeps_decision_status_after_delivery():
    clock = FakeClock()
    controller = enabled_controller(clock)
    core = AgentCore(
        clock=clock,
        time_controller=controller,
        child_name="Avery",
        child_pin_hash=PasswordHasher().hash("123456"),
    )
    assert core.handle(new_request("start_session", {"pin": "123456"}))["ok"]
    first = core.handle(new_request("request_more_time", {"minutes": 18}))["data"]
    first_id = first["local_request_id"]
    core.set_remote_request_status(first_id, "pending")
    core.acknowledge_time_request(first_id)
    assert core.pending_time_requests() == []
    assert core.status()["time_requests"][-1]["status"] == "pending"

    core.apply_remote_command(
        {
            "id": "grant-18",
            "type": "add_time",
            "payload": {"minutes": 18, "client_request_id": first_id},
        }
    )
    assert core.status()["time_requests"][-1]["status"] == "approved"
    core.set_remote_request_status(first_id, "pending")
    assert core.status()["time_requests"][-1]["status"] == "approved"

    second = core.handle(new_request("request_more_time", {"minutes": 12}))["data"]
    second_id = second["local_request_id"]
    core.acknowledge_time_request(second_id)
    core.set_child_audit(
        [
            {
                "action": "time_request_decided",
                "new_value": {"client_request_id": second_id, "status": "rejected"},
            }
        ]
    )
    assert core.status()["time_requests"][-1]["status"] == "rejected"


def test_more_time_request_requires_enrollment_and_active_child_session():
    response = AgentCore().handle(new_request("request_more_time", {"minutes": 15}))
    assert response["ok"] is False
    assert response["error"]["code"] == "remote_not_enrolled"

    core = AgentCore(
        child_name="Avery",
        child_pin_hash=PasswordHasher().hash("123456"),
    )
    unauthenticated = core.handle(new_request("request_more_time", {"minutes": 15}))
    assert unauthenticated["ok"] is False
    assert unauthenticated["error"]["code"] == "no_active_session"


@pytest.mark.parametrize("minutes", [None, True, 0, 121, "15"])
def test_more_time_request_rejects_invalid_minutes(minutes):
    response = AgentCore().handle(new_request("request_more_time", {"minutes": minutes}))
    assert response["ok"] is False
    assert response["error"]["code"] == "invalid_minutes"


def test_unknown_operation_and_invalid_request_are_safe_errors():
    core = AgentCore()
    unsupported = core.handle(new_request("do_everything"))
    invalid = core.handle({"request_id": "broken"})
    assert unsupported["error"]["code"] == "unsupported_operation"
    assert invalid["error"]["code"] == "invalid_request"
