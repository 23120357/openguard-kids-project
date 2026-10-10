import copy
import time
import uuid
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from dnslib import RCODE, DNSRecord
from fastapi.testclient import TestClient
from sqlalchemy import select

from agent.event_queue import RETENTION_SECONDS, EventQueue
from agent.filtering import DNSProxy, app_decision, domain_decision
from agent.remote_sync import RemoteConfig, RemoteSync
from common.domains import event_domain
from server.app.event_models import ActivityEvent
from server.app.event_routes import expire_events

from .conftest import pair, sign_in


def event(tokens, child, **kwargs):
    doc = {
        "id": str(uuid.uuid4()),
        "generation": 0,
        "event": {
            "ts": time.time(),
            "device_id": tokens["device_id"],
            "child_id": child["id"],
            "type": "blocked_domain",
            "subject": "example.org",
            "duration_sec": 0,
            "policy_id": "filter:1",
        },
        "explanation": {
            "reason": "Trang web không nằm trong danh sách cho phép.",
            "rule_author": "Phụ huynh",
        },
    }
    doc["event"].update(kwargs)
    return doc


def post(parent, tokens, items):
    return parent.post(
        "/api/device/activity-events",
        json={"events": items},
        headers={"Authorization": "Bearer " + tokens["access_token"]},
    )


def test_retry_is_idempotent_and_keeps_explanation(parent, child):
    tokens, _ = pair(parent, child)
    item = event(tokens, child)
    for _ in range(2):
        result = post(parent, tokens, [item])
        assert result.status_code == 200
        assert result.json()["acknowledged"] == [item["id"]]
    rows = parent.get(f"/api/children/{child['id']}/activity-events").json()["items"]
    assert len(rows) == 1
    assert rows[0]["event"] == item["event"]
    assert rows[0]["explanation"] == item["explanation"]


def test_key_reuse_conflict_rolls_back_entire_batch(parent, child):
    tokens, _ = pair(parent, child)
    item = event(tokens, child)
    assert post(parent, tokens, [item]).status_code == 200
    changed = copy.deepcopy(item)
    changed["explanation"]["reason"] = "Different reason"
    assert post(parent, tokens, [event(tokens, child), changed]).status_code == 409
    assert len(parent.get(f"/api/children/{child['id']}/activity-events").json()["items"]) == 1


@pytest.mark.parametrize(
    "subject",
    ["https://example.org/a", "www.example.org", "user:data@example.org", "example.org/path"],
)
def test_domain_payload_rejects_urls_and_subdomains(parent, child, subject):
    tokens, _ = pair(parent, child)
    assert post(parent, tokens, [event(tokens, child, subject=subject)]).status_code == 422


def test_event_device_and_child_ownership(parent, child, app):
    tokens, _ = pair(parent, child)
    assert (
        post(parent, tokens, [event(tokens, child, device_id="another-device")]).status_code == 403
    )
    with TestClient(app) as other:
        sign_in(other, "other@example.test")
        other_child = other.post(
            "/api/children", json={"display_name": "Other", "pin": "654321"}
        ).json()
        assert other.get(f"/api/children/{child['id']}/activity-events").status_code == 404
        assert other.delete(f"/api/children/{child['id']}/activity-data").status_code == 404
    assert (
        post(parent, tokens, [event(tokens, child, child_id=other_child["id"])]).status_code == 403
    )


def test_event_auth_and_csrf_required(client, parent, child):
    tokens, _ = pair(parent, child)
    assert (
        parent.post(
            "/api/device/activity-events", json={"events": [event(tokens, child)]}
        ).status_code
        == 401
    )
    response = parent.delete(
        f"/api/children/{child['id']}/activity-data", headers={"X-CSRF-Token": ""}
    )
    assert response.status_code == 403


def test_retention_purges_and_drops_late_events(parent, child, app):
    tokens, _ = pair(parent, child)
    old = event(tokens, child, ts=time.time() - RETENTION_SECONDS - 10)
    assert post(parent, tokens, [old]).json()["discarded"] == [old["id"]]
    item = event(tokens, child)
    assert post(parent, tokens, [item]).status_code == 200
    expire_events(app.state.sessions, now=time.time() + RETENTION_SECONDS + 10)
    with app.state.sessions() as db:
        assert not db.scalars(select(ActivityEvent)).all()
    assert post(parent, tokens, [event(tokens, child, ts=time.time() + 600)]).status_code == 422


def test_delete_fences_offline_retries_and_reports_pending_devices(parent, child):
    tokens, _ = pair(parent, child)
    item = event(tokens, child)
    post(parent, tokens, [item])
    deleted = parent.delete(f"/api/children/{child['id']}/activity-data").json()
    assert deleted["generation"] == 1
    assert deleted["pending_devices"][0]["id"] == tokens["device_id"]
    assert post(parent, tokens, [item]).json()["discarded"] == [item["id"]]
    new = event(tokens, child)
    new["generation"] = 1
    assert post(parent, tokens, [new]).json()["acknowledged"] == [new["id"]]
    headers = {"Authorization": "Bearer " + tokens["access_token"]}
    assert (
        parent.post(
            "/api/device/event-state/ack", json={"generations": {child["id"]: 0}}, headers=headers
        ).status_code
        == 409
    )
    assert (
        parent.post(
            "/api/device/event-state/ack", json={"generations": {child["id"]: 1}}, headers=headers
        ).status_code
        == 200
    )
    assert parent.get(f"/api/children/{child['id']}/activity-data/deletion").json()["complete"]


def test_delete_waits_for_every_household_device(parent, child, app):
    tokens, _ = pair(parent, child)
    sibling = parent.post("/api/children", json={"display_name": "Sibling", "pin": "456789"}).json()
    sibling_tokens, _ = pair(parent, sibling)
    from server.app.models import Device

    with app.state.sessions() as db:
        db.get(Device, sibling_tokens["device_id"]).revoked = True
        db.commit()
    result = parent.delete(f"/api/children/{child['id']}/activity-data").json()
    assert {d["id"] for d in result["pending_devices"]} == {
        tokens["device_id"],
        sibling_tokens["device_id"],
    }
    assert not result["complete"]
    assert any(d["revoked"] for d in result["pending_devices"])


def test_queue_survives_restart_until_ack_and_retains_history(tmp_path):
    path = tmp_path / "events.db"
    q = EventQueue(path)
    id = q.append(
        device_id="d",
        child_id="c",
        type="blocked_domain",
        subject="example.org",
        policy_id="1",
        reason="blocked",
    )
    q = EventQueue(path)
    assert q.pending()[0]["id"] == id
    q.acknowledge([id])
    assert q.pending() == []
    assert q.history("c")[0]["id"] == id
    q.acknowledge_notifications("another-child", [id])
    assert q.notifications("c")
    q.acknowledge_notifications("c", [id])
    assert q.notifications("c") == []


def test_queue_erasure_is_per_child_and_persistent(tmp_path):
    q = EventQueue(tmp_path / "events.db")
    for child_id in ["a", "b"]:
        q.append(
            device_id="d", child_id=child_id, type="blocked_app", subject="game.exe", policy_id="1"
        )
    q.apply_generations({"a": 1, "b": 0})
    assert q.history("a") == []
    assert q.history("b")
    q.append(device_id="d", child_id="a", type="blocked_app", subject="game.exe", policy_id="1")
    q.apply_generations({"a": 1})
    assert q.history("a")[0]["generation"] == 1
    with pytest.raises(ValueError):
        q.apply_generations({"a": 0})


def test_offline_queue_expires_history_and_pending(tmp_path):
    clock = [time.time()]
    q = EventQueue(tmp_path / "events.db", clock=lambda: clock[0])
    q.append(device_id="d", child_id="c", type="blocked_app", subject="game.exe", policy_id="1")
    clock[0] += RETENTION_SECONDS + 1
    assert q.pending() == q.history("c") == q.notifications("c") == []


def test_domain_rules_subdomains_safety_and_privacy():
    rules = {
        "enabled": True,
        "domain_mode": "allowlist",
        "domain_allow": ["example.org"],
        "domain_block": ["111.vn"],
        "safety_domains": ["school.edu.vn"],
    }
    assert domain_decision("news.example.org", rules) is None
    assert domain_decision("notexample.org", rules)
    assert domain_decision("111.vn", rules) is None
    assert domain_decision("portal.school.edu.vn", rules) is None
    assert event_domain("portal.school.edu.vn") == "school.edu.vn"


def test_app_hash_recognizes_rename_and_rejects_impersonation():
    sha = "a" * 64
    rules = {
        "enabled": True,
        "app_mode": "allowlist",
        "app_allow": [{"name": "learn.exe", "sha256": sha}],
        "app_block": [],
    }
    assert app_decision("renamed.exe", sha, rules) is None
    assert app_decision("learn.exe", "b" * 64, rules)
    rules["app_block"] = [{"name": "learn.exe", "sha256": sha}]
    assert app_decision("game.exe", sha, rules)


def test_dns_block_records_one_popup_for_a_aaaa_queries():
    core = Mock()
    core.filter_context.return_value = (
        "child",
        {
            "enabled": True,
            "version": 1,
            "domain_mode": "allowlist",
            "domain_allow": [],
            "safety_domains": [],
        },
        123,
    )
    proxy = DNSProxy(core)
    for qtype in ["A", "AAAA", "A"]:
        reply = proxy.resolve(
            DNSRecord.question("www.example.org", qtype), SimpleNamespace(protocol="udp")
        )
        assert reply.header.rcode == RCODE.NXDOMAIN
    assert core.record_activity.call_count == 1
    assert core.record_activity.call_args.args[2] == "example.org"


def test_dns_proxy_udp_and_tcp_real_requests_without_upstream():
    core = Mock()
    core.filter_context.return_value = (
        "child",
        {
            "enabled": True,
            "version": 1,
            "domain_mode": "allowlist",
            "domain_allow": [],
            "safety_domains": [],
        },
        123,
    )
    proxy = DNSProxy(core, port=0)
    proxy.start()
    try:
        for index, server in enumerate(proxy.servers):
            port = server.server.server_address[1]
            reply = DNSRecord.parse(
                DNSRecord.question("example.org").send(
                    "127.0.0.1", port, tcp=bool(index), timeout=2
                )
            )
            assert reply.header.rcode == RCODE.NXDOMAIN
    finally:
        proxy.stop()


def test_filtering_validation_versions_and_signed_document(parent, child):
    tokens, _ = pair(parent, child)
    path = f"/api/children/{child['id']}/filtering"
    assert parent.get(path).json()["version"] == 0
    assert (
        parent.put(
            path,
            json={"expected_version": 0, "enabled": True, "domain_block": ["https://bad.test/x"]},
        ).status_code
        == 422
    )
    assert (
        parent.put(
            path,
            json={
                "expected_version": 0,
                "enabled": True,
                "domain_mode": "allowlist",
                "domain_allow": ["example.org"],
            },
        ).status_code
        == 200
    )
    assert parent.put(path, json={"expected_version": 0}).status_code == 409
    doc = parent.get(
        "/api/device/filtering", headers={"Authorization": "Bearer " + tokens["access_token"]}
    ).json()
    from server.app.policy_signing import verify_policy

    integrity = doc.pop("integrity")
    assert verify_policy(doc, integrity["signature"], tokens["policy_signing_key"])
    assert doc["policies"][0]["version"] == 1
    assert "111.vn" in doc["policies"][0]["safety_domains"]


def test_end_to_end_offline_queue_sync_and_delete(parent, child, tmp_path):
    from agent.core import AgentCore

    tokens, _ = pair(parent, child)
    path = tmp_path / "remote-config.json"
    RemoteConfig(
        server_url="http://testserver",
        device_id=tokens["device_id"],
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        policy_signing_key=tokens["policy_signing_key"],
        fingerprint="test-installation",
        child_id=child["id"],
    ).save(path)
    sync = RemoteSync(AgentCore(), path, tmp_path / "policy.json")
    id = sync.events.append(
        device_id=tokens["device_id"],
        child_id=child["id"],
        type="blocked_domain",
        subject="example.org",
        policy_id="1",
        reason="Not allowed",
    )
    # Simulated dropped response after the server committed, then retry.
    result = post(parent, tokens, sync.events.pending())
    assert result.status_code == 200
    sync.sync_activity(parent)
    assert sync.events.pending() == []
    assert len(parent.get(f"/api/children/{child['id']}/activity-events").json()["items"]) == 1
    assert sync.events.history(child["id"])[0]["id"] == id
    parent.delete(f"/api/children/{child['id']}/activity-data")
    sync.sync_activity(parent)
    assert sync.events.history(child["id"]) == []
    assert parent.get(f"/api/children/{child['id']}/activity-data/deletion").json()["complete"]


def test_sync_failure_keeps_pending_queue(parent, child, tmp_path):
    from agent.core import AgentCore

    tokens, _ = pair(parent, child)
    path = tmp_path / "remote-config.json"
    RemoteConfig(
        server_url="http://testserver",
        device_id=tokens["device_id"],
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        policy_signing_key=tokens["policy_signing_key"],
        fingerprint="test-installation",
        child_id=child["id"],
    ).save(path)
    sync = RemoteSync(AgentCore(), path, tmp_path / "policy.json")
    sync.events.append(
        device_id=tokens["device_id"],
        child_id=child["id"],
        type="blocked_app",
        subject="game.exe",
        policy_id="1",
        reason="Blocked",
    )
    client = Mock()
    client.request.side_effect = httpx.ConnectError("Offline")
    with pytest.raises(httpx.ConnectError):
        sync.sync_activity(client)
    assert len(sync.events.pending()) == 1


def test_core_dns_event_scope_notification_ack_and_ipc_size(tmp_path):
    from agent.core import AgentCore
    from agent.ipc_protocol import encode_message, new_request, success_response

    core = AgentCore()
    q = EventQueue(tmp_path / "events.db")
    core.configure_events(q, "d")
    core._active_child_id = "c"
    rules = {
        "enabled": True,
        "child_id": "c",
        "version": 1,
        "domain_mode": "allowlist",
        "domain_allow": [],
    }
    core.configure_filtering([rules])
    core.handle(
        new_request(
            "ui_heartbeat",
            {"visible": True, "idle_seconds": 0, "session_locked": False, "process_id": 123},
        )
    )
    proxy = DNSProxy(core)
    assert (
        proxy.resolve(
            DNSRecord.question("blocked.example.test"), SimpleNamespace(protocol="udp")
        ).header.rcode
        == RCODE.NXDOMAIN
    )
    first = core.status()["blocking_notifications"][0]
    assert first["event"]["subject"] == "example.test"
    assert first["explanation"]["reason"] == "Trang web không nằm trong danh sách cho phép."
    core.handle(new_request("ack_blocking_events", {"event_ids": [first["id"]]}))
    assert core.status()["blocking_notifications"] == []
    for _ in range(40):
        q.append(
            device_id="d",
            child_id="c",
            type="blocked_app",
            subject="😀" * 200,
            policy_id="1",
            reason="😀" * 300,
        )
    encode_message(success_response("r", core.status()))
    core._active_child_id = "sibling"
    assert core.status()["activity_events"] == core.status()["blocking_notifications"] == []


def test_popup_shows_reason_once_and_acknowledges_on_dismiss(monkeypatch):
    from agent import tray_ui

    ui = tray_ui.TrayApplication.__new__(tray_ui.TrayApplication)
    ui.events_tree = Mock()
    ui.events_tree.get_children.return_value = []
    ui.root = Mock()
    ui.block_popup = None
    ui.block_popup_ids = set()
    ui._send_async = Mock()
    popup = Mock()
    monkeypatch.setattr(tray_ui.tk, "Toplevel", Mock(return_value=popup))
    text = Mock()
    button = Mock()
    monkeypatch.setattr(tray_ui.tk, "Text", Mock(return_value=text))
    for widget in ["Frame", "Label"]:
        monkeypatch.setattr(tray_ui.ttk, widget, Mock())
    monkeypatch.setattr(tray_ui.ttk, "Button", button)
    item = {
        "id": "event-1",
        "event": {"ts": time.time(), "subject": "example.org"},
        "explanation": {
            "reason": "Trang web không nằm trong danh sách cho phép.",
            "rule_author": "Phụ huynh",
        },
    }
    data = {"activity_events": [item], "blocking_notifications": [item]}
    ui._update_activity_events(data)
    ui._update_activity_events(data)
    assert tray_ui.tk.Toplevel.call_count == 1
    assert "Trang web không nằm trong danh sách cho phép." in text.insert.call_args.args[1]
    assert ui._send_async.call_count == 0
    button.call_args.kwargs["command"]()
    ui._send_async.assert_called_once_with(
        "ack_blocking", "ack_blocking_events", {"event_ids": ["event-1"]}
    )
    assert ui.block_popup is None


def test_popup_closes_after_profile_switch_or_erasure(monkeypatch):
    from agent.tray_ui import TrayApplication

    ui = TrayApplication.__new__(TrayApplication)
    ui.events_tree = Mock()
    ui.events_tree.get_children.return_value = []
    popup = Mock()
    ui.block_popup = popup
    ui.block_popup_ids = {"old-child-event"}
    ui._update_activity_events({"activity_events": [], "blocking_notifications": []})
    popup.destroy.assert_called_once()
    assert ui.block_popup is None


def test_app_controller_never_kills_other_windows_sessions(tmp_path, monkeypatch):
    import psutil
    import win32process
    import win32ts

    from agent.filtering import AppController

    filename = tmp_path / "renamed-game.exe"
    filename.write_bytes(b"harmless fake executable, never launched")
    core = Mock()
    controller = AppController(core)
    sha = controller.file_hash(filename)
    rules = {
        "enabled": True,
        "version": 1,
        "app_mode": "blocklist",
        "app_block": [{"name": "game.exe", "sha256": sha}],
    }
    core.filter_context.return_value = ("c", rules, 10)
    monkeypatch.setattr(win32process, "EnumProcesses", lambda: [20, 30])
    monkeypatch.setattr(win32ts, "ProcessIdToSessionId", lambda pid: 1 if pid in [10, 20] else 2)
    processes = {pid: Mock() for pid in [20, 30]}
    for process in processes.values():
        process.name.return_value = filename.name
        process.exe.return_value = str(filename)
        process.create_time.return_value = 1.0
    monkeypatch.setattr(psutil, "Process", lambda pid: processes[pid])
    controller.scan()
    processes[20].kill.assert_called_once()
    processes[30].kill.assert_not_called()
    assert core.record_activity.call_args.args[1:3] == ("blocked_app", filename.name)
