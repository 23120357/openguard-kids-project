"""Immediate child requests and parent dashboard change signals."""

import asyncio
import threading
import time
import uuid
from types import SimpleNamespace

from argon2 import PasswordHasher
from sqlalchemy import select

from agent.core import AgentCore
from agent.ipc_protocol import new_request
from agent.remote_sync import RemoteConfig, RemoteSync
from server.app.models import Parent
from server.app.realtime import ParentEvents
from server.app.routes import parent_events
from tests.conftest import pair


def test_time_request_is_sent_without_a_heartbeat(tmp_path, monkeypatch):
    from agent import remote_sync

    config_path = tmp_path / "remote-config.json"
    RemoteConfig(
        "http://127.0.0.1:8000", "device", "access", "refresh", "k" * 40, "fingerprint"
    ).save(config_path)
    core = AgentCore(child_name="An", child_pin_hash=PasswordHasher().hash("123456"))
    sync = RemoteSync(core, config_path, tmp_path / "remote-policy.json")
    sent = threading.Event()

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    class FakeResponse:
        def json(self):
            return {"status": "pending"}

    def send(_client, method, path, **kwargs):
        assert method == "POST"
        assert path == "/api/device/requests"
        assert kwargs["json"]["minutes"] == 15
        sent.set()
        return FakeResponse()

    monkeypatch.setattr(remote_sync.httpx, "Client", FakeClient)
    monkeypatch.setattr(sync, "_request", send)
    worker = threading.Thread(target=sync._time_request_loop, daemon=True)
    worker.start()  # No heartbeat or WebSocket loop is started.
    try:
        assert core.handle(new_request("start_session", {"pin": "123456"}))["ok"]
        response = core.handle(new_request("request_more_time", {"minutes": 15}))
        assert response["ok"]
        assert sent.wait(1)
        deadline = time.monotonic() + 1
        while core.pending_time_requests() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert core.pending_time_requests() == []
    finally:
        sync.stop_event.set()
        sync._request_wake.set()
        worker.join(timeout=2)


def test_device_time_status_is_reported_independently_of_policy_heartbeat(tmp_path, monkeypatch):
    from agent import remote_sync

    config_path = tmp_path / "remote-config.json"
    RemoteConfig(
        "http://127.0.0.1:8000", "device", "access", "refresh", "k" * 40, "fingerprint"
    ).save(config_path)
    sync = RemoteSync(AgentCore(), config_path, tmp_path / "remote-policy.json")
    sent = threading.Event()

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    def send(_client, method, path, **kwargs):
        assert method == "POST"
        assert path == "/api/device/time-status"
        assert kwargs["json"]["active_child_id"] is None
        sent.set()

    monkeypatch.setattr(remote_sync.httpx, "Client", FakeClient)
    monkeypatch.setattr(sync, "_request", send)
    worker = threading.Thread(target=sync._time_status_loop, daemon=True)
    worker.start()  # No policy heartbeat is started.
    try:
        assert sent.wait(1)
    finally:
        sync.stop_event.set()
        sync._time_status_wake.set()
        worker.join(timeout=2)


def test_parent_event_bus_notifies_from_request_thread():
    async def scenario():
        events = ParentEvents()
        queue = await events.subscribe("parent-a")
        await asyncio.to_thread(events.notify, "parent-a", "status")
        assert await asyncio.wait_for(queue.get(), timeout=1) == "status"
        events.unsubscribe("parent-a", queue)

    asyncio.run(scenario())


def test_dashboard_event_stream_requires_parent_login(client):
    response = client.get("/api/parent/events")
    assert response.status_code == 401


def test_authenticated_dashboard_stream_emits_change(parent, app):
    request = SimpleNamespace(cookies={"ogk_session": parent.cookies.get("ogk_session")}, app=app)

    async def scenario():
        response = await parent_events(request)
        stream = response.body_iterator
        assert "event: ready" in await anext(stream)
        with app.state.sessions() as db:
            parent_id = db.scalar(select(Parent.id).where(Parent.email == "parent@example.test"))
        app.state.parent_events.notify(parent_id, "status")
        assert '"kind": "status"' in await asyncio.wait_for(anext(stream), timeout=1)
        await stream.aclose()

    asyncio.run(scenario())


def test_server_signals_dashboard_when_child_requests_time(parent, app):
    signals = []
    app.state.parent_events.notify = lambda parent_id, kind="status": signals.append(
        (parent_id, kind)
    )
    child_response = parent.post("/api/children", json={"display_name": "An", "pin": "123456"})
    assert child_response.status_code == 201
    child = child_response.json()
    assert signals[-1][1] == "children"
    tokens, _ = pair(parent, child)
    response = parent.post(
        "/api/device/requests",
        headers={"Authorization": "Bearer " + tokens["access_token"]},
        json={
            "request_id": str(uuid.uuid4()),
            "child_id": child["id"],
            "requester": "An",
            "minutes": 15,
            "created_at": time.time(),
        },
    )
    assert response.status_code == 201
    assert signals[-1][1] == "status"
    assert parent.get("/api/time-requests").json()[0]["minutes"] == 15
