"""Shared, content-free F3 reporting for server and the child's local view."""

from collections import Counter
from datetime import UTC, date, datetime, time, timedelta, timezone

REPORT_ZONE = timezone(timedelta(hours=7))
SESSION_SUBJECT = "OpenGuard Kids - Phiên máy tính"
REPORT_HIDDEN_APPS = frozenset(
    {
        "apmsgfwd.exe",
        "apntex.exe",
        "apoint.exe",
        "applicationframehost.exe",
        "conhost.exe",
        "codex.exe",
        "csrss.exe",
        "defendersessionhelper.exe",
        "dptf_helper.exe",
        "dllhost.exe",
        "dwm.exe",
        "fontdrvhost.exe",
        "igfxem.exe",
        "hidfind.exe",
        "logonui.exe",
        "msedgewebview2.exe",
        "node_repl.exe",
        "onedrive.sync.service.exe",
        "openconsole.exe",
        "pythonw.exe",
        "rundll32.exe",
        "runtimebroker.exe",
        "searchapp.exe",
        "searchhost.exe",
        "securityhealthsystray.exe",
        "sihost.exe",
        "smartscreen.exe",
        "startmenuexperiencehost.exe",
        "svchost.exe",
        "taskhostw.exe",
        "textinputhost.exe",
        "userinit.exe",
        "useroobebroker.exe",
        "vmware-tray.exe",
        "winlogon.exe",
    }
)


def _merge_intervals(intervals):
    merged = []
    for left, right in sorted(intervals):
        if right <= left:
            continue
        if merged and left <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], right))
        else:
            merged.append((left, right))
    return merged


def _intersect_intervals(intervals, windows):
    intervals = _merge_intervals(intervals)
    windows = _merge_intervals(windows)
    intersections = []
    interval_index = window_index = 0
    while interval_index < len(intervals) and window_index < len(windows):
        left, right = intervals[interval_index]
        window_left, window_right = windows[window_index]
        start, stop = max(left, window_left), min(right, window_right)
        if stop > start:
            intersections.append((start, stop))
        if right <= window_right:
            interval_index += 1
        else:
            window_index += 1
    return intersections


def report_bounds(end_date=None, days=28, now=None):
    end = (
        date.fromisoformat(end_date)
        if end_date
        else datetime.fromtimestamp(
            now if now is not None else datetime.now(UTC).timestamp(), REPORT_ZONE
        ).date()
    )
    if not 1 <= days <= 90:
        raise ValueError("Report length must be between 1 and 90 days")
    start = end - timedelta(days=days - 1)
    return (
        start,
        end,
        datetime.combine(start, time.min, REPORT_ZONE).timestamp(),
        datetime.combine(end + timedelta(days=1), time.min, REPORT_ZONE).timestamp(),
    )


def activity_report(events, *, end_date=None, days=28, now=None):
    start, end, lower, upper = report_bounds(end_date, days, now)
    daily = {start + timedelta(days=i): 0.0 for i in range(days)}
    app_starts, domains, types = Counter(), Counter(), Counter()
    app_intervals = {}
    session_intervals = []
    blocked = 0
    for event in events:
        ts, kind, subject = event["ts"], event["type"], event["subject"]
        in_range = lower <= ts < upper
        if in_range:
            types[kind] += 1
            blocked += kind in {"blocked_app", "blocked_domain"}
            if kind == "domain_query":
                domains[subject] += 1
            if (
                kind == "app_start"
                and subject != SESSION_SUBJECT
                and subject.casefold() not in REPORT_HIDDEN_APPS
            ):
                app_starts[subject] += 1
        if kind != "app_stop":
            continue
        # Duration describes the interval immediately preceding this event.
        left, right = max(lower, ts - event["duration_sec"]), min(upper, ts)
        if right <= left:
            continue
        if subject == SESSION_SUBJECT:
            session_intervals.append((left, right))
        elif subject.casefold() not in REPORT_HIDDEN_APPS:
            app_intervals.setdefault(subject, []).append((left, right))

    session_intervals = _merge_intervals(session_intervals)
    for left, right in session_intervals:
        while left < right:
            day = datetime.fromtimestamp(left, REPORT_ZONE).date()
            midnight = datetime.combine(day + timedelta(days=1), time.min, REPORT_ZONE).timestamp()
            stop = min(right, midnight)
            daily[day] += stop - left
            left = stop
    app_seconds = Counter()
    for subject, intervals in app_intervals.items():
        # Browsers and desktop apps often own many worker processes. Merge their
        # overlapping intervals and, when session data exists, count only time
        # during which the child's monitored computer session was active.
        active = (
            _intersect_intervals(intervals, session_intervals)
            if session_intervals
            else _merge_intervals(intervals)
        )
        app_seconds[subject] = sum(right - left for left, right in active)
    weekly = Counter()
    for day, seconds in daily.items():
        weekly[day - timedelta(days=day.weekday())] += seconds
    apps = sorted(
        set(app_seconds) | set(app_starts),
        key=lambda name: (-app_seconds[name], -app_starts[name], name),
    )[:10]
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "timezone": "Asia/Ho_Chi_Minh",
        "total_duration_sec": round(sum(daily.values())),
        "blocked_count": blocked,
        "daily": [
            {"date": day.isoformat(), "duration_sec": round(value)} for day, value in daily.items()
        ],
        "weekly": [
            {"week_start": day.isoformat(), "duration_sec": round(value)}
            for day, value in sorted(weekly.items())
        ],
        "top_apps": [
            {"subject": name, "duration_sec": round(app_seconds[name]), "starts": app_starts[name]}
            for name in apps
        ],
        "top_domains": [
            {"subject": name, "queries": count}
            for name, count in sorted(domains.items(), key=lambda item: (-item[1], item[0]))[:10]
        ],
        "event_counts": dict(types),
    }
