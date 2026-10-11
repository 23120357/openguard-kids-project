import csv
import io
import time
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from dnslib import DNSRecord
from PIL import Image

from agent.core import AgentCore
from agent.event_queue import EventQueue
from agent.filtering import DNSProxy
from agent.ipc_protocol import new_request
from agent.time_control import MemoryTimeStore, SQLiteTimeStore
from common.activity_reports import REPORT_ZONE, SESSION_SUBJECT, activity_report
from common.report_charts import rolling_week_columns
from server.app.event_routes import expire_events
from server.app.models import TimeRequest

from .conftest import pair, sign_in
from .test_activity_events import event, post
from .test_time_control import controller, policy


def payload(ts, kind="app_stop", subject=SESSION_SUBJECT, seconds=0):
    return {"ts": ts, "type": kind, "subject": subject, "duration_sec": seconds}


def test_report_splits_midnight_and_week_without_double_counting_apps():
    midnight = datetime(2026, 10, 5, tzinfo=REPORT_ZONE).timestamp()
    result = activity_report(
        [
            payload(midnight + 30, seconds=60),
            payload(midnight + 30, subject="school.exe", seconds=60),
            payload(midnight + 30, subject="browser.exe", seconds=60),
            payload(midnight, "domain_query", "example.org"),
            payload(midnight + 2, "blocked_domain", "example.org"),
        ],
        end_date="2026-10-05",
        days=2,
    )
    assert [row["duration_sec"] for row in result["daily"]] == [30, 30]
    assert [row["duration_sec"] for row in result["weekly"]] == [30, 30]
    assert result["total_duration_sec"] == 60
    assert sum(row["duration_sec"] for row in result["top_apps"]) == 120
    assert result["top_domains"] == [{"subject": "example.org", "queries": 1}]
    assert result["blocked_count"] == 1


def test_report_zero_days_and_top_ten_are_stable():
    ts = datetime(2026, 10, 5, 12, tzinfo=REPORT_ZONE).timestamp()
    events = [payload(ts, subject=f"app-{i:02}.exe", seconds=i) for i in range(15)]
    events += [payload(ts, "domain_query", f"domain-{i:02}.test") for i in range(15)]
    result = activity_report(events, end_date="2026-10-05", days=7)
    assert len(result["daily"]) == 7
    assert result["total_duration_sec"] == 0
    assert len(result["top_apps"]) == len(result["top_domains"]) == 10
    assert result["top_apps"][0]["subject"] == "app-14.exe"
    assert result["top_domains"][0]["subject"] == "domain-00.test"


def test_rolling_week_chart_has_eight_consecutive_seven_day_columns():
    start = datetime(2026, 8, 17, tzinfo=REPORT_ZONE)
    daily = [
        {
            "date": (start + timedelta(days=index)).date().isoformat(),
            "duration_sec": 3600 if index < 7 else 7200 if index >= 49 else 0,
        }
        for index in range(56)
    ]
    columns = rolling_week_columns(daily)
    assert len(columns) == 8
    assert [row["duration_sec"] for row in columns] == [7 * 3600, 0, 0, 0, 0, 0, 0, 14 * 3600]
    assert columns[0]["week_start"] == daily[0]["date"]
    assert columns[-1]["week_end"] == daily[-1]["date"]


def test_parent_chart_endpoints_keep_fixed_windows(parent, child, monkeypatch):
    from server.app import event_routes

    captured = {}

    def capture(items, kind):
        captured[kind] = items
        return b"chart"

    monkeypatch.setattr(event_routes, "render_report_chart", capture)
    base = f"/api/children/{child['id']}/activity-report/chart.png"
    assert parent.get(base + "?kind=daily&days=90").status_code == 200
    assert parent.get(base + "?kind=weekly&days=7").status_code == 200
    assert len(captured["daily"]) == 7
    assert len(captured["weekly"]) == 8


def test_parent_and_local_child_reports_agree_and_retries_do_not_inflate(parent, child, tmp_path):
    tokens, _ = pair(parent, child)
    now = time.time()
    day = datetime.fromtimestamp(now, REPORT_ZONE).date().isoformat()
    queue = EventQueue(tmp_path / "events.db", clock=lambda: now)
    for kind, subject, seconds in [
        ("app_stop", SESSION_SUBJECT, 10),
        ("app_start", "paint.exe", 0),
        ("app_stop", "paint.exe", 6),
        ("domain_query", "example.org", 0),
        ("blocked_domain", "example.org", 0),
    ]:
        queue.append(
            device_id=tokens["device_id"],
            child_id=child["id"],
            type=kind,
            subject=subject,
            duration_sec=seconds,
            policy_id="demo:1",
            reason="Chặn theo luật." if kind.startswith("blocked") else "",
        )
    for _ in range(2):
        assert post(parent, tokens, queue.pending()).status_code == 200
    remote = parent.get(f"/api/children/{child['id']}/activity-report?days=1&end_date={day}").json()
    local = queue.report(child["id"], days=1, end_date=day)
    assert remote.pop("requests") == []
    assert remote == local
    assert remote["total_duration_sec"] == 10
    assert remote["blocked_count"] == 1
    assert queue.report("another-child")["total_duration_sec"] == 0


def test_report_and_export_require_ownership_and_valid_dates(parent, child):
    base = f"/api/children/{child['id']}"
    assert parent.get(base + "/activity-report?days=91").status_code == 422
    assert parent.get(base + "/activity-report?end_date=not-a-date").status_code == 422
    assert parent.get(base + "/activity-report.csv?week_start=not-a-date").status_code == 422
    assert parent.get(base + "/activity-report/chart.png?kind=invalid").status_code == 422
    for kind in ("daily", "weekly", "apps"):
        response = parent.get(base + "/activity-report/chart.png?kind=" + kind + "&days=7")
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"
        assert response.headers["cache-control"] == "no-store"
        assert Image.open(io.BytesIO(response.content)).size[0] == (440 if kind == "apps" else 800)
    sign_in(parent, "other@example.test")
    assert parent.get(base + "/activity-report").status_code == 404
    assert parent.get(base + "/activity-report/chart.png?kind=daily").status_code == 404
    assert parent.get(base + "/activity-report.csv").status_code == 404
    parent.cookies.clear()
    assert parent.get(base + "/activity-report").status_code == 401


def test_weekly_csv_is_utf8_safe_and_includes_requests(parent, child):
    tokens, _ = pair(parent, child)
    assert (
        post(
            parent,
            tokens,
            [event(tokens, child, type="app_stop", subject="=2+3.exe", duration_sec=4)],
        ).status_code
        == 200
    )
    response = parent.post(
        "/api/device/requests",
        headers={"Authorization": "Bearer " + tokens["access_token"]},
        json={
            "request_id": "report-request",
            "child_id": child["id"],
            "requester": child["display_name"],
            "minutes": 15,
            "created_at": time.time(),
        },
    )
    assert response.status_code == 201
    result = parent.get(f"/api/children/{child['id']}/activity-report.csv")
    assert result.status_code == 200
    assert result.content.startswith(b"\xef\xbb\xbf")
    rows = list(csv.reader(io.StringIO(result.content.decode("utf-8-sig"))))
    assert ["Ứng dụng", "'=2+3.exe", "4", "giây chạy"] in rows
    assert any(row[0] == "Xin thêm giờ" and row[2] == "15" for row in rows)
    assert len([row for row in rows if row[0] == "Thời gian dùng máy"]) == 7
    assert result.headers["cache-control"] == "no-store"
    assert "attachment" in result.headers["content-disposition"]


def test_erasure_and_retention_include_request_activity(parent, child, app):
    tokens, _ = pair(parent, child)
    request = parent.post(
        "/api/device/requests",
        headers={"Authorization": "Bearer " + tokens["access_token"]},
        json={
            "request_id": "old-request",
            "child_id": child["id"],
            "requester": child["display_name"],
            "minutes": 15,
            "created_at": time.time(),
        },
    ).json()
    with app.state.sessions() as db:
        db.get(TimeRequest, request["id"]).created_at = time.time() - 91 * 86400
        db.commit()
    expire_events(app.state.sessions)
    assert parent.get("/api/time-requests").json() == []
    assert post(parent, tokens, [event(tokens, child)]).status_code == 200
    assert parent.delete(f"/api/children/{child['id']}/activity-data").status_code == 200
    report = parent.get(f"/api/children/{child['id']}/activity-report").json()
    assert report["blocked_count"] == 0
    assert report["top_domains"] == report["requests"] == []


def reporting_core(tmp_path, *, enabled=False):
    timer, clock, store = controller(policy(enabled=enabled))
    core = AgentCore(clock=clock.mono, wall_clock=clock.current_wall, time_controller=timer)
    core._active_child_id = "child"
    core._active_user = "An"
    core._profiles = {"child": {"id": "child", "display_name": "An"}}
    core._controllers = {"child": timer}
    queue = EventQueue(tmp_path / "queue.db", clock=clock.current_wall)
    core.configure_events(queue, "device")
    return core, clock, store, queue


def heartbeat(core, **kwargs):
    return core.handle(
        new_request(
            "ui_heartbeat",
            {
                "visible": True,
                "idle_seconds": 0,
                "session_locked": False,
                "process_id": 10,
                **kwargs,
            },
        )
    )


def test_usage_reporting_works_with_rules_disabled_and_ignores_absence_idle_lock(tmp_path):
    core, clock, _, queue = reporting_core(tmp_path)
    heartbeat(core)
    clock.advance(2)
    heartbeat(core)
    assert core.activity_context() is not None
    assert core.filter_context() is None
    for kwargs in [{"idle_seconds": 400}, {"session_locked": True}, {"visible": False}]:
        clock.advance(2)
        heartbeat(core, **kwargs)
    clock.advance(60)
    heartbeat(core)
    assert queue.report("child")["total_duration_sec"] == 2
    assert core.status()["activity_report"]["total_duration_sec"] == 2


def test_tray_top_apps_periods_use_one_seven_and_ninety_days(tmp_path):
    core, clock, _, queue = reporting_core(tmp_path)
    for age, subject in ((0, "today.exe"), (2, "week.exe"), (20, "older.exe")):
        queue.append(
            device_id="device",
            child_id="child",
            type="app_stop",
            subject=subject,
            policy_id="demo:1",
            duration_sec=60,
            timestamp=clock.wall - age * 86400,
        )
    periods = core.activity_report()["app_periods"]
    assert [item["subject"] for item in periods["1"]] == ["today.exe"]
    assert {item["subject"] for item in periods["7"]} == {"today.exe", "week.exe"}
    assert {item["subject"] for item in periods["90"]} == {
        "today.exe", "week.exe", "older.exe"
    }
    queue.append(
        device_id="device", child_id="sibling", type="app_stop",
        subject="private.exe", policy_id="demo:1", duration_sec=3600,
        timestamp=clock.wall,
    )
    assert all("private.exe" not in {item["subject"] for item in rows} for rows in core.activity_report()["app_periods"].values())
    core._active_child_id = "sibling"
    assert [item["subject"] for item in core.activity_report()["app_periods"]["90"]] == ["private.exe"]
    core._active_child_id = "child"
    core.clear_activity(queue.apply_generations({"child": 1}))
    assert core.activity_report()["app_periods"] == {"1": [], "7": [], "90": []}


def test_time_events_requests_and_overrides_enter_durable_queue_once(tmp_path):
    core, clock, store, queue = reporting_core(tmp_path, enabled=True)
    core._time_controller._emit_event(
        "quota_warning", clock.wall, "Em còn 5 phút.", {"policy_version": 1}
    )
    core._time_controller._emit_event(
        "locked", clock.wall, "Đã khóa theo lịch.", {"policy_version": 1}
    )
    core.apply_remote_command(
        {"id": "grant-1", "type": "add_time", "child_id": "child", "payload": {"minutes": 15}}
    )
    core.apply_remote_command(
        {"id": "grant-1", "type": "add_time", "child_id": "child", "payload": {"minutes": 15}}
    )
    assert core.handle(new_request("request_more_time", {"minutes": 15}))["ok"]
    types = [
        item["event"]["type"] for item in EventQueue(queue.path, clock=clock.current_wall).pending()
    ]
    assert types.count("override_granted") == 1
    assert {"quota_warning", "locked", "unlock_request", "override_granted"} <= set(types)
    changed = queue.apply_generations({"child": 1})
    core.clear_activity(changed)
    assert store.events == []
    assert core.pending_time_requests() == []
    assert core.status()["activity_report"]["blocked_count"] == 0
    assert queue.pending() == []


@pytest.mark.parametrize("store_class", [MemoryTimeStore, SQLiteTimeStore])
def test_local_time_event_history_can_expire_and_erase_without_resetting_quota(
    tmp_path, store_class
):
    store = (
        MemoryTimeStore() if store_class is MemoryTimeStore else SQLiteTimeStore(tmp_path / "f1.db")
    )
    store.add_event("locked", 1, "Old", {})
    store.add_event("locked", 100 * 86400, "New", {})
    store.expire_events(100 * 86400)
    assert len(store.recent_events()) == 1
    state = store.load_state()
    store.erase_events()
    assert store.recent_events() == []
    assert store.load_state() == state


def test_allowed_dns_queries_are_recorded_without_full_url_when_filtering_off(monkeypatch):
    core = Mock()
    core.activity_context.return_value = ("child", {"enabled": False, "version": 0}, 10)
    monkeypatch.setattr(DNSRecord, "send", lambda request, *args, **kwargs: request.reply().pack())
    proxy = DNSProxy(core)
    for qtype in ["A", "AAAA"]:
        proxy.resolve(
            DNSRecord.question("portal.school.edu.vn", qtype), SimpleNamespace(protocol="udp")
        )
    core.record_activity.assert_called_once_with(
        "child", "domain_query", "school.edu.vn", "", {"enabled": False, "version": 0}
    )


def test_dns_query_reaches_parent_report_and_synced_tray(parent, child, tmp_path, monkeypatch):
    from agent.remote_sync import RemoteConfig, RemoteSync

    tokens, _ = pair(parent, child)
    config_path = tmp_path / "remote-config.json"
    RemoteConfig(
        server_url="http://testserver",
        device_id=tokens["device_id"],
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        policy_signing_key=tokens["policy_signing_key"],
        fingerprint="test-installation",
        child_id=child["id"],
    ).save(config_path)
    sync = RemoteSync(AgentCore(), config_path, tmp_path / "policy.json")
    sync.core._active_child_id = child["id"]
    monkeypatch.setattr(
        sync.core, "activity_context",
        lambda: (child["id"], {"enabled": False, "version": 0}, 1),
    )
    monkeypatch.setattr(DNSRecord, "send", lambda request, *args, **kwargs: request.reply().pack())
    DNSProxy(sync.core).resolve(
        DNSRecord.question("portal.example.org", "A"), SimpleNamespace(protocol="udp")
    )
    assert sync.core.activity_report()["top_domains"] == [
        {"subject": "example.org", "queries": 1}
    ]
    sync.sync_activity(parent)
    web = parent.get(f"/api/children/{child['id']}/activity-report?days=1").json()
    tray = sync.core.activity_report()
    assert web["top_domains"] == tray["top_domains"] == [
        {"subject": "example.org", "queries": 1}
    ]
    assert tray["source"] == "synced"


def test_device_child_view_matches_parent_across_multiple_devices(parent, child):
    first, _ = pair(parent, child)
    second, _ = pair(parent, child)
    for tokens in (first, second):
        assert (
            post(
                parent,
                tokens,
                [event(tokens, child, type="app_stop", subject=SESSION_SUBJECT, duration_sec=5)],
            ).status_code
            == 200
        )
    expected = parent.get(f"/api/children/{child['id']}/activity-report?days=1").json()
    response = parent.get(
        "/api/device/activity-report",
        params={"child_id": child["id"]},
        headers={"Authorization": "Bearer " + first["access_token"]},
    )
    assert response.json()["report"] == expected
    assert expected["total_duration_sec"] == 10
    for days in (7, 90):
        response = parent.get(
            "/api/device/activity-report", params={"child_id": child["id"], "days": days},
            headers={"Authorization": "Bearer " + first["access_token"]},
        )
        assert response.json()["report"] == parent.get(
            f"/api/children/{child['id']}/activity-report?days={days}"
        ).json()
    sign_in(parent, "other@example.test")
    other = parent.post("/api/children", json={"display_name": "Other", "pin": "123456"}).json()
    assert (
        parent.get(
            "/api/device/activity-report",
            params={"child_id": other["id"]},
            headers={"Authorization": "Bearer " + first["access_token"]},
        ).status_code
        == 403
    )


def test_sync_without_erasure_preserves_usage_baseline_and_offline_view(tmp_path):
    core, clock, _, queue = reporting_core(tmp_path)
    heartbeat(core)
    clock.advance(2)
    core.clear_activity([])
    heartbeat(core)
    assert queue.report("child")["total_duration_sec"] == 2
    report = queue.report("child")
    report["total_duration_sec"] = 20
    report["requests"] = []
    report["app_periods"] = {
        "7": [{"subject": "week-from-server.exe", "duration_sec": 120, "starts": 1}],
        "90": [{"subject": "history-from-server.exe", "duration_sec": 360, "starts": 1}],
    }
    core.set_activity_report({"child_id": "child", "generation": 0, "report": report})
    assert core.activity_report()["source"] == "synced"
    assert core.activity_report()["total_duration_sec"] == 20
    assert core.activity_report()["app_periods"]["7"][0]["subject"] == "week-from-server.exe"
    assert core.activity_report()["app_periods"]["90"][0]["subject"] == "history-from-server.exe"
    clock.advance(16)
    assert core.activity_report()["source"] == "local"
    assert core.activity_report()["total_duration_sec"] == 2


def test_running_application_reports_duration_before_exit_with_filtering_disabled(
    tmp_path, monkeypatch
):
    import psutil
    import win32process
    import win32ts

    from agent import filtering

    now = [0.0]
    base = time.time()
    queue = EventQueue(tmp_path / "apps.db", clock=lambda: base + now[0])
    core = Mock()
    rules = {"enabled": False, "version": 0}
    core.activity_context.return_value = ("child", rules, 10)
    core.record_activity.side_effect = lambda child_id, kind, name, reason, rules, duration_sec=0: (
        queue.append(
            device_id="device",
            child_id=child_id,
            type=kind,
            subject=name,
            reason=reason,
            policy_id="filter:0",
            duration_sec=duration_sec,
        )
    )
    process = Mock()
    process.name.return_value = "school.exe"
    process.exe.return_value = "C:/Lab/school.exe"
    process.create_time.return_value = 100.0
    monkeypatch.setattr(psutil, "Process", lambda pid: process)
    monkeypatch.setattr(win32process, "EnumProcesses", lambda: [20])
    monkeypatch.setattr(win32ts, "ProcessIdToSessionId", lambda pid: 1)
    monkeypatch.setattr(filtering.time, "monotonic", lambda: now[0])
    scanner = filtering.AppController(core)
    scanner.scan()
    now[0] = 2
    scanner.scan()
    assert queue.report("child")["top_apps"] == [
        {"subject": "school.exe", "duration_sec": 2, "starts": 1}
    ]
    now[0] = 3
    monkeypatch.setattr(win32process, "EnumProcesses", list)
    scanner.scan()
    assert queue.report("child")["top_apps"][0]["duration_sec"] == 3
    process.kill.assert_not_called()
