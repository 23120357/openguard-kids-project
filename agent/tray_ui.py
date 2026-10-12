"""Visible child-facing OpenGuard Kids Tray UI."""

from __future__ import annotations

import argparse
import ctypes
import logging
import os
import queue
import threading
import time
import tkinter as tk
from ctypes import wintypes
from datetime import UTC, datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tkinter import ttk
from typing import Any

import pystray
from PIL import Image, ImageDraw, ImageTk

from agent.named_pipe import NamedPipeClient, PipeUnavailableError, current_process_id
from agent.ui_scheduler import MonotonicScheduler
from agent.windows_activity import lock_workstation, sample_activity

BRAND = "#123B5D"
ACCENT = "#18A999"
PALE = "#EAF6F4"
INK = "#17324D"
MUTED = "#5D7183"
WARNING = "#B76E00"
LOGGER = logging.getLogger(__name__)
ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0
TRAY_MUTEX_NAME = r"Global\OpenGuardKids.Tray.Singleton.v1"
TRAY_SHOW_EVENT_NAME = r"Global\OpenGuardKids.Tray.Show.v1"
TRAY_REFRESH_EVENT_NAME = r"Global\OpenGuardKids.Tray.Refresh.v1"


def format_clock(seconds: float) -> str:
    """Format a non-negative duration as a fixed-width digital clock."""

    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, seconds_part = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{seconds_part:02d}"


def format_used_duration(seconds: float) -> str:
    """Show today's total usage in minutes and seconds, including past one hour."""

    minutes, seconds_part = divmod(max(0, int(seconds)), 60)
    return f"{minutes:02d} phút {seconds_part:02d} giây"


def disabled_time_detail(control: dict[str, Any]) -> str:
    return control.get("policy_error") or (
        "Chính sách thời gian đang tắt. "
        f"Hôm nay đã dùng {format_used_duration(control.get('used_seconds', 0))}."
    )


def format_local_datetime(moment: datetime) -> str:
    weekdays = ("Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy", "Chủ nhật")
    return f"{weekdays[moment.weekday()]}, {moment:%d/%m/%Y · %H:%M:%S}"


def has_remaining_time(value: Any) -> bool:
    """A missing quota is normal before a child signs in, not a UI error."""

    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def session_error_message(result: dict[str, Any] | Exception) -> str:
    """Explain a failed profile switch without hiding a stale profile or broken pipe."""
    if isinstance(result, PipeUnavailableError):
        return "Không kết nối được với agent service. Hãy kiểm tra hoặc khởi động lại service."
    if isinstance(result, Exception):
        return "Không thể liên lạc với agent service. Hãy thử lại sau."
    error = result.get("error", {})
    message = error.get("message")
    known = {
        "Incorrect child PIN": "PIN không đúng.",
        "Too many incorrect PIN attempts; try again in 15 minutes": (
            "Đã nhập sai PIN quá nhiều lần. Thử lại sau 15 phút."
        ),
        "Unknown child username": (
            "Không tìm thấy tên hồ sơ trên agent. Kiểm tra cách viết hoặc đợi đồng bộ từ server."
        ),
        "Choose an available child profile": "Hồ sơ chưa được đồng bộ tới agent.",
        "Pair this device before signing in": "Thiết bị chưa được ghép với tài khoản phụ huynh.",
    }
    if message in known:
        return known[message]
    if error.get("code") == "invalid_pin":
        return "PIN phải gồm đúng 6 chữ số."
    if error.get("code") == "internal_error":
        return "Agent service gặp lỗi khi xác thực hồ sơ. Hãy kiểm tra nhật ký service."
    code = error.get("code")
    return f"Không thể xác thực hồ sơ (mã lỗi: {code})." if code else "Không thể xác thực hồ sơ."


def configure_tray_logging() -> None:
    app_data = os.environ.get("LOCALAPPDATA")
    if not app_data:
        return
    try:
        log_dir = Path(app_data) / "OpenGuardKids"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(
            log_dir / "tray.log", maxBytes=1_000_000, backupCount=2, encoding="utf-8"
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOGGER.addHandler(handler)
        LOGGER.setLevel(logging.WARNING)
    except OSError:
        LOGGER.warning("Could not initialize the Tray log file", exc_info=True)


def format_audit_entry(item: dict[str, Any], names: dict[str, str]) -> str:
    old_value = item.get("old_value") if isinstance(item.get("old_value"), dict) else {}
    new_value = item.get("new_value") if isinstance(item.get("new_value"), dict) else {}
    changes = []
    for key, label in (
        ("version", "phiên bản"),
        ("enabled", "bật"),
        ("weekday_minutes", "ngày thường"),
        ("weekend_minutes", "cuối tuần"),
    ):
        if key in new_value and old_value.get(key) != new_value.get(key):
            changes.append(f"{label}: {old_value.get(key, '—')} → {new_value[key]}")
    if old_value.get("schedule") != new_value.get("schedule") and "schedule" in new_value:
        changes.append("lịch tuần đã đổi")
    detail = f" ({'; '.join(changes)})" if changes else ""
    timestamp = (
        datetime.fromtimestamp(float(item.get("ts", 0)), UTC)
        .astimezone()
        .strftime("%d/%m/%Y %H:%M:%S")
    )
    action = names.get(item.get("action"), item.get("action", "Thay đổi"))
    return (
        f"• {timestamp} · {item.get('actor', 'phụ huynh')} · "
        f"{item.get('ip', 'IP không rõ')} · {action}{detail}"
    )


def format_policy_schedule(rows: list[str]) -> str:
    days = ("Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy", "Chủ nhật")

    def slot_time(slot: int) -> str:
        if slot == 48:
            return "00:00 (hôm sau)"
        return f"{slot // 2:02d}:{(slot % 2) * 30:02d}"

    lines = []
    for day, row in zip(days, rows, strict=False):
        periods = []
        start = None
        for slot, allowed in enumerate(row + "0"):
            if allowed == "1" and start is None:
                start = slot
            elif allowed == "0" and start is not None:
                periods.append(f"{slot_time(start)}–{slot_time(slot)}")
                start = None
        lines.append(f"{day}: {', '.join(periods) if periods else 'Không được sử dụng'}")
    return "\n".join(lines)


class TrayInstanceGuard:
    """Own the per-session Tray singleton and its show-window signal."""

    def __init__(self, mutex_handle: int, show_event_handle: int, refresh_event_handle: int):
        self.mutex_handle = mutex_handle
        self.show_event_handle = show_event_handle
        self.refresh_event_handle = refresh_event_handle
        self._closed = False

    @classmethod
    def acquire(
        cls,
        *,
        mutex_name: str = TRAY_MUTEX_NAME,
        show_event_name: str = TRAY_SHOW_EVENT_NAME,
        refresh_event_name: str = TRAY_REFRESH_EVENT_NAME,
    ) -> TrayInstanceGuard | None:
        if os.name != "nt":
            raise RuntimeError("The Tray singleton is only available on Windows")
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
        kernel32.CreateMutexW.restype = wintypes.HANDLE
        kernel32.CreateEventW.argtypes = [
            wintypes.LPVOID,
            wintypes.BOOL,
            wintypes.BOOL,
            wintypes.LPCWSTR,
        ]
        kernel32.CreateEventW.restype = wintypes.HANDLE
        kernel32.SetEvent.argtypes = [wintypes.HANDLE]
        kernel32.SetEvent.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]

        ctypes.set_last_error(0)
        mutex_handle = kernel32.CreateMutexW(None, False, mutex_name)
        if not mutex_handle:
            raise OSError(ctypes.get_last_error(), "CreateMutexW failed")
        already_running = ctypes.get_last_error() == ERROR_ALREADY_EXISTS
        show_event_handle = kernel32.CreateEventW(None, False, False, show_event_name)
        if not show_event_handle:
            error = ctypes.get_last_error()
            kernel32.CloseHandle(mutex_handle)
            raise OSError(error, "CreateEventW failed")
        refresh_event_handle = kernel32.CreateEventW(None, False, False, refresh_event_name)
        if not refresh_event_handle:
            error = ctypes.get_last_error()
            kernel32.CloseHandle(show_event_handle)
            kernel32.CloseHandle(mutex_handle)
            raise OSError(error, "CreateEventW failed")

        if already_running:
            kernel32.SetEvent(show_event_handle)
            kernel32.CloseHandle(refresh_event_handle)
            kernel32.CloseHandle(show_event_handle)
            kernel32.CloseHandle(mutex_handle)
            return None
        return cls(mutex_handle, show_event_handle, refresh_event_handle)

    def consume_show_request(self) -> bool:
        if self._closed:
            return False
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        return kernel32.WaitForSingleObject(self.show_event_handle, 0) == WAIT_OBJECT_0

    def consume_refresh_request(self) -> bool:
        if self._closed:
            return False
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        kernel32.WaitForSingleObject.restype = wintypes.DWORD
        return kernel32.WaitForSingleObject(self.refresh_event_handle, 0) == WAIT_OBJECT_0

    def close(self) -> None:
        if self._closed:
            return
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle(self.refresh_event_handle)
        kernel32.CloseHandle(self.show_event_handle)
        kernel32.CloseHandle(self.mutex_handle)
        self._closed = True


def create_icon_image(size: int = 128) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    margin = size // 10
    shield = [
        (size // 2, margin),
        (size - margin, size // 4),
        (size - margin - 4, size * 3 // 5),
        (size // 2, size - margin),
        (margin + 4, size * 3 // 5),
        (margin, size // 4),
    ]
    draw.polygon(shield, fill=BRAND)
    draw.ellipse(
        (size * 27 // 100, size * 30 // 100, size * 73 // 100, size * 76 // 100),
        fill=ACCENT,
    )
    draw.arc(
        (size * 36 // 100, size * 41 // 100, size * 64 // 100, size * 65 // 100),
        start=15,
        end=165,
        fill="white",
        width=max(3, size // 22),
    )
    return image


class TrayApplication:
    REFRESH_MS = 1000
    VISUAL_REPORT_REFRESH_SECONDS = 60

    def __init__(self, *, instance_guard: TrayInstanceGuard, start_open: bool = False):
        self.instance_guard = instance_guard
        self.root = tk.Tk()
        self.scheduler = MonotonicScheduler()
        self.root.title("OpenGuard Kids")
        self.root.geometry("680x620")
        self.root.minsize(600, 540)
        self.root.configure(background="#F4F8FB")
        self.root.protocol("WM_DELETE_WINDOW", self.hide_window)
        self.client = NamedPipeClient(timeout_ms=1200)
        self.responses: queue.Queue[tuple[str, dict[str, Any] | Exception]] = queue.Queue()
        self.closing = False
        self.connected = False
        self.status_in_flight = False
        self.status_requested_at = 0.0
        self.request_in_flight = False
        self.session_in_flight = False
        self.switching_profile = False
        self.current_user: str | None = None
        self.active_child_id: str | None = None
        self.profile_options: dict[str, str] = {}
        self.paired = False
        self.enrollment_in_flight = False
        self.profile_login_required = False
        self.remote_requests_available = False
        self.demo_in_flight = False
        self.notified_event_ids: set[str] = set()
        self.block_notice_keys: set[tuple[str | None, str, str, str]] = set()
        self.block_notice_scope = None
        self.block_ack_attempts: dict[str, float] = {}
        self.completed_lock_attempts: set[str] = set()
        self._configure_styles()
        self._build_window()
        self._update_today_datetime()

        image = create_icon_image()
        self.window_icon = ImageTk.PhotoImage(image)
        self.root.iconphoto(True, self.window_icon)
        self.icon = pystray.Icon(
            "OpenGuardKids",
            image,
            "OpenGuard Kids - Đang kết nối...",
            menu=pystray.Menu(
                pystray.MenuItem("Mở OpenGuard Kids", self._tray_open, default=True),
                pystray.MenuItem(self._tray_status, None, enabled=False),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Xin thêm thời gian…", self._tray_request_time),
                pystray.MenuItem("Ứng dụng ghi nhận gì?", self._tray_open_privacy),
                pystray.Menu.SEPARATOR,
                pystray.MenuItem("Thoát giao diện", self._tray_exit),
            ),
        )
        self.icon.run_detached()
        if not start_open:
            self.root.withdraw()
        self.scheduler.after(300, self._show_startup_notification)
        self.scheduler.after(100, self._poll_responses)
        self.scheduler.after(100, self._poll_show_requests)
        self.scheduler.after(150, self.refresh_status)

    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Root.TFrame", background="#F4F8FB")
        style.configure("Card.TFrame", background="white", relief="flat")
        style.configure(
            "Title.TLabel", background="#F4F8FB", foreground=INK, font=("Segoe UI", 22, "bold")
        )
        style.configure(
            "Subtitle.TLabel", background="#F4F8FB", foreground=MUTED, font=("Segoe UI", 10)
        )
        style.configure(
            "TodayDate.TLabel", background="#F4F8FB", foreground=INK, font=("Segoe UI", 11, "bold")
        )
        style.configure(
            "CardTitle.TLabel", background="white", foreground=INK, font=("Segoe UI", 12, "bold")
        )
        style.configure("Body.TLabel", background="white", foreground=INK, font=("Segoe UI", 10))
        style.configure("Muted.TLabel", background="white", foreground=MUTED, font=("Segoe UI", 9))
        style.configure(
            "Status.TLabel",
            background=PALE,
            foreground=BRAND,
            font=("Segoe UI", 10, "bold"),
            padding=(10, 6),
        )
        style.configure(
            "Time.TLabel", background="white", foreground=BRAND, font=("Consolas", 30, "bold")
        )
        style.configure(
            "Accent.TButton",
            font=("Segoe UI", 10, "bold"),
            padding=(14, 9),
            background=ACCENT,
            foreground="white",
        )
        style.map("Accent.TButton", background=[("active", "#13887C"), ("disabled", "#A8C8C3")])
        style.configure("Secondary.TButton", font=("Segoe UI", 9), padding=(11, 7))
        style.configure("TNotebook", background="#F4F8FB", borderwidth=0)
        style.configure("TNotebook.Tab", font=("Segoe UI", 10, "bold"), padding=(14, 8))

    def _build_window(self) -> None:
        outer = ttk.Frame(self.root, style="Root.TFrame", padding=24)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer, style="Root.TFrame")
        header.pack(fill="x", pady=(0, 16))
        ttk.Label(header, text="OpenGuard Kids", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Công cụ đồng hành cùng em khi sử dụng máy tính",
            style="Subtitle.TLabel",
        ).pack(anchor="w", pady=(3, 0))

        self.status_label = ttk.Label(
            outer, text="Đang kết nối với dịch vụ...", style="Status.TLabel"
        )
        self.status_label.pack(fill="x", pady=(0, 14))

        self.pairing_frame = ttk.Frame(outer, style="Card.TFrame", padding=24)
        ttk.Label(self.pairing_frame, text="Ghép máy với gia đình", style="CardTitle.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            self.pairing_frame,
            text="Nhập mã 8 ký tự do phụ huynh tạo trên dashboard.",
            style="Body.TLabel",
        ).pack(anchor="w", pady=(12, 10))
        self.pairing_code = ttk.Entry(self.pairing_frame, width=20)
        self.pairing_code.pack(anchor="w")
        self.pairing_button = ttk.Button(
            self.pairing_frame, text="Ghép đôi", style="Accent.TButton", command=self.enroll_device
        )
        self.pairing_button.pack(anchor="w", pady=(12, 0))
        self.pairing_result = ttk.Label(self.pairing_frame, text="", style="Muted.TLabel")
        self.pairing_result.pack(anchor="w", pady=(10, 0))

        notebook = ttk.Notebook(outer)
        self.notebook = notebook

        login_tab = ttk.Frame(notebook, style="Root.TFrame", padding=(0, 14))
        today = ttk.Frame(notebook, style="Root.TFrame")
        policy = ttk.Frame(notebook, style="Root.TFrame", padding=(0, 14))
        privacy = ttk.Frame(notebook, style="Root.TFrame", padding=(0, 14))
        notebook.add(login_tab, text="Đăng nhập")
        notebook.add(today, text="Hôm nay")
        notebook.add(policy, text="Chính sách")
        notebook.add(privacy, text="Ứng dụng ghi nhận gì?")
        events_tab = ttk.Frame(notebook, style="Root.TFrame", padding=(0, 14))
        notebook.add(events_tab, text="Sự kiện")
        self.events_tab = events_tab
        events_tab.columnconfigure(0, weight=1)
        events_tab.rowconfigure(1, weight=3, minsize=90)
        events_tab.rowconfigure(2, weight=1, minsize=110)
        ttk.Label(
            events_tab, text="Các lần ứng dụng hoặc trang web bị chặn", style="Body.TLabel"
        ).grid(row=0, column=0, sticky="w", pady=8)
        events_list = ttk.Frame(events_tab)
        events_list.grid(row=1, column=0, sticky="nsew")
        self.events_tree = ttk.Treeview(
            events_list, columns=("time", "subject", "reason"), show="headings"
        )
        for column, title, width in [
            ("time", "Thời gian", 150),
            ("subject", "Trang web / ứng dụng", 180),
            ("reason", "Lý do chặn", 300),
        ]:
            self.events_tree.heading(column, text=title)
            self.events_tree.column(column, width=width, minwidth=100, stretch=True)
        event_scroll = ttk.Scrollbar(events_list, orient="vertical", command=self.events_tree.yview)
        self.events_tree.configure(yscrollcommand=event_scroll.set)
        event_scroll.pack(side="right", fill="y")
        self.events_tree.pack(fill="both", expand=True)
        detail_frame = ttk.Frame(events_tab)
        detail_frame.grid(row=2, column=0, sticky="nsew", pady=(12, 0))
        self.event_detail = tk.Text(
            detail_frame,
            height=5,
            width=1,
            wrap="word",
            font=("Segoe UI", 10),
            background="white",
            borderwidth=0,
            padx=8,
            pady=8,
        )
        self.event_detail_scrollbar = ttk.Scrollbar(
            detail_frame, orient="vertical", command=self.event_detail.yview
        )
        self.event_detail.configure(yscrollcommand=self.event_detail_scrollbar.set)
        self.event_detail_scrollbar.pack(side="right", fill="y")
        self.event_detail.pack(side="left", fill="both", expand=True)
        self._set_event_detail("Chọn một sự kiện để xem đầy đủ lý do.")

        def show_event_detail(_event):
            selected = self.events_tree.selection()
            values = self.events_tree.item(selected[0], "values") if selected else []
            self._set_event_detail("\n".join(values))

        self.events_tree.bind("<<TreeviewSelect>>", show_event_detail)
        self._bind_tab_mousewheel(events_tab, self._scroll_events)
        self.block_popup = None
        self.block_popup_ids = set()
        self.login_tab = login_tab
        self.today_tab = today
        self.policy_tab = policy
        self.privacy_tab = privacy

        today_canvas = tk.Canvas(today, background="#F4F8FB", highlightthickness=0)
        today_scrollbar = ttk.Scrollbar(today, orient="vertical", command=today_canvas.yview)
        today_canvas.configure(yscrollcommand=today_scrollbar.set)
        today_scrollbar.pack(side="right", fill="y")
        today_canvas.pack(side="left", fill="both", expand=True)
        today_content = ttk.Frame(today_canvas, style="Root.TFrame", padding=(0, 14, 8, 14))
        content_window = today_canvas.create_window((0, 0), window=today_content, anchor="nw")
        today_content.bind(
            "<Configure>",
            lambda _event: today_canvas.configure(scrollregion=today_canvas.bbox("all")),
        )
        today_canvas.bind(
            "<Configure>",
            lambda event: today_canvas.itemconfigure(content_window, width=event.width),
        )
        self.today_canvas = today_canvas
        self.today_content = today_content
        today_canvas.bind("<MouseWheel>", self._scroll_today)
        self.today_datetime_label = ttk.Label(today_content, text="", style="TodayDate.TLabel")
        self.today_datetime_label.pack(anchor="w", pady=(0, 12))

        activity_card = ttk.Frame(today_content, style="Card.TFrame", padding=20)
        activity_card.pack(fill="x", pady=(0, 12))
        ttk.Label(activity_card, text="Hôm nay em đã dùng gì?", style="CardTitle.TLabel").pack(
            anchor="w"
        )
        illustration = tk.Canvas(
            activity_card, height=48, width=180, background="white", highlightthickness=0
        )
        illustration.pack(anchor="w", pady=8)
        illustration.create_rectangle(8, 4, 64, 35, outline="#226B54", width=3)
        illustration.create_line(0, 42, 72, 42, fill="#226B54", width=4)
        illustration.create_oval(96, 3, 138, 45, outline="#327E68", width=2)
        illustration.create_oval(108, 3, 126, 45, outline="#327E68")
        illustration.create_line(96, 24, 138, 24, fill="#327E68")
        self.activity_summary = ttk.Label(
            activity_card,
            text="Đăng nhập để xem hoạt động của em.",
            wraplength=500,
            style="Body.TLabel",
        )
        self.activity_summary.pack(fill="x", pady=6)
        self.activity_chart = tk.Canvas(
            activity_card, height=50, background="white", highlightthickness=0
        )
        self.activity_chart.pack(fill="x", pady=8)
        self._today_activity_report = None
        self.activity_chart.bind("<Configure>", lambda _event: self._draw_activity_report())
        self.eye_hint = ttk.Label(
            activity_card,
            text="Nhớ nghỉ mắt: cứ 20 phút, nhìn xa khoảng 6 mét trong 20 giây.",
            wraplength=500,
            style="Body.TLabel",
        )
        self.eye_hint.pack(fill="x", pady=6)

        time_card = ttk.Frame(today_content, style="Card.TFrame", padding=20)
        time_card.pack(fill="x", pady=(0, 12))
        ttk.Label(time_card, text="Thời gian còn lại", style="CardTitle.TLabel").pack(anchor="w")
        self.time_label = ttk.Label(time_card, text="--:--:--", style="Time.TLabel")
        self.time_label.pack(anchor="w", pady=(8, 3))
        self.time_detail_label = ttk.Label(
            time_card,
            text="Đang tải chính sách thời gian từ dịch vụ.",
            style="Muted.TLabel",
        )
        self.time_detail_label.pack(anchor="w")
        demo_row = ttk.Frame(time_card, style="Card.TFrame")
        demo_row.pack(fill="x", pady=(12, 0))
        self.demo_button = ttk.Button(
            demo_row,
            text="Demo developer: giảm 1 phút",
            style="Secondary.TButton",
            command=lambda: self.reduce_demo_time(60),
        )
        self.demo_button.pack(side="left")
        self.demo_button.state(["disabled"])
        self.demo_result = ttk.Label(demo_row, text="", style="Muted.TLabel")
        self.demo_result.pack(side="left", padx=(10, 0))

        session_card = ttk.Frame(login_tab, style="Card.TFrame", padding=20)
        session_card.pack(fill="x", pady=(0, 12))
        self.session_card = session_card
        ttk.Label(session_card, text="Ai đang sử dụng máy?", style="CardTitle.TLabel").pack(
            anchor="w"
        )
        self.session_label = ttk.Label(
            session_card,
            text="Nhập tên đăng nhập và PIN 6 chữ số của em.",
            style="Body.TLabel",
            wraplength=550,
        )
        self.session_label.pack(anchor="w", pady=(8, 8))
        fields = ttk.Frame(session_card, style="Card.TFrame")
        fields.pack(fill="x")
        self.login_fields = fields
        fields.columnconfigure(0, weight=3)
        fields.columnconfigure(1, weight=1)
        ttk.Label(fields, text="Tên đăng nhập", style="Body.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        ttk.Label(fields, text="PIN 6 số", style="Body.TLabel").grid(row=0, column=1, sticky="w")
        self.username_entry = ttk.Entry(fields, width=24)
        self.username_entry.grid(row=1, column=0, sticky="ew", padx=(0, 12), pady=(5, 0), ipady=4)
        self.pin_entry = ttk.Entry(fields, show="●", width=12)
        self.pin_entry.grid(row=1, column=1, sticky="ew", pady=(5, 0), ipady=4)
        self.username_entry.bind("<Return>", lambda _event: self.start_session())
        self.pin_entry.bind("<Return>", lambda _event: self.start_session())
        actions = ttk.Frame(session_card, style="Card.TFrame")
        actions.pack(fill="x", pady=(14, 0))
        self.login_actions = actions
        self.login_button = ttk.Button(
            actions,
            text="Đăng nhập",
            style="Accent.TButton",
            command=self.start_session,
        )
        self.login_button.pack(side="left")
        self.logout_button = ttk.Button(
            actions,
            text="Kết thúc phiên",
            style="Secondary.TButton",
            command=self.end_session,
        )
        self.logout_button.state(["disabled"])
        self.session_result = ttk.Label(session_card, text="", style="Muted.TLabel")
        self.session_result.pack(anchor="w", pady=(8, 0))

        request_card = ttk.Frame(today_content, style="Card.TFrame", padding=20)
        request_card.pack(fill="x", pady=(0, 12))
        ttk.Label(request_card, text="Em cần thêm thời gian?", style="CardTitle.TLabel").pack(
            anchor="w"
        )
        ttk.Label(
            request_card,
            text="Phụ huynh sẽ nhận yêu cầu cùng tên người gửi, thiết bị và số phút mong muốn. Mặc định 15 phút.",
            style="Body.TLabel",
            wraplength=570,
            justify="left",
        ).pack(anchor="w", pady=(7, 12))
        row = ttk.Frame(request_card, style="Card.TFrame")
        row.pack(fill="x")
        self.request_button = ttk.Button(
            row,
            text="Xin thêm giờ",
            style="Accent.TButton",
            command=self._request_selected_time,
        )
        self.request_button.pack(side="left")
        self.request_button.state(["disabled"])
        ttk.Label(row, text="Số phút:", style="Body.TLabel").pack(side="left", padx=(12, 5))
        self.request_minutes = tk.Spinbox(row, from_=1, to=120, width=5, increment=1)
        self.request_minutes.delete(0, "end")
        self.request_minutes.insert(0, "15")
        self.request_minutes.pack(side="left")
        self.request_result = ttk.Label(request_card, text="", style="Muted.TLabel", wraplength=570)
        self.request_result.pack(anchor="w", pady=(10, 0))
        time_card.pack_forget()
        time_card.pack(before=activity_card, fill="x", pady=(0, 12))
        request_card.pack_forget()
        request_card.pack(after=time_card, fill="x", pady=(0, 12))

        apps_card = ttk.Frame(today_content, style="Card.TFrame", padding=20)
        apps_card.pack(fill="x", pady=(12, 0))
        ttk.Label(apps_card, text="Top 10 ứng dụng", style="CardTitle.TLabel").pack(anchor="w")
        self.top_apps_period = tk.StringVar(value="1 ngày")
        period_select = ttk.Combobox(
            apps_card,
            textvariable=self.top_apps_period,
            values=("1 ngày", "1 tuần", "Toàn thời gian"),
            state="readonly",
            width=20,
        )
        period_select.pack(anchor="w", pady=(8, 6))
        period_select.bind("<<ComboboxSelected>>", lambda _event: self._draw_top_apps())
        self.top_apps_source = ttk.Label(
            apps_card,
            text="Ứng dụng có thể chạy nền hoặc cùng lúc.",
            style="Body.TLabel",
            wraplength=500,
        )
        self.top_apps_source.pack(anchor="w", pady=(0, 8))
        self.top_apps_chart = tk.Canvas(
            apps_card, background="#FFFFFF", highlightthickness=0, height=1
        )
        self.top_apps_chart.pack(fill="x")
        self.top_apps_chart.bind("<Configure>", lambda _event: self._draw_top_apps())

        policy_canvas = tk.Canvas(policy, background="#F4F8FB", highlightthickness=0)
        policy_scrollbar = ttk.Scrollbar(policy, orient="vertical", command=policy_canvas.yview)
        policy_canvas.configure(yscrollcommand=policy_scrollbar.set)
        policy_scrollbar.pack(side="right", fill="y")
        policy_canvas.pack(side="left", fill="both", expand=True)
        policy_content = ttk.Frame(policy_canvas, style="Root.TFrame", padding=(0, 0, 8, 0))
        policy_window = policy_canvas.create_window((0, 0), window=policy_content, anchor="nw")
        policy_content.bind(
            "<Configure>",
            lambda _event: policy_canvas.configure(scrollregion=policy_canvas.bbox("all")),
        )
        policy_canvas.bind(
            "<Configure>",
            lambda event: policy_canvas.itemconfigure(policy_window, width=event.width),
        )
        self.policy_canvas = policy_canvas
        self.policy_content = policy_content
        policy_canvas.bind("<MouseWheel>", self._scroll_policy)

        policy_card = ttk.Frame(policy_content, style="Card.TFrame", padding=22)
        policy_card.pack(fill="x", pady=(0, 12))
        ttk.Label(policy_card, text="Chính sách hiện tại", style="CardTitle.TLabel").pack(
            anchor="w"
        )
        self.policy_summary_label = ttk.Label(
            policy_card,
            text="Đăng nhập để xem chính sách của em.",
            style="Body.TLabel",
            wraplength=550,
            justify="left",
        )
        self.policy_summary_label.pack(anchor="w", pady=(10, 0))
        self.policy_schedule_label = ttk.Label(
            policy_card, text="", style="Body.TLabel", wraplength=550, justify="left"
        )
        self.policy_schedule_label.pack(anchor="w", pady=(10, 0))
        audit_card = ttk.Frame(policy_content, style="Card.TFrame", padding=22)
        audit_card.pack(fill="x")
        ttk.Label(audit_card, text="Nhật ký thay đổi", style="CardTitle.TLabel").pack(anchor="w")
        self.audit_label = ttk.Label(
            audit_card,
            text="Chưa đồng bộ nhật ký.",
            style="Body.TLabel",
            wraplength=550,
            justify="left",
        )
        self.audit_label.pack(anchor="w", pady=(10, 0))

        privacy_canvas = tk.Canvas(privacy, background="#F4F8FB", highlightthickness=0)
        privacy_scrollbar = ttk.Scrollbar(privacy, orient="vertical", command=privacy_canvas.yview)
        privacy_canvas.configure(yscrollcommand=privacy_scrollbar.set)
        privacy_scrollbar.pack(side="right", fill="y")
        privacy_canvas.pack(side="left", fill="both", expand=True)
        privacy_content = ttk.Frame(privacy_canvas, style="Root.TFrame", padding=(0, 0, 8, 0))
        privacy_window = privacy_canvas.create_window((0, 0), window=privacy_content, anchor="nw")
        privacy_content.bind(
            "<Configure>",
            lambda _event: privacy_canvas.configure(scrollregion=privacy_canvas.bbox("all")),
        )
        privacy_canvas.bind(
            "<Configure>",
            lambda event: privacy_canvas.itemconfigure(privacy_window, width=event.width),
        )
        self.privacy_canvas = privacy_canvas
        self.privacy_content = privacy_content
        privacy_canvas.bind("<MouseWheel>", self._scroll_privacy)

        privacy_card = ttk.Frame(privacy_content, style="Card.TFrame", padding=22)
        privacy_card.pack(fill="both", expand=True)
        ttk.Label(
            privacy_card, text="Ứng dụng này ghi nhận gì về em?", style="CardTitle.TLabel"
        ).pack(anchor="w")
        privacy_text = (
            "Dịch vụ ghi nhận tổng thời gian sử dụng, trạng thái không hoạt động và trạng thái "
            "khóa màn hình để áp dụng giới hạn hằng ngày và lịch sử dụng.\n\n"
            "Ứng dụng không đọc nội dung em gõ, tin nhắn, email hay tài liệu; không chụp màn "
            "hình; và không theo dõi tên ứng dụng hoặc trang web.\n\n"
            "Dịch vụ không ẩn. Biểu tượng OpenGuard Kids luôn xuất hiện ở khay hệ thống khi "
            "giao diện đang chạy. Nếu giao diện mất kết nối, việc đếm thời gian và yêu cầu khóa "
            "máy sẽ dừng cho tới khi giao diện xuất hiện lại."
        )
        ttk.Label(
            privacy_card,
            text=privacy_text,
            style="Body.TLabel",
            wraplength=570,
            justify="left",
        ).pack(anchor="w", pady=(12, 18))
        self.details_label = ttk.Label(
            privacy_card,
            text="Dịch vụ: đang kiểm tra\nChế độ kiểm soát: tắt\nDNS: không lọc",
            style="Status.TLabel",
            justify="left",
        )
        self.details_label.pack(fill="x")
        self._bind_tab_mousewheel(today_content, self._scroll_today)
        self._bind_tab_mousewheel(policy_content, self._scroll_policy)
        self._bind_tab_mousewheel(privacy_content, self._scroll_privacy)

        footer = ttk.Frame(outer, style="Root.TFrame")
        footer.pack(side="bottom", fill="x", pady=(14, 0))
        self.footer = footer
        ttk.Label(
            footer,
            text="Đóng cửa sổ sẽ giữ biểu tượng ở khay hệ thống.",
            style="Subtitle.TLabel",
        ).pack(side="left")
        ttk.Button(footer, text="Ẩn xuống khay", command=self.hide_window).pack(side="right")

    def _show_startup_notification(self) -> None:
        try:
            self.icon.notify(
                "OpenGuard Kids đang hiển thị và kết nối với dịch vụ trên máy.",
                "OpenGuard Kids",
            )
        except Exception:
            LOGGER.debug("Windows notification could not be displayed", exc_info=True)

    def _update_today_datetime(self) -> None:
        if self.closing:
            return
        self.today_datetime_label.configure(text=format_local_datetime(datetime.now().astimezone()))
        self.scheduler.after(1000, self._update_today_datetime)

    def _tray_status(self, _item) -> str:
        return "Dịch vụ: đã kết nối" if self.connected else "Dịch vụ: ngoại tuyến"

    def _tray_open(self, _icon=None, _item=None) -> None:
        self.scheduler.after(0, self.show_window)

    def _tray_open_privacy(self, _icon=None, _item=None) -> None:
        def open_tab():
            self.notebook.select(self.privacy_tab)
            self.show_window()

        self.scheduler.after(0, open_tab)

    def _scroll_today(self, event) -> str | None:
        return self._scroll_tab(event, self.today_tab, self.today_canvas)

    def _scroll_privacy(self, event) -> str | None:
        return self._scroll_tab(event, self.privacy_tab, self.privacy_canvas)

    def _scroll_policy(self, event) -> str | None:
        return self._scroll_tab(event, self.policy_tab, self.policy_canvas)

    def _scroll_events(self, event) -> str | None:
        widget = getattr(event, "widget", None)
        detail_widgets = (
            getattr(self, "event_detail", None),
            getattr(self, "event_detail_scrollbar", None),
        )
        target = (
            self.event_detail
            if widget is not None and widget in detail_widgets
            else self.events_tree
        )
        return self._scroll_tab(event, self.events_tab, target)

    def _set_event_detail(self, text: str) -> None:
        self.event_detail.configure(state="normal")
        self.event_detail.delete("1.0", "end")
        self.event_detail.insert("1.0", text)
        self.event_detail.configure(state="disabled")
        self.event_detail.yview_moveto(0)

    def _scroll_tab(self, event, tab, canvas) -> str | None:
        if self.notebook.select() != str(tab) or not event.delta:
            return None
        units = max(1, abs(event.delta) // 120)
        canvas.yview_scroll(-units if event.delta > 0 else units, "units")
        return "break"

    def _bind_tab_mousewheel(self, widget, callback) -> None:
        if not isinstance(widget, tk.Spinbox):
            widget.bind("<MouseWheel>", callback, add="+")
        for child in widget.winfo_children():
            self._bind_tab_mousewheel(child, callback)

    def _tray_request_time(self, _icon=None, _item=None) -> None:
        self.scheduler.after(0, self._request_selected_time)

    def _tray_exit(self, _icon=None, _item=None) -> None:
        self.scheduler.after(0, self.exit)

    def show_window(self) -> None:
        self.root.deiconify()
        self.root.state("normal")
        self.root.lift()
        self.root.focus_force()
        self.root.update_idletasks()
        try:
            user32 = ctypes.WinDLL("user32", use_last_error=True)
            user32.ShowWindow(wintypes.HWND(self.root.winfo_id()), 9)
            user32.SetForegroundWindow(wintypes.HWND(self.root.winfo_id()))
        except OSError:
            LOGGER.debug("Windows did not foreground the existing Tray window", exc_info=True)

    def hide_window(self) -> None:
        self.root.withdraw()

    def exit(self) -> None:
        self.closing = True
        try:
            self.icon.stop()
        finally:
            self.root.destroy()

    def _send_async(
        self, action: str, message_type: str, payload: dict[str, Any] | None = None
    ) -> None:
        def work():
            try:
                client = NamedPipeClient(timeout_ms=5000) if action == "session_start" else self.client
                result: dict[str, Any] | Exception = client.request(message_type, payload)
            except Exception as exc:
                LOGGER.debug("Local IPC request failed: %s", action, exc_info=True)
                result = exc
            self.responses.put((action, result))

        threading.Thread(target=work, name=f"ogk-{action}", daemon=True).start()

    def refresh_status(self) -> None:
        if self.closing or self.status_in_flight:
            return
        try:
            activity = sample_activity()
            idle_seconds = activity.idle_seconds
            session_locked = activity.session_locked
        except (OSError, RuntimeError):
            LOGGER.warning(
                "Could not sample Windows activity; using safe inactive state", exc_info=True
            )
            idle_seconds = 0
            session_locked = True
        self.status_in_flight = True
        self.status_requested_at = time.monotonic()
        self._send_async(
            "status",
            "ui_heartbeat",
            {
                "process_id": current_process_id(),
                "visible": True,
                "idle_seconds": idle_seconds,
                "session_locked": session_locked,
            },
        )

    def request_more_time(self, minutes: int) -> None:
        if self.request_in_flight:
            return
        if not self.current_user:
            self.request_result.configure(
                text="Hãy đăng nhập vào phiên sử dụng trước.", foreground=WARNING
            )
            return
        if not self.remote_requests_available:
            self.request_result.configure(
                text="Thiết bị chưa được ghép với dashboard phụ huynh.", foreground=WARNING
            )
            return
        self.request_in_flight = True
        self.request_button.state(["disabled"])
        self.request_result.configure(text="Đang gửi yêu cầu tới dịch vụ trên máy...")
        self._send_async("request_time", "request_more_time", {"minutes": minutes})

    def _request_selected_time(self) -> None:
        try:
            minutes = int(self.request_minutes.get())
        except ValueError:
            self.request_result.configure(text="Nhập số phút từ 1 đến 120.", foreground=WARNING)
            return
        if not 1 <= minutes <= 120:
            self.request_result.configure(text="Nhập số phút từ 1 đến 120.", foreground=WARNING)
            return
        self.request_more_time(minutes)

    def start_session(self) -> None:
        if self.session_in_flight or (
            self.current_user and not getattr(self, "switching_profile", False)
        ):
            return
        username = self.username_entry.get().strip()
        if self.profile_login_required and not username:
            self.session_result.configure(
                text="Hãy nhập tên đăng nhập trước khi nhập PIN.", foreground=WARNING
            )
            return
        pin = self.pin_entry.get()
        self.session_in_flight = True
        self.login_button.state(["disabled"])
        self.session_result.configure(text="Đang kiểm tra PIN…", foreground=MUTED)
        payload = {"pin": pin}
        if self.profile_login_required:
            payload["username"] = username
        self._send_async("session_start", "start_session", payload)
        self.pin_entry.delete(0, "end")

    def enroll_device(self) -> None:
        if self.enrollment_in_flight or self.paired:
            return
        code = self.pairing_code.get().strip().upper()
        if len(code) != 8:
            self.pairing_result.configure(text="Mã ghép đôi phải có 8 ký tự.", foreground=WARNING)
            return
        self.enrollment_in_flight = True
        self.pairing_button.state(["disabled"])
        self.pairing_result.configure(text="Đang ghép đôi...", foreground=MUTED)
        self._send_async("enroll_device", "enroll_device", {"code": code})

    def _set_pairing_view(self, paired: bool) -> None:
        if self.paired and not paired:
            return
        self.paired = paired
        if paired:
            self.pairing_frame.pack_forget()
            if not self.notebook.winfo_manager():
                self.notebook.pack(fill="both", expand=True)
        else:
            self.notebook.pack_forget()
            if not self.pairing_frame.winfo_manager():
                self.pairing_frame.pack(fill="both", expand=True)

    def end_session(self) -> None:
        if self.session_in_flight or not self.current_user:
            return
        if self.profile_login_required:
            self.switching_profile = True
            self._update_session_ui()
            return
        self.session_in_flight = True
        self.logout_button.state(["disabled"])
        self._send_async("session_end", "end_session")

    def reduce_demo_time(self, seconds: int) -> None:
        if self.demo_in_flight:
            return
        self.demo_in_flight = True
        self.demo_button.state(["disabled"])
        self.demo_result.configure(text="Đang giảm thời gian demo...", foreground=MUTED)
        self._send_async("demo_reduce", "demo_reduce_time", {"seconds": seconds})

    def _poll_responses(self) -> None:
        if self.closing:
            return
        try:
            while True:
                try:
                    action, result = self.responses.get_nowait()
                except queue.Empty:
                    break
                if action == "status":
                    self.status_in_flight = False
                    elapsed_ms = int((time.monotonic() - self.status_requested_at) * 1000)
                    self.scheduler.after(max(1, self.REFRESH_MS - elapsed_ms), self.refresh_status)
                    self._apply_status(result)
                elif action == "request_time":
                    self._apply_request_result(result)
                elif action == "demo_reduce":
                    self._apply_demo_result(result)
                elif action == "enroll_device":
                    self.enrollment_in_flight = False
                    self.pairing_button.state(["!disabled"])
                    if isinstance(result, Exception) or not result.get("ok"):
                        error = (
                            result.get("error", {}).get("message", "Không thể kết nối dịch vụ.")
                            if isinstance(result, dict)
                            else "Không thể kết nối dịch vụ."
                        )
                        self.pairing_result.configure(text=error, foreground=WARNING)
                    else:
                        self.pairing_code.delete(0, "end")
                        self._set_pairing_view(True)
                        self.refresh_status()
                elif action in {"session_start", "session_end"}:
                    self.session_in_flight = False
                    if isinstance(result, Exception) or not result.get("ok"):
                        message = session_error_message(result)
                        error = result.get("error", {}) if isinstance(result, dict) else {}
                        LOGGER.warning(
                            "Profile session request failed: code=%s detail=%s exception=%s",
                            error.get("code"), error.get("message"),
                            type(result).__name__ if isinstance(result, Exception) else None,
                        )
                        self.session_result.configure(
                            text=message, foreground=WARNING
                        )
                        self.login_button.state(["!disabled"])
                        self.logout_button.state(["disabled"])
                    else:
                        self.switching_profile = False
                        self.current_user = result["data"].get("current_user")
                        self.active_child_id = result["data"].get("active_child_id")
                        self._update_session_ui()
                        if not self.current_user:
                            self._update_policy_ui(None)
                        self.refresh_status()
        except Exception:  # Keep the Tk event loop alive after a UI callback error.
            LOGGER.exception("Tray response processing failed")
            self.status_label.configure(text="Giao diện gặp lỗi; đang thử cập nhật lại.")
        finally:
            if not self.closing:
                self.scheduler.after(100, self._poll_responses)

    def _poll_show_requests(self) -> None:
        if self.closing:
            return
        if self.instance_guard.consume_show_request():
            self.show_window()
        if self.instance_guard.consume_refresh_request():
            self.refresh_status()
        self.scheduler.after(100, self._poll_show_requests)

    def _apply_status(self, result: dict[str, Any] | Exception) -> None:
        if isinstance(result, Exception) or not result.get("ok"):
            self.connected = False
            self.remote_requests_available = False
            self._update_session_ui()
            self.status_label.configure(
                text="Dịch vụ đang ngoại tuyến - giao diện sẽ tự kết nối lại"
            )
            self.details_label.configure(
                text="Dịch vụ: ngoại tuyến\nChế độ kiểm soát: tắt\nDNS: không lọc"
            )
            self.time_detail_label.configure(text="Không thể đọc chính sách thời gian.")
            self.demo_button.state(["disabled"])
            self.icon.title = "OpenGuard Kids - Dịch vụ ngoại tuyến"
        else:
            data = result["data"]
            control = data.get("time_control", {})
            remote = data.get("remote", {})
            notice_scope = (data.get("active_child_id"), data.get("current_user_since"))
            if notice_scope != getattr(self, "block_notice_scope", None):
                self.block_notice_keys = set()
                self.block_ack_attempts = {}
                self.block_notice_scope = notice_scope
            self.current_user = data.get("current_user")
            self.active_child_id = data.get("active_child_id")
            enrollment = data.get("enrollment", {})
            self._set_pairing_view(
                not enrollment.get("required", False) or enrollment.get("enrolled", False)
            )
            self.profile_login_required = bool(
                data.get("capabilities", {}).get("child_profile_login")
            )
            self.profile_options = {
                item["display_name"]: item["id"] for item in data.get("profiles", [])
            }
            self.remote_requests_available = bool(
                data.get("capabilities", {}).get("remote_parent_requests")
            )
            self._update_session_ui()
            self._update_request_status(data.get("time_requests", []))
            self._update_activity_events(data)
            self._update_activity_report(data.get("activity_report"))
            web_state = {
                "active": "đã cấu hình (mở lại trình duyệt để nhận policy)",
                "inactive": "đang tắt",
                "error": "lỗi cấu hình",
            }.get(data.get("filtering", {}).get("web_protection"), "chưa cấu hình")
            self.connected = True
            mode = control.get("mode", "disabled")
            self.status_label.configure(text=self._status_text(mode, control))
            self.details_label.configure(
                text=(
                    "Dịch vụ: đang chạy\n"
                    f"Máy chủ phụ huynh: {'đã kết nối' if remote.get('connected') else 'ngoại tuyến/chưa ghép'}\n"
                    f"Chế độ kiểm soát: {self._mode_text(mode)}\n"
                    "Ghi nhận: tổng thời gian, nghỉ quá 5 phút và khóa màn hình\n"
                    "Sự kiện: tên ứng dụng/trang web, thời gian và lý do chặn\n"
                    f"Kiểm soát ứng dụng: {'đang bật' if data.get('filtering', {}).get('enabled') else 'đang tắt'}\n"
                    f"DNS proxy: {'đang bật' if data.get('filtering', {}).get('dns_proxy_enabled') else 'đang tắt'}\n"
                    f"DNS trình duyệt: {web_state}\n"
                    f"{data.get('filtering', {}).get('web_protection_error') or ''}\n"
                    f"{data.get('filtering', {}).get('error') or ''}"
                )
            )
            self.icon.title = f"OpenGuard Kids - {self._mode_text(mode)}"
            remaining = control.get("remaining_seconds")
            if remaining is None:
                unlimited = (
                    mode == "disabled"
                    and self.current_user
                    and not control.get("policy_error")
                )
                self.time_label.configure(text="Không giới hạn" if unlimited else "--:--:--")
                self.demo_button.state(["disabled"])
            else:
                self.time_label.configure(text=format_clock(remaining))
                if not self.demo_in_flight and remaining > 0:
                    self.demo_button.state(["!disabled"])
                else:
                    self.demo_button.state(["disabled"])
            if mode == "quota_grace":
                grace = control.get("grace_remaining_seconds", 0)
                detail = f"Đã hết giờ. Em có {grace} giây để lưu công việc."
            elif mode == "quota_exhausted":
                detail = "Đã hết thời gian. Máy sẽ khóa cho đến khi được cấp thêm giờ."
            elif mode == "schedule_blocked":
                detail = "Ngoài lịch cho phép. Máy sẽ khóa cho đến khung giờ được sử dụng."
            elif mode == "remote_lock":
                detail = "Phụ huynh vừa yêu cầu khóa máy từ dashboard."
            elif mode == "idle":
                detail = "Đang tạm dừng đếm vì máy không hoạt động quá 5 phút."
            elif mode == "session_locked":
                detail = "Đang tạm dừng đếm vì màn hình đã khóa."
            elif mode == "inert_no_tray":
                detail = "Việc đếm chỉ hoạt động khi giao diện khay đang hiện diện."
            elif mode == "disabled":
                detail = disabled_time_detail(control)
            elif mode == "awaiting_profile":
                detail = "Hãy đăng nhập bằng PIN để bắt đầu phiên sử dụng máy."
            else:
                used = control.get("used_seconds", 0)
                detail = f"Hôm nay đã dùng {format_used_duration(used)}."
            self.time_detail_label.configure(text=detail)
            audits = data.get("child_audit", [])[:5]
            audit_names = {
                "policy_updated": "Phụ huynh đổi chính sách",
                "enrollment_consent": "Phụ huynh đồng ý ghép thiết bị",
                "emergency_command_created": "Phụ huynh gửi lệnh khẩn",
                "emergency_command_acknowledged": "Agent xác nhận lệnh khẩn",
                "time_requested": "Em đã xin thêm giờ",
                "time_request_decided": "Phụ huynh đã trả lời yêu cầu xin giờ",
            }
            self.audit_label.configure(
                text="\n".join(format_audit_entry(item, audit_names) for item in audits)
                or "Chưa có thay đổi được ghi nhận."
            )
            self._update_policy_ui(data.get("current_policy"))
            self._show_time_notifications(control.get("notifications", []))
            if has_remaining_time(control.get("remaining_seconds")):
                self.completed_lock_attempts.discard("quota_exhausted")
            if control.get("schedule_allowed", True):
                self.completed_lock_attempts.discard("outside_schedule")
            if control.get("lock_required"):
                self._request_workstation_lock(
                    control.get("lock_reason"), control.get("remote_command_id")
                )
        self.icon.update_menu()

    def _update_activity_events(self, data):
        if not hasattr(self, "events_tree"):
            return
        selection = self.events_tree.selection()
        previous_ids = list(self.events_tree.get_children())
        scroll_position = self.events_tree.yview()
        displayed_ids = set()
        items = data.get("activity_events", [])
        next_ids = [item["id"] for item in items]
        obsolete_ids = [id for id in previous_ids if id not in next_ids]
        if obsolete_ids:
            self.events_tree.delete(*obsolete_ids)
        for index, item in enumerate(items):
            event = item["event"]
            explanation = item["explanation"]
            values = (
                datetime.fromtimestamp(event["ts"], tz=UTC)
                .astimezone()
                .strftime("%d/%m/%Y %H:%M:%S"),
                event["subject"],
                explanation["reason"] + " · " + explanation["rule_author"],
            )
            if item["id"] in previous_ids:
                if tuple(self.events_tree.item(item["id"], "values")) != values:
                    self.events_tree.item(item["id"], values=values)
                if previous_ids != next_ids:
                    self.events_tree.move(item["id"], "", index)
            else:
                self.events_tree.insert("", index, iid=item["id"], values=values)
            displayed_ids.add(item["id"])
        if isinstance(scroll_position, tuple) and scroll_position and previous_ids:
            self.events_tree.yview_moveto(scroll_position[0])
        if isinstance(selection, tuple) and selection and selection[0] in displayed_ids:
            if self.events_tree.selection() != selection:
                self.events_tree.selection_set(selection)
        elif hasattr(self, "event_detail"):
            self._set_event_detail("Chọn một sự kiện để xem đầy đủ lý do.")
        notifications = data.get("blocking_notifications", [])
        live_ids = {item["id"] for item in data.get("activity_events", [])} | {
            item["id"] for item in notifications
        }
        if self.block_popup is not None and not (self.block_popup_ids & live_ids):
            self.block_popup.destroy()
            self.block_popup = None
            self.block_popup_ids.clear()
            if hasattr(self, "block_popup_keys"):
                self.block_popup_keys.clear()
        attempts = getattr(self, "block_ack_attempts", {})
        self.block_ack_attempts = attempts
        notification_ids = {item["id"] for item in notifications}
        for event_id in list(attempts):
            if event_id not in notification_ids:
                del attempts[event_id]
        now = time.monotonic()
        fresh_items = []
        fresh_ids = []
        fresh_keys = set()
        duplicate_ids = []
        active_keys = getattr(self, "block_popup_keys", set()) if self.block_popup else set()
        for item in notifications:
            event = item["event"]
            key = (
                getattr(self, "active_child_id", None), event.get("type", ""),
                event["subject"], item["explanation"]["reason"],
            )
            event_id = item["id"]
            if event_id in attempts:
                if now - attempts[event_id] >= 5:
                    duplicate_ids.append(event_id)
                    attempts[event_id] = now
            elif key in active_keys:
                if event_id not in self.block_popup_ids and now - attempts.get(event_id, -10) >= 5:
                    duplicate_ids.append(event_id)
                    attempts[event_id] = now
            else:
                fresh_ids.append(event_id)
                if key not in fresh_keys:
                    fresh_items.append(item)
                    fresh_keys.add(key)
        if duplicate_ids:
            self._send_async("ack_blocking", "ack_blocking_events", {"event_ids": duplicate_ids})
        if not fresh_items or self.block_popup is not None:
            return
        popup = tk.Toplevel(self.root)
        self.block_popup = popup
        self.block_popup_keys = set(fresh_keys)
        ids = fresh_ids
        self.block_popup_ids = set(ids)
        popup.title("OpenGuard Kids · Lý do chặn")
        popup.geometry("520x360")
        popup.attributes("-topmost", True)
        frame = ttk.Frame(popup, padding=20)
        frame.pack(fill="both", expand=True)
        ttk.Label(
            frame,
            text="Ứng dụng hoặc trang web vừa bị chặn",
            font=("Segoe UI", 12, "bold"),
            wraplength=470,
        ).pack(anchor="w")
        text = tk.Text(frame, wrap="word", height=10, borderwidth=0, font=("Segoe UI", 10))
        text.pack(fill="both", expand=True, pady=12)
        for item in fresh_items:
            explanation = item["explanation"]
            text.insert(
                "end",
                f"{item['event']['subject']}\n{explanation['reason']}\nLuật do: {explanation['rule_author']}\n\n",
            )
        text.configure(state="disabled")

        def dismiss():
            self.block_popup = None
            self.block_popup_ids.clear()
            self.block_popup_keys.clear()
            popup.destroy()
            for event_id in ids:
                attempts[event_id] = time.monotonic()
            self._send_async("ack_blocking", "ack_blocking_events", {"event_ids": ids})

        popup.protocol("WM_DELETE_WINDOW", dismiss)
        ttk.Button(frame, text="Em đã hiểu", command=dismiss).pack(anchor="e")

    def _update_activity_report(self, report):
        if not hasattr(self, "activity_summary"):
            return
        if report is None:
            self.activity_summary.configure(text="Đăng nhập để xem hoạt động của em.")
        else:
            self.activity_summary.configure(
                text=f"Ngày {report['end_date']} (giờ Việt Nam)\nThời gian sử dụng: {format_used_duration(report['total_duration_sec'])}. "
                + (
                    "Đây là dữ liệu đã đồng bộ từ các máy của em, giống báo cáo của bố mẹ."
                    if report.get("source") == "synced"
                    else "Đây là hoạt động lưu trên máy này; bố mẹ sẽ thấy sau khi đồng bộ."
                )
            )
            self._check_eye_reminder(report)
        scope = (getattr(self, "active_child_id", None), report.get("end_date") if report else None)
        now = time.monotonic()
        if (
            scope != getattr(self, "_visual_report_scope", None)
            or now - getattr(self, "_visual_report_checked_at", float("-inf"))
            >= self.VISUAL_REPORT_REFRESH_SECONDS
        ):
            self._visual_report_scope = scope
            self._visual_report_checked_at = now
            signature = (
                report.get("source"),
                tuple((item["subject"], item["queries"]) for item in report["top_domains"]),
                tuple(
                    (item["subject"], item["duration_sec"])
                    for item in report.get("top_apps", [])
                ),
                tuple(
                    (period, tuple((item["subject"], item["duration_sec"]) for item in apps))
                    for period, apps in sorted(report.get("app_periods", {}).items())
                ),
            ) if report else None
            if scope != getattr(self, "_visual_report_drawn_scope", None) or signature != getattr(
                self, "_visual_report_signature", None
            ):
                self._today_activity_report = report
                self._visual_report_drawn_scope = scope
                self._visual_report_signature = signature
                self._draw_activity_report()
                self._draw_top_apps()

    def _draw_top_apps(self):
        canvas = self.top_apps_chart
        canvas.delete("all")
        report = self._today_activity_report
        if not report:
            canvas.create_text(0, 8, anchor="nw", text="Đăng nhập để xem ứng dụng.", fill="#4D6864")
            canvas.configure(height=34)
            return
        period = {"1 ngày": "1", "1 tuần": "7", "Toàn thời gian": "90"}[
            self.top_apps_period.get()
        ]
        apps = report.get("app_periods", {}).get(period)
        if apps is None:
            apps = report.get("top_apps", []) if period == "1" else []
        source = (
            "Số liệu đã đồng bộ từ các máy của em."
            if period == "1" and report.get("source") == "synced"
            else "Số liệu ghi nhận trên máy này."
        )
        self.top_apps_source.configure(text=source + " Ứng dụng có thể chạy nền hoặc cùng lúc.")
        width = max(250, canvas.winfo_width())
        if not apps:
            canvas.create_text(0, 8, anchor="nw", text="Chưa có hoạt động ứng dụng trong khoảng này.", fill="#4D6864")
            canvas.configure(height=34)
            return
        maximum = max(item["duration_sec"] for item in apps) or 1
        y = 8
        for item in apps[:10]:
            label = canvas.create_text(
                0, y, anchor="nw", width=width - 8,
                text=f"{item['subject']} · {format_used_duration(item['duration_sec'])}",
                font=("Segoe UI", 10), fill="#173B38",
            )
            y = canvas.bbox(label)[3] + 5
            canvas.create_rectangle(0, y, width - 8, y + 7, fill="#E6F0E9", outline="")
            canvas.create_rectangle(
                0, y, (width - 8) * item["duration_sec"] / maximum, y + 7,
                fill="#327E68", outline="",
            )
            y += 20
        canvas.configure(height=y + 8)

    def _check_eye_reminder(self, report):
        if not getattr(self, "current_user", None):
            return
        key = (self.active_child_id, report["end_date"])
        used = max(0, int(report.get("local_duration_sec", 0)))
        if (
            getattr(self, "_eye_reminder_key", None) != key
            or used < getattr(self, "_eye_reminder_baseline", 0)
        ):
            self._eye_reminder_key = key
            # Existing use must not trigger a notification on login or Tray restart.
            self._eye_reminder_baseline = used
            return
        if used - self._eye_reminder_baseline < 20 * 60:
            return
        self._eye_reminder_baseline = used
        self._show_eye_reminder()

    def _show_eye_reminder(self):
        try:
            self.icon.notify(
                "Hãy nghỉ mắt! Nhìn ra xa khoảng 6 mét trong 20 giây.",
                "OpenGuard Kids",
            )
        except Exception:
            LOGGER.debug("Windows eye-rest notification could not be displayed", exc_info=True)

    def _draw_activity_report(self):
        canvas = self.activity_chart
        canvas.delete("all")
        report = self._today_activity_report
        if not report:
            canvas.configure(height=1)
            return
        width = max(250, canvas.winfo_width())
        y = 8
        for title, items, value_key in [
            ("Trang web máy đã hỏi địa chỉ (số lần)", report["top_domains"], "queries"),
        ]:
            canvas.create_text(
                0, y, anchor="nw", text=title, font=("Segoe UI", 10, "bold"), fill="#173B38"
            )
            y += 28
            if not items:
                canvas.create_text(
                    0,
                    y,
                    anchor="nw",
                    text="Chưa có hoạt động này hôm nay.",
                    font=("Segoe UI", 10),
                    fill="#4D6864",
                )
                y += 30
            maximum = max([item[value_key] for item in items] + [1])
            for item in items:
                value = f"{item[value_key]} lượt hỏi"
                label = canvas.create_text(
                    0,
                    y,
                    anchor="nw",
                    width=width - 8,
                    text=f"{item['subject']} · {value}",
                    font=("Segoe UI", 10),
                    fill="#173B38",
                )
                bounds = canvas.bbox(label)
                y = bounds[3] + 5
                canvas.create_rectangle(0, y, width - 8, y + 7, fill="#E6F0E9", outline="")
                canvas.create_rectangle(
                    0, y, (width - 8) * item[value_key] / maximum, y + 7, fill="#327E68", outline=""
                )
                y += 20
            y += 10
        canvas.create_text(
            0,
            y,
            anchor="nw",
            width=width - 8,
            text="Lượt hỏi địa chỉ web không đồng nghĩa với lượt mở trang. Chương trình không đọc bài viết hay tin nhắn của em.",
            font=("Segoe UI", 10),
            fill="#4D6864",
        )
        canvas.configure(height=canvas.bbox("all")[3] + 8)

    def _update_policy_ui(self, policy: dict[str, Any] | None) -> None:
        if not self.current_user:
            self.policy_summary_label.configure(text="Đăng nhập để xem chính sách của em.")
            self.policy_schedule_label.configure(text="")
            self.audit_label.configure(text="Đăng nhập để xem nhật ký thay đổi.")
            return
        if not policy:
            self.policy_summary_label.configure(
                text="Service chưa đồng bộ chính sách cho hồ sơ này. Hãy kiểm tra kết nối và khởi động lại service nếu vừa cập nhật ứng dụng."
            )
            self.policy_schedule_label.configure(text="")
            return
        self.policy_summary_label.configure(
            text=(
                f"Hồ sơ: {self.current_user}\n"
                f"Trạng thái: {'Đang bật' if policy['enabled'] else 'Đang tắt'}\n"
                f"Ngày thường: {policy['weekday_minutes']} phút/ngày\n"
                f"Cuối tuần: {policy['weekend_minutes']} phút/ngày\n"
                f"Phiên bản: {policy['version']}\n"
                f"Cảnh báo trước khi hết giờ: {', '.join(map(str, policy['warnings_minutes']))} phút\n"
                f"Thời gian lưu công việc: {policy['grace_seconds']} giây\n"
                f"Tạm dừng khi không hoạt động: {policy['idle_threshold_seconds']} giây"
            )
        )
        self.policy_schedule_label.configure(
            text="Lịch sử dụng\n" + format_policy_schedule(policy["schedule"])
        )

    def _update_session_ui(self) -> None:
        if self.current_user and not getattr(self, "switching_profile", False):
            self.session_result.configure(text="")
            self.session_label.configure(text=f"Đã đăng nhập với tư cách {self.current_user}.")
            self.login_fields.pack_forget()
            self.login_button.pack_forget()
            if not self.logout_button.winfo_manager():
                self.logout_button.pack(side="left")
            self.login_button.state(["disabled"])
            self.pin_entry.state(["disabled"])
            self.username_entry.state(["disabled"])
            self.logout_button.state(["!disabled"])
            self.logout_button.configure(
                text="Đổi hồ sơ" if self.profile_login_required else "Kết thúc phiên"
            )
            if self.remote_requests_available:
                self.request_button.state(["!disabled"])
            else:
                self.request_button.state(["disabled"])
        else:
            self.request_result.configure(text="")
            restoring_form = not self.login_fields.winfo_manager()
            self.logout_button.pack_forget()
            if restoring_form:
                self.login_fields.pack(fill="x", before=self.login_actions)
            if not self.login_button.winfo_manager():
                self.login_button.pack(side="left")
            self.pin_entry.state(["!disabled"])
            self.username_entry.state(["!disabled"])
            if restoring_form:
                self.username_entry.delete(0, "end")
                self.pin_entry.delete(0, "end")
                self.session_result.configure(text="")
            self.session_label.configure(
                text=(
                    f"Đang đổi hồ sơ; chính sách của {self.current_user} vẫn áp dụng."
                    if self.current_user
                    else "Đang đồng bộ hồ sơ; nếu chờ lâu, kiểm tra server và PIN trên dashboard."
                    if self.profile_login_required and not self.profile_options
                    else "Nhập tên đăng nhập và PIN 6 chữ số để bắt đầu."
                )
            )
            if not self.session_in_flight and (
                not self.profile_login_required or self.profile_options
            ):
                self.login_button.state(["!disabled"])
            else:
                self.login_button.state(["disabled"])
            self.logout_button.state(["disabled"])
            self.request_button.state(["disabled"])

    def _update_request_status(self, requests: list[dict[str, Any]]) -> None:
        if not self.current_user or not requests:
            return
        latest = requests[-1]
        minutes = latest.get("minutes")
        if not isinstance(minutes, int):
            return
        status = latest.get("status")
        if status == "approved":
            message, color = f"Đã cộng thêm {minutes} phút.", ACCENT
        elif status == "rejected":
            message, color = f"Yêu cầu xin thêm {minutes} phút đã bị từ chối.", WARNING
        elif status == "approved_pending":
            message, color = f"Phụ huynh đã duyệt {minutes} phút; đang cộng thời gian.", MUTED
        elif status == "pending":
            message, color = f"Đã gửi yêu cầu {minutes} phút; đang chờ phụ huynh.", MUTED
        elif status == "retrying":
            message, color = f"Yêu cầu {minutes} phút chưa gửi được; sẽ thử lại.", WARNING
        else:
            message, color = f"Đang gửi yêu cầu {minutes} phút tới phụ huynh.", MUTED
        self.request_result.configure(text=message, foreground=color)

    @staticmethod
    def _mode_text(mode: str) -> str:
        return {
            "active": "đang đếm thời gian",
            "idle": "tạm dừng khi không hoạt động",
            "session_locked": "tạm dừng khi màn hình khóa",
            "quota_grace": "thời gian lưu công việc",
            "quota_exhausted": "đã hết thời gian",
            "schedule_blocked": "ngoài lịch cho phép",
            "remote_lock": "phụ huynh yêu cầu khóa ngay",
            "awaiting_profile": "đang chờ trẻ đăng nhập",
            "awaiting_pairing": "đang chờ ghép đôi",
            "inert_no_tray": "tạm dừng vì thiếu giao diện",
            "disabled": "đang tắt",
            "starting": "đang khởi động",
        }.get(mode, mode)

    def _status_text(self, mode: str, control: dict[str, Any]) -> str:
        if mode == "awaiting_pairing":
            return "Hãy nhập mã ghép đôi để kích hoạt thiết bị"
        if not control.get("configured", True):
            return "Chính sách thời gian có lỗi - tính năng đang tắt an toàn"
        if mode in {"quota_exhausted", "schedule_blocked", "remote_lock"}:
            return "Máy cần được khóa theo chính sách thời gian"
        if mode == "quota_grace":
            return "Đã hết giờ - hãy lưu công việc trước khi máy khóa"
        return f"Đã kết nối - {self._mode_text(mode)}"

    def _show_time_notifications(self, notifications: list[dict[str, Any]]) -> None:
        new_ids: list[str] = []
        for event in notifications:
            event_id = event.get("id")
            if not isinstance(event_id, str) or event_id in self.notified_event_ids:
                continue
            try:
                self.icon.notify(str(event.get("message", "Thông báo thời gian")), "OpenGuard Kids")
                self.notified_event_ids.add(event_id)
                new_ids.append(event_id)
            except Exception:
                LOGGER.debug("Windows notification could not be displayed", exc_info=True)
        if new_ids:
            self._send_async("ack_events", "ack_time_events", {"event_ids": new_ids})

    def _request_workstation_lock(self, reason: Any, command_id: Any = None) -> None:
        if reason not in {"quota_exhausted", "outside_schedule", "remote_lock"}:
            return
        key = f"remote_lock:{command_id}" if reason == "remote_lock" else reason
        if reason == "remote_lock" and key in self.completed_lock_attempts:
            return
        now = time.monotonic()
        if reason != "remote_lock" and now < getattr(self, "next_policy_lock_attempt", 0):
            return
        if lock_workstation():
            if reason != "remote_lock":
                self.next_policy_lock_attempt = now + 10
            self.completed_lock_attempts.add(key)
            payload = {"reason": reason}
            if reason == "remote_lock":
                payload["command_id"] = command_id
            self._send_async("ack_lock", "ack_lock", payload)
        else:
            LOGGER.warning("Windows rejected the LockWorkStation request")

    def _apply_demo_result(self, result: dict[str, Any] | Exception) -> None:
        self.demo_in_flight = False
        if isinstance(result, Exception) or not result.get("ok"):
            self.demo_result.configure(text="Không giảm được thời gian.", foreground=WARNING)
            if self.connected:
                self.demo_button.state(["!disabled"])
            return
        reduced = result["data"]["reduced_seconds"]
        self.demo_result.configure(
            text=f"Đã giảm {format_clock(reduced)}.",
            foreground=ACCENT,
        )

    def _apply_request_result(self, result: dict[str, Any] | Exception) -> None:
        self.request_in_flight = False
        if self.current_user and self.remote_requests_available:
            self.request_button.state(["!disabled"])
        else:
            self.request_button.state(["disabled"])
        if isinstance(result, PipeUnavailableError):
            self.request_result.configure(
                text="Chưa gửi được vì dịch vụ đang ngoại tuyến. Em có thể thử lại sau.",
                foreground=WARNING,
            )
            return
        if isinstance(result, Exception) or not result.get("ok"):
            self.request_result.configure(
                text="Dịch vụ chưa nhận được yêu cầu. Em có thể thử lại.",
                foreground=WARNING,
            )
            return
        minutes = result["data"]["minutes"]
        self.request_result.configure(
            text=f"Đã nhận yêu cầu {minutes} phút; đang gửi ngay tới dashboard (mất mạng sẽ thử lại).",
            foreground=ACCENT,
        )

    def run(self) -> None:
        wait = threading.Event()
        try:
            # Tk timers can stall after a wall-clock adjustment. Pump UI events
            # without waiting on those timers; application deadlines are monotonic.
            while not self.closing:
                self.root.update()
                if self.closing:
                    break
                self.scheduler.run_due()
                wait.wait(0.02)
        finally:
            self.instance_guard.close()


def main() -> int:
    configure_tray_logging()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--open", action="store_true", help="Open the main window at startup")
    args = parser.parse_args()
    instance_guard = TrayInstanceGuard.acquire()
    if instance_guard is None:
        return 0
    TrayApplication(instance_guard=instance_guard, start_open=args.open).run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
