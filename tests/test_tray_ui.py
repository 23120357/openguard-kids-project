import os
import queue
import time
import tkinter as tk
import uuid
from datetime import UTC, datetime
from tkinter import ttk
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent.named_pipe import PipeUnavailableError
from agent.tray_ui import (
    TrayApplication,
    TrayInstanceGuard,
    disabled_time_detail,
    format_clock,
    format_local_datetime,
    format_policy_schedule,
    format_used_duration,
    has_remaining_time,
    session_error_message,
)


def test_events_mousewheel_scrolls_tree_only_in_events_tab():
    tab = "events-tab"
    notebook = Mock()
    notebook.select.return_value = tab
    tree = Mock()
    ui = TrayApplication.__new__(TrayApplication)
    ui.events_tab = tab
    ui.events_tree = tree
    ui.notebook = notebook
    assert ui._scroll_events(SimpleNamespace(delta=-120)) == "break"
    tree.yview_scroll.assert_called_once_with(1, "units")
    tree.reset_mock()
    assert ui._scroll_events(SimpleNamespace(delta=240)) == "break"
    tree.yview_scroll.assert_called_once_with(-2, "units")
    tree.reset_mock()
    notebook.select.return_value = "today-tab"
    assert ui._scroll_events(SimpleNamespace(delta=-120)) is None
    tree.yview_scroll.assert_not_called()


def test_eye_reminder_appears_once_per_twenty_minutes_of_local_use():
    app = TrayApplication.__new__(TrayApplication)
    app.current_user = "An"
    app.active_child_id = "child"
    app._show_eye_reminder = Mock()
    for seconds in (1199, 1200, 1250, 2399, 2400, 2410, 3600):
        app._check_eye_reminder({"end_date": "2026-10-11", "local_duration_sec": seconds})
    assert app._show_eye_reminder.call_count == 2
    app._check_eye_reminder({"end_date": "2026-10-12", "local_duration_sec": 1200})
    assert app._show_eye_reminder.call_count == 2
    app._check_eye_reminder({"end_date": "2026-10-12", "local_duration_sec": 2400})
    assert app._show_eye_reminder.call_count == 3


def test_eye_reminder_waits_twenty_minutes_after_profile_switch_or_restart():
    app = TrayApplication.__new__(TrayApplication)
    app.current_user = "An"
    app.active_child_id = "child-a"
    app._show_eye_reminder = Mock()
    app._check_eye_reminder({"end_date": "2026-10-11", "local_duration_sec": 7200})
    app._check_eye_reminder({"end_date": "2026-10-11", "local_duration_sec": 8399})
    assert app._show_eye_reminder.call_count == 0
    app._check_eye_reminder({"end_date": "2026-10-11", "local_duration_sec": 8400})
    assert app._show_eye_reminder.call_count == 1
    app.active_child_id = "child-b"
    app._check_eye_reminder({"end_date": "2026-10-11", "local_duration_sec": 1200})
    assert app._show_eye_reminder.call_count == 1


def test_eye_reminder_uses_the_same_windows_notification_as_time_warnings():
    app = TrayApplication.__new__(TrayApplication)
    app.icon = Mock()
    app._show_eye_reminder()
    app.icon.notify.assert_called_once_with(
        "Hãy nghỉ mắt! Nhìn ra xa khoảng 6 mét trong 20 giây.",
        "OpenGuard Kids",
    )


def test_domain_query_chart_updates_at_most_once_per_minute():
    app = TrayApplication.__new__(TrayApplication)
    app.active_child_id = "child"
    app.activity_summary = Mock()
    app._check_eye_reminder = Mock()
    app._draw_activity_report = Mock()
    app._draw_top_apps = Mock()
    report = {
        "end_date": "2026-10-11", "total_duration_sec": 0, "source": "local",
        "top_domains": [{"subject": "example.org", "queries": 1}],
        "top_apps": [], "app_periods": {},
    }
    app._update_activity_report(report)
    assert app._draw_activity_report.call_count == 1
    updated = {**report, "top_domains": [{"subject": "example.org", "queries": 2}]}
    app._update_activity_report(updated)
    assert app._draw_activity_report.call_count == 1
    app._visual_report_checked_at -= 61
    app._update_activity_report(updated)
    assert app._draw_activity_report.call_count == 2
    app._visual_report_checked_at -= 61
    app._update_activity_report(updated)
    assert app._draw_activity_report.call_count == 2
    app.active_child_id = "another-child"
    app._update_activity_report(updated)
    assert app._draw_activity_report.call_count == 3


def test_event_poll_preserves_rows_and_scrolled_position():
    ui = TrayApplication.__new__(TrayApplication)
    ui.events_tree = Mock()
    ui.events_tree.get_children.return_value = ("event-1",)
    ui.events_tree.selection.return_value = ("event-1",)
    ui.events_tree.yview.return_value = (0.5, 0.8)
    event = {
        "id": "event-1",
        "event": {"ts": 0, "subject": "example.org"},
        "explanation": {"reason": "blocked", "rule_author": "parent"},
    }

    values = (
        datetime.fromtimestamp(0, UTC).astimezone().strftime("%d/%m/%Y %H:%M:%S"),
        "example.org",
        "blocked · parent",
    )
    ui.events_tree.item.return_value = values
    ui.block_popup = None
    ui.block_popup_ids = set()
    ui._update_activity_events({"activity_events": [event], "blocking_notifications": []})
    ui.events_tree.delete.assert_not_called()
    ui.events_tree.insert.assert_not_called()
    ui.events_tree.move.assert_not_called()
    ui.events_tree.yview_moveto.assert_called_once_with(0.5)
    ui.events_tree.selection_set.assert_not_called()


def test_mousewheel_over_event_details_scrolls_details_instead_of_list():
    ui = TrayApplication.__new__(TrayApplication)
    ui.events_tab = "events-tab"
    ui.notebook = Mock()
    ui.notebook.select.return_value = ui.events_tab
    ui.events_tree = Mock()
    ui.event_detail = Mock()
    ui.event_detail_scrollbar = Mock()
    for widget in (ui.event_detail, ui.event_detail_scrollbar):
        ui.event_detail.reset_mock()
        assert ui._scroll_events(SimpleNamespace(delta=-120, widget=widget)) == "break"
        ui.event_detail.yview_scroll.assert_called_once_with(1, "units")
    ui.events_tree.yview_scroll.assert_not_called()


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [(0, "00:00:00"), (5, "00:00:05"), (65, "00:01:05"), (3661, "01:01:01")],
)
def test_digital_clock_format(seconds, expected):
    assert format_clock(seconds) == expected


@pytest.mark.parametrize(
    ("seconds", "expected"),
    [
        (0, "00 phút 00 giây"),
        (5, "00 phút 05 giây"),
        (65, "01 phút 05 giây"),
        (3661, "61 phút 01 giây"),
    ],
)
def test_today_used_duration_format(seconds, expected):
    assert format_used_duration(seconds) == expected


def test_today_header_formats_local_date_and_time():
    assert format_local_datetime(datetime(2026, 10, 4, 16, 1, 8, tzinfo=UTC)) == (
        "Chủ nhật, 04/10/2026 · 16:01:08"
    )


def test_policy_schedule_formats_allowed_intervals():
    lines = format_policy_schedule(["1" * 2 + "0" * 46, "0" * 48])
    assert "Thứ 2: 00:00–01:00" in lines
    assert "Thứ 3: Không có giờ dùng máy" in lines


def test_policy_schedule_groups_simple_weekly_patterns():
    assert format_policy_schedule(["0" * 48] * 7) == "Cả tuần: Không có giờ dùng máy"
    assert format_policy_schedule(["1" * 48] * 7) == "Cả tuần: Cả ngày"
    assert format_policy_schedule(["1" * 2 + "0" * 46] * 5 + ["0" * 48] * 2) == (
        "Thứ 2 – Thứ 6: 00:00–01:00\nCuối tuần: Không có giờ dùng máy"
    )


@pytest.mark.parametrize("value, expected", [(None, False), (0, False), (1, True), (1.5, True)])
def test_missing_quota_does_not_break_tray_refresh(value, expected):
    assert has_remaining_time(value) is expected


def test_tray_poll_continues_after_a_status_render_error():
    responses = queue.Queue()
    responses.put(("status", {"ok": True, "data": {}}))
    render = Mock(side_effect=TypeError("bad status field"))
    root = Mock()
    ui = SimpleNamespace(
        closing=False,
        responses=responses,
        status_in_flight=True,
        status_requested_at=time.monotonic(),
        root=root,
        scheduler=root,
        REFRESH_MS=1000,
        refresh_status=Mock(),
        _apply_status=render,
        status_label=Mock(),
        _poll_responses=Mock(),
    )
    TrayApplication._poll_responses(ui)
    assert ui.status_in_flight is False
    assert root.after.call_count == 2
    assert any(
        1 <= call.args[0] <= 1000 and call.args[1] is ui.refresh_status
        for call in root.after.call_args_list
    )
    root.after.assert_any_call(100, ui._poll_responses)


def test_policy_lock_retries_but_remote_command_remains_one_shot(monkeypatch):
    ui = TrayApplication.__new__(TrayApplication)
    ui.completed_lock_attempts = set()
    ui._send_async = Mock()
    lock = Mock(return_value=True)
    now = [10.0]
    monkeypatch.setattr("agent.tray_ui.lock_workstation", lock)
    monkeypatch.setattr("agent.tray_ui.time.monotonic", lambda: now[0])
    ui._request_workstation_lock("quota_exhausted")
    ui._request_workstation_lock("quota_exhausted")
    assert lock.call_count == 1
    now[0] += 2
    ui._request_workstation_lock("quota_exhausted")
    assert lock.call_count == 1
    # The existing controller retries policy locks every ten seconds.
    now[0] += 8
    ui._request_workstation_lock("quota_exhausted")
    assert lock.call_count == 2
    ui._request_workstation_lock("remote_lock", "command-1")
    now[0] += 2
    ui._request_workstation_lock("remote_lock", "command-1")
    assert lock.call_count == 3


def test_switch_profile_keeps_current_session_until_pin_succeeds():
    ui = TrayApplication.__new__(TrayApplication)
    ui.session_in_flight = False
    ui.current_user = "An"
    ui.profile_login_required = True
    ui._update_session_ui = Mock()
    ui._send_async = Mock()
    ui.end_session()
    assert ui.switching_profile is True
    assert ui.current_user == "An"
    ui._send_async.assert_not_called()
    ui.username_entry = Mock()
    ui.username_entry.get.return_value = "Binh"
    ui.pin_entry = Mock()
    ui.pin_entry.get.return_value = "123456"
    ui.login_button = Mock()
    ui.session_result = Mock()
    ui.start_session()
    ui._send_async.assert_called_once_with(
        "session_start", "start_session", {"username": "Binh", "pin": "123456"}
    )


def test_successful_pin_switch_updates_tray_session():
    ui = TrayApplication.__new__(TrayApplication)
    ui.closing = False
    ui.switching_profile = True
    ui.session_in_flight = True
    ui.current_user = "An"
    ui.active_child_id = "child-a"
    ui.responses = queue.Queue()
    ui.responses.put(("session_start", {
        "ok": True, "data": {"current_user": "Binh", "active_child_id": "child-b"},
    }))
    ui.scheduler = Mock()
    ui._update_session_ui = Mock()
    ui.refresh_status = Mock()
    ui._poll_responses()
    assert ui.switching_profile is False
    assert ui.current_user == "Binh"
    assert ui.active_child_id == "child-b"
    ui._update_session_ui.assert_called_once()
    ui.refresh_status.assert_called_once()


@pytest.mark.parametrize("failure, expected", [
    ({"error": {"code": "login_failed", "message": "Unknown child username"}}, "Không tìm thấy tên hồ sơ"),
    ({"error": {"code": "login_failed", "message": "Incorrect child PIN"}}, "PIN không đúng"),
    ({"error": {"code": "invalid_pin", "message": "pin must contain exactly six digits"}}, "6 chữ số"),
    (PipeUnavailableError("pipe missing"), "Không kết nối được"),
])
def test_profile_switch_explains_actual_failure(failure, expected):
    assert expected in session_error_message(failure)


def test_unknown_profile_keeps_current_session_and_shows_specific_error():
    ui = TrayApplication.__new__(TrayApplication)
    ui.closing = False
    ui.switching_profile = True
    ui.session_in_flight = True
    ui.current_user = "An"
    ui.responses = queue.Queue()
    ui.responses.put(("session_start", {
        "ok": False, "error": {"code": "login_failed", "message": "Unknown child username"},
    }))
    ui.scheduler = Mock()
    ui.session_result = Mock()
    ui.login_button = Mock()
    ui.logout_button = Mock()
    ui._poll_responses()
    assert ui.current_user == "An"
    assert ui.switching_profile is True
    assert "Không tìm thấy tên hồ sơ" in ui.session_result.configure.call_args.kwargs["text"]


@pytest.mark.skipif(os.name != "nt", reason="Tk layout verification requires Windows")
def test_tray_initializes_switch_state_before_first_status(monkeypatch):
    monkeypatch.setattr("agent.tray_ui.pystray.Icon", Mock(return_value=Mock()))
    app = TrayApplication(instance_guard=Mock(), start_open=True)
    try:
        assert app.switching_profile is False
        app.icon = Mock()
        app._apply_status({"ok": True, "data": {
            "current_user": None, "active_child_id": None,
            "profiles": [{"id": "child-a", "display_name": "An"}],
            "capabilities": {"child_profile_login": True, "remote_parent_requests": False},
            "enrollment": {"required": False}, "remote": {"connected": True},
            "time_control": {"mode": "awaiting_profile", "remaining_seconds": None},
            "activity_events": [], "activity_report": None, "time_requests": [],
            "child_audit": [], "current_policy": None, "filtering": {"enabled": False},
        }})
        assert app.profile_options == {"An": "child-a"}
        assert "Đang đồng bộ" not in app.session_label.cget("text")
    finally:
        app.root.destroy()


def test_disabled_time_policy_still_shows_recorded_usage():
    assert "160 phút" in disabled_time_detail({"used_seconds": 9600, "policy_error": None})


def test_mouse_wheel_scrolls_today_tab():
    ui = TrayApplication.__new__(TrayApplication)
    ui.notebook = Mock()
    ui.today_tab = "today"
    ui.today_canvas = Mock()
    ui.notebook.select.return_value = "today"
    assert ui._scroll_today(SimpleNamespace(delta=-120)) == "break"
    ui.today_canvas.yview_scroll.assert_called_once_with(1, "units")
    ui.notebook.select.return_value = "login"
    assert ui._scroll_today(SimpleNamespace(delta=-120)) is None


def test_mouse_wheel_scrolls_privacy_tab():
    ui = TrayApplication.__new__(TrayApplication)
    ui.notebook = Mock()
    ui.privacy_tab = "privacy"
    ui.privacy_canvas = Mock()
    ui.notebook.select.return_value = "privacy"
    assert ui._scroll_privacy(SimpleNamespace(delta=-120)) == "break"
    ui.privacy_canvas.yview_scroll.assert_called_once_with(1, "units")
    ui.notebook.select.return_value = "today"
    assert ui._scroll_privacy(SimpleNamespace(delta=-120)) is None


@pytest.mark.parametrize(
    ("status", "expected"),
    [
        ("pending", "đang chờ phụ huynh"),
        ("approved", "Đã cộng thêm 18 phút"),
        ("rejected", "đã bị từ chối"),
    ],
)
def test_time_request_result_reflects_parent_decision(status, expected):
    ui = TrayApplication.__new__(TrayApplication)
    ui.current_user = "Avery"
    ui.request_result = Mock()
    ui._update_request_status([{"minutes": 18, "status": status}])
    assert expected in ui.request_result.configure.call_args.kwargs["text"]


def test_policy_tab_shows_active_child_policy_and_schedule():
    ui = TrayApplication.__new__(TrayApplication)
    ui.current_user = "Avery"
    ui.policy_title_label = Mock()
    ui.policy_status_label = Mock()
    ui.policy_weekday_value = Mock()
    ui.policy_weekend_value = Mock()
    ui.policy_summary_label = Mock()
    ui.policy_schedule_label = Mock()
    ui.audit_label = Mock()
    ui._update_policy_ui(
        {
            "version": 3,
            "enabled": True,
            "weekday_minutes": 45,
            "weekend_minutes": 90,
            "warnings_minutes": [10, 5, 1],
            "grace_seconds": 60,
            "idle_threshold_seconds": 300,
            "schedule": ["1" * 48] * 7,
        }
    )
    assert ui.policy_title_label.configure.call_args.kwargs["text"] == "Xin chào Avery!"
    assert ui.policy_status_label.configure.call_args.kwargs["text"] == "Đang áp dụng"
    assert ui.policy_weekday_value.configure.call_args.kwargs["text"] == "45 phút"
    assert ui.policy_weekend_value.configure.call_args.kwargs["text"] == "90 phút"
    assert "nhắc trước khi hết giờ" in ui.policy_summary_label.configure.call_args.kwargs["text"]
    assert ui.policy_schedule_label.configure.call_args.kwargs["text"] == "Cả tuần: Cả ngày"


@pytest.mark.skipif(os.name != "nt", reason="Tk layout verification requires Windows")
def test_event_details_remain_visible_and_scroll_at_small_window_sizes():
    app = TrayApplication.__new__(TrayApplication)
    app.root = tk.Tk()
    app.root.withdraw()
    try:
        app.paired = False
        app._configure_styles()
        app._build_window()
        app._set_pairing_view(True)
        app.notebook.select(app.events_tab)
        app._set_event_detail("\n".join(f"Lý do chặn dòng {index}" for index in range(80)))
        for width, height in [(600, 540), (680, 620)]:
            app.root.geometry(f"{width}x{height}+10000+10000")
            app.root.deiconify()
            app.root.update()
            detail_frame = app.event_detail.master
            assert app.event_detail.winfo_height() >= 80
            assert (
                detail_frame.winfo_y() + detail_frame.winfo_height()
                <= app.events_tab.winfo_height()
            )
            assert app.event_detail.cget("state") == "disabled"
            app.event_detail.yview_moveto(0)
            app._scroll_events(SimpleNamespace(delta=-120, widget=app.event_detail))
            assert app.event_detail.yview()[0] > 0
    finally:
        app.root.destroy()


@pytest.mark.skipif(os.name != "nt", reason="Tk layout verification requires Windows")
def test_child_activity_view_renders_shared_data_and_scrolls_long_top_ten():
    from common.activity_reports import activity_report

    app = TrayApplication.__new__(TrayApplication)
    app.root = tk.Tk()
    app.root.withdraw()
    try:
        app.paired = False
        app._configure_styles()
        app._build_window()
        app._set_pairing_view(True)
        report = activity_report([], end_date="2026-10-11", days=1)
        report.update(
            total_duration_sec=120,
            blocked_count=2,
            source="synced",
            requests=[{"minutes": 15, "status": "approved"}],
        )
        report["top_apps"] = [
            {"subject": "school-" + "a" * 90 + str(i) + ".exe", "duration_sec": 60, "starts": 1}
            for i in range(10)
        ]
        report["top_domains"] = [{"subject": f"school-{i}.test", "queries": 2} for i in range(10)]
        report["app_periods"] = {
            "1": report["top_apps"],
            "7": [{"subject": "week.exe", "duration_sec": 600, "starts": 1}],
            "90": [{"subject": "all.exe", "duration_sec": 3600, "starts": 1}],
        }
        app._update_activity_report(report)
        app.root.geometry("600x540+10000+10000")
        app.notebook.select(app.today_tab)
        app.root.deiconify()
        app.root.update()
        assert "02 phút 00 giây" in app.activity_summary.cget("text")
        assert "giống báo cáo của bố mẹ" in app.activity_summary.cget("text")
        today_titles = [
            child.cget("text")
            for widget in app.today_content.winfo_children()
            if isinstance(widget, ttk.Frame)
            for child in widget.winfo_children()
            if isinstance(child, ttk.Label)
        ]
        assert sum(title.startswith("Hôm nay em đã dùng gì") for title in today_titles) == 1
        cards = app.today_content.pack_slaves()
        assert "Thời gian còn lại" in [
            child.cget("text") for child in cards[1].winfo_children() if isinstance(child, ttk.Label)
        ]
        assert "Em cần thêm thời gian?" in [
            child.cget("text") for child in cards[2].winfo_children() if isinstance(child, ttk.Label)
        ]
        assert len(app.activity_chart.find_all()) > 20
        assert "school-0.test" in app.activity_chart.itemcget(
            app.activity_chart.find_all()[1], "text"
        )
        assert any("school-" in app.top_apps_chart.itemcget(item, "text") for item in app.top_apps_chart.find_withtag("all") if app.top_apps_chart.type(item) == "text")
        app.top_apps_period.set("1 tuần")
        app._draw_top_apps()
        assert "máy này" in app.top_apps_source.cget("text")
        assert any("week.exe" in app.top_apps_chart.itemcget(item, "text") for item in app.top_apps_chart.find_withtag("all") if app.top_apps_chart.type(item) == "text")
        app.top_apps_period.set("Toàn thời gian")
        app._draw_top_apps()
        assert any("all.exe" in app.top_apps_chart.itemcget(item, "text") for item in app.top_apps_chart.find_withtag("all") if app.top_apps_chart.type(item) == "text")
        app._scroll_today(SimpleNamespace(delta=-120))
        assert app.today_canvas.yview()[0] > 0
        app._update_activity_report(None)
        assert app.activity_summary.cget("text") == "Đăng nhập để xem hoạt động của em."
    finally:
        app.root.destroy()


@pytest.mark.skipif(os.name != "nt", reason="Tk layout verification requires Windows")
def test_login_has_own_default_tab_and_scrollable_today():
    app = TrayApplication.__new__(TrayApplication)
    app.root = tk.Tk()
    app.root.withdraw()
    try:
        app.root.geometry("680x620")
        app.paired = False
        app._configure_styles()
        app._build_window()
        app._set_pairing_view(True)
        app.root.update_idletasks()
        outer_children = app.footer.master.pack_slaves()
        assert outer_children.index(app.footer) < outer_children.index(app.notebook)
        assert app.footer.pack_info()["side"] == "bottom"
        assert [app.notebook.tab(i, "text") for i in range(4)] == [
            "Đăng nhập",
            "Hôm nay",
            "Chính sách",
            "Ứng dụng ghi nhận gì?",
        ]
        assert app.notebook.select() == str(app.login_tab)
        assert app.session_card.master is app.login_tab
        assert app.login_button.winfo_reqheight() > app.username_entry.winfo_reqheight()
        assert app.today_content.winfo_reqheight() > app.today_canvas.winfo_reqheight()
        assert app.privacy_content.winfo_reqheight() > app.privacy_canvas.winfo_reqheight()
        assert app.audit_label.master.master is app.policy_content
        app.current_user = None
        app.session_in_flight = False
        app.profile_login_required = True
        app.profile_options = {"An": "child-id"}
        app.remote_requests_available = True
        app._update_session_ui()
        app.username_entry.insert(0, "An")
        app._update_session_ui()
        assert app.username_entry.get() == "An"  # polling must not clear typed input
        app.session_result.configure(text="Đang kiểm tra PIN…")
        app.current_user = "An"
        app._update_session_ui()
        assert app.session_result.cget("text") == ""
        assert not app.login_fields.winfo_manager()
        assert app.logout_button.winfo_manager() == "pack"
        assert "Đã đăng nhập với tư cách An" in app.session_label.cget("text")
        app.end_session()
        assert app.username_entry.get() == ""
        app.username_entry.insert(0, "Bình")
        app._update_session_ui()
        assert app.username_entry.get() == "Bình"
        app.switching_profile = False
        app.current_user = None
        app._update_session_ui()
        assert app.login_fields.winfo_manager() == "pack"
        assert not app.logout_button.winfo_manager()
        assert app.username_entry.get() == "Bình"
    finally:
        app.root.destroy()


@pytest.mark.skipif(os.name != "nt", reason="Windows named objects are required")
def test_tray_singleton_signals_existing_instance_instead_of_starting_another():
    suffix = uuid.uuid4()
    mutex_name = rf"Global\OpenGuardKids.Test.Singleton.{suffix}"
    event_name = rf"Global\OpenGuardKids.Test.Show.{suffix}"
    refresh_name = rf"Global\OpenGuardKids.Test.Refresh.{suffix}"
    first = TrayInstanceGuard.acquire(
        mutex_name=mutex_name,
        show_event_name=event_name,
        refresh_event_name=refresh_name,
    )
    assert first is not None
    try:
        second = TrayInstanceGuard.acquire(
            mutex_name=mutex_name,
            show_event_name=event_name,
            refresh_event_name=refresh_name,
        )
        assert second is None
        assert first.consume_show_request() is True
        assert first.consume_refresh_request() is False
    finally:
        first.close()

    replacement = TrayInstanceGuard.acquire(
        mutex_name=mutex_name,
        show_event_name=event_name,
        refresh_event_name=refresh_name,
    )
    assert replacement is not None
    replacement.close()
