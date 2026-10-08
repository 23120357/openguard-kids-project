import os
import queue
import time
import tkinter as tk
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from agent.tray_ui import (
    TrayApplication,
    TrayInstanceGuard,
    format_clock,
    format_local_datetime,
    format_policy_schedule,
    format_used_duration,
    has_remaining_time,
)


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
    assert "Thứ hai: 00:00–01:00" in lines
    assert "Thứ ba: Không được sử dụng" in lines


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
    assert "Ngày thường: 45 phút/ngày" in ui.policy_summary_label.configure.call_args.kwargs["text"]
    assert (
        "Thứ hai: 00:00–00:00 (hôm sau)"
        in ui.policy_schedule_label.configure.call_args.kwargs["text"]
    )


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
        app.current_user = None
        app._update_session_ui()
        assert app.login_fields.winfo_manager() == "pack"
        assert not app.logout_button.winfo_manager()
        assert app.username_entry.get() == ""
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
