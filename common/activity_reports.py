"""Shared, content-free F3 reporting for server and the child's local view."""

from collections import Counter
from datetime import UTC, date, datetime, time, timedelta, timezone

REPORT_ZONE = timezone(timedelta(hours=7))
SESSION_SUBJECT = "OpenGuard Kids - Phiên máy tính"


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
    app_seconds, app_starts, domains, types = Counter(), Counter(), Counter(), Counter()
    blocked = 0
    for event in events:
        ts, kind, subject = event["ts"], event["type"], event["subject"]
        in_range = lower <= ts < upper
        if in_range:
            types[kind] += 1
            blocked += kind in {"blocked_app", "blocked_domain"}
            if kind == "domain_query":
                domains[subject] += 1
            if kind == "app_start" and subject != SESSION_SUBJECT:
                app_starts[subject] += 1
        if kind != "app_stop":
            continue
        # Duration describes the interval immediately preceding this event.
        left, right = max(lower, ts - event["duration_sec"]), min(upper, ts)
        if right <= left:
            continue
        if subject != SESSION_SUBJECT:
            app_seconds[subject] += right - left
            continue
        while left < right:
            day = datetime.fromtimestamp(left, REPORT_ZONE).date()
            midnight = datetime.combine(day + timedelta(days=1), time.min, REPORT_ZONE).timestamp()
            stop = min(right, midnight)
            daily[day] += stop - left
            left = stop
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
