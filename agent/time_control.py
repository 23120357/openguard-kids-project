"""F1 screen-time policy, persistence, and deterministic enforcement state."""

from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

SLOTS_PER_DAY = 48
DAYS_PER_WEEK = 7
ALL_ALLOWED_DAY = "1" * SLOTS_PER_DAY
MAX_SAMPLE_GAP_SECONDS = 5.0
CLOCK_ROLLBACK_TOLERANCE_SECONDS = 120.0
EVENT_RETENTION_SECONDS = 90 * 86400


def recorded_at(timestamp: float) -> str:
    """Return a stable, sortable UTC date-time for persisted records."""

    return (
        datetime.fromtimestamp(timestamp, UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
    )


class PolicyError(ValueError):
    """Raised when an F1 policy file is unsafe or malformed."""


@dataclass(frozen=True)
class TimePolicy:
    version: int
    enabled: bool
    weekday_minutes: int
    weekend_minutes: int
    schedule: tuple[str, ...]
    warnings_minutes: tuple[int, ...] = (10, 5, 1)
    grace_seconds: int = 60
    idle_threshold_seconds: int = 300

    @classmethod
    def disabled(cls, *, version: int = 0) -> TimePolicy:
        return cls(
            version=version,
            enabled=False,
            weekday_minutes=90,
            weekend_minutes=120,
            schedule=(ALL_ALLOWED_DAY,) * DAYS_PER_WEEK,
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> TimePolicy:
        allowed = {
            "version",
            "enabled",
            "weekday_minutes",
            "weekend_minutes",
            "schedule",
            "warnings_minutes",
            "grace_seconds",
            "idle_threshold_seconds",
        }
        unknown = set(value) - allowed
        if unknown:
            raise PolicyError(f"Unknown policy fields: {', '.join(sorted(unknown))}")

        version = _plain_int(value.get("version"), "version", minimum=1)
        enabled = value.get("enabled")
        if not isinstance(enabled, bool):
            raise PolicyError("enabled must be a boolean")
        weekday = _plain_int(
            value.get("weekday_minutes"), "weekday_minutes", minimum=1, maximum=1440
        )
        weekend = _plain_int(
            value.get("weekend_minutes"), "weekend_minutes", minimum=1, maximum=1440
        )

        schedule_value = value.get("schedule")
        if not isinstance(schedule_value, list) or len(schedule_value) != DAYS_PER_WEEK:
            raise PolicyError("schedule must contain seven Monday-to-Sunday rows")
        schedule: list[str] = []
        for index, row in enumerate(schedule_value):
            if not isinstance(row, str) or len(row) != SLOTS_PER_DAY or set(row) - {"0", "1"}:
                raise PolicyError(f"schedule row {index} must contain exactly 48 zero/one slots")
            schedule.append(row)

        warnings_value = value.get("warnings_minutes", [10, 5, 1])
        if not isinstance(warnings_value, list) or not warnings_value:
            raise PolicyError("warnings_minutes must be a non-empty list")
        warnings = tuple(
            _plain_int(item, "warning minute", minimum=1, maximum=1439) for item in warnings_value
        )
        if tuple(sorted(set(warnings), reverse=True)) != warnings:
            raise PolicyError("warnings_minutes must be unique and descending")

        grace = _plain_int(value.get("grace_seconds", 60), "grace_seconds", minimum=0, maximum=600)
        idle = _plain_int(
            value.get("idle_threshold_seconds", 300),
            "idle_threshold_seconds",
            minimum=60,
            maximum=3600,
        )
        return cls(
            version=version,
            enabled=enabled,
            weekday_minutes=weekday,
            weekend_minutes=weekend,
            schedule=tuple(schedule),
            warnings_minutes=warnings,
            grace_seconds=grace,
            idle_threshold_seconds=idle,
        )

    def quota_seconds(self, moment: datetime) -> int:
        minutes = self.weekend_minutes if moment.weekday() >= 5 else self.weekday_minutes
        return minutes * 60

    def schedule_allows(self, moment: datetime) -> bool:
        slot = moment.hour * 2 + (1 if moment.minute >= 30 else 0)
        return self.schedule[moment.weekday()][slot] == "1"


def load_time_policy(path: str | Path) -> TimePolicy:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise PolicyError(f"Policy file not found: {path}") from exc
    except (OSError, json.JSONDecodeError) as exc:
        raise PolicyError(f"Policy file could not be read: {path}") from exc
    if not isinstance(value, dict):
        raise PolicyError("Policy must be a JSON object")
    return TimePolicy.from_dict(value)


def _plain_int(value: Any, name: str, *, minimum: int, maximum: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise PolicyError(f"{name} must be an integer")
    if value < minimum or (maximum is not None and value > maximum):
        suffix = f" and {maximum}" if maximum is not None else ""
        raise PolicyError(f"{name} must be between {minimum}{suffix}")
    return value


@dataclass
class F1State:
    local_date: str | None = None
    used_seconds: float = 0.0
    total_used_seconds: float | None = None
    extra_seconds: float = 0.0
    trusted_wall_time: float | None = None
    grace_deadline_wall: float | None = None
    warned_minutes: list[int] = field(default_factory=list)
    last_mode: str = "disabled"
    clock_tamper_active: bool = False
    policy_version: int = 0
    completed_lock_reasons: list[str] = field(default_factory=list)
    applied_time_command_ids: list[str] = field(default_factory=list)
    recorded_at: str | None = None

    @classmethod
    def from_dict(cls, value: dict[str, Any] | None) -> F1State:
        if not value:
            return cls()
        used = max(0.0, float(value.get("used_seconds", 0.0)))
        total = value.get("total_used_seconds")
        return cls(
            local_date=value.get("local_date"),
            used_seconds=used,
            total_used_seconds=max(used, float(total)) if total is not None else used,
            extra_seconds=max(0.0, float(value.get("extra_seconds", 0.0))),
            trusted_wall_time=value.get("trusted_wall_time"),
            grace_deadline_wall=value.get("grace_deadline_wall"),
            warned_minutes=[int(item) for item in value.get("warned_minutes", [])],
            last_mode=str(value.get("last_mode", "disabled")),
            clock_tamper_active=bool(value.get("clock_tamper_active", False)),
            policy_version=int(value.get("policy_version", 0)),
            completed_lock_reasons=[
                str(item)
                for item in value.get("completed_lock_reasons", [])
                if item in {"quota_exhausted", "outside_schedule"}
            ],
            applied_time_command_ids=[
                str(item)
                for item in value.get("applied_time_command_ids", [])
                if isinstance(item, str) and item
            ][-1000:],
            recorded_at=str(value["recorded_at"]) if value.get("recorded_at") else None,
        )


class TimeStore(Protocol):
    def load_state(self) -> F1State: ...

    def save_state(self, state: F1State) -> None: ...

    def add_event(
        self, event_type: str, ts: float, message: str, details: dict[str, Any]
    ) -> dict[str, Any]: ...

    def pending_events(self, *, limit: int = 20) -> list[dict[str, Any]]: ...

    def acknowledge_events(self, event_ids: list[str]) -> None: ...

    def recent_events(self, *, limit: int = 100) -> list[dict[str, Any]]: ...


class MemoryTimeStore:
    def __init__(self):
        self.state = F1State()
        self.events: list[dict[str, Any]] = []

    def load_state(self) -> F1State:
        return F1State.from_dict(asdict(self.state))

    def save_state(self, state: F1State) -> None:
        self.state = F1State.from_dict(asdict(state))

    def add_event(
        self, event_type: str, ts: float, message: str, details: dict[str, Any]
    ) -> dict[str, Any]:
        event = {
            "id": str(uuid.uuid4()),
            "ts": ts,
            "recorded_at": recorded_at(ts),
            "type": event_type,
            "message": message,
            "details": details,
            "acknowledged": False,
        }
        self.events.append(event)
        return dict(event)

    def pending_events(self, *, limit: int = 20) -> list[dict[str, Any]]:
        return [dict(event) for event in self.events if not event["acknowledged"]][:limit]

    def acknowledge_events(self, event_ids: list[str]) -> None:
        wanted = set(event_ids)
        for event in self.events:
            if event["id"] in wanted:
                event["acknowledged"] = True

    def recent_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        return [dict(event) for event in reversed(self.events[-limit:])]


class SQLiteTimeStore:
    """Small local F1 store. The containing directory must have a SYSTEM/Admin ACL."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        with self._connect() as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS f1_state ("
                "id INTEGER PRIMARY KEY CHECK(id = 1), value TEXT NOT NULL)"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS f1_events ("
                "id TEXT PRIMARY KEY, ts REAL NOT NULL, type TEXT NOT NULL, "
                "message TEXT NOT NULL, details TEXT NOT NULL, acknowledged INTEGER NOT NULL, "
                "recorded_at TEXT NOT NULL)"
            )
            columns = {row[1] for row in db.execute("PRAGMA table_info(f1_events)")}
            if "recorded_at" not in columns:
                db.execute("ALTER TABLE f1_events ADD COLUMN recorded_at TEXT")
                db.execute(
                    "UPDATE f1_events SET recorded_at = "
                    "strftime('%Y-%m-%dT%H:%M:%SZ', ts, 'unixepoch') "
                    "WHERE recorded_at IS NULL"
                )

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.execute("PRAGMA journal_mode=WAL")
        return db

    def load_state(self) -> F1State:
        with self._lock, self._connect() as db:
            row = db.execute("SELECT value FROM f1_state WHERE id = 1").fetchone()
        return F1State.from_dict(json.loads(row[0]) if row else None)

    def save_state(self, state: F1State) -> None:
        value = json.dumps(asdict(state), separators=(",", ":"), allow_nan=False)
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO f1_state(id, value) VALUES (1, ?) "
                "ON CONFLICT(id) DO UPDATE SET value = excluded.value",
                (value,),
            )

    def add_event(
        self, event_type: str, ts: float, message: str, details: dict[str, Any]
    ) -> dict[str, Any]:
        event = {
            "id": str(uuid.uuid4()),
            "ts": ts,
            "recorded_at": recorded_at(ts),
            "type": event_type,
            "message": message,
            "details": details,
            "acknowledged": False,
        }
        details_json = json.dumps(details, separators=(",", ":"), allow_nan=False)
        with self._lock, self._connect() as db:
            db.execute(
                "INSERT INTO f1_events("
                "id, ts, type, message, details, acknowledged, recorded_at"
                ") VALUES (?, ?, ?, ?, ?, 0, ?)",
                (event["id"], ts, event_type, message, details_json, event["recorded_at"]),
            )
            db.execute("DELETE FROM f1_events WHERE ts < ?", (ts - EVENT_RETENTION_SECONDS,))
        return event

    def pending_events(self, *, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT id, ts, recorded_at, type, message, details FROM f1_events "
                "WHERE acknowledged = 0 ORDER BY ts, id LIMIT ?",
                (limit,),
            ).fetchall()
        return [_event_row(row, False) for row in rows]

    def acknowledge_events(self, event_ids: list[str]) -> None:
        if not event_ids:
            return
        placeholders = ",".join("?" for _ in event_ids)
        with self._lock, self._connect() as db:
            db.execute(
                f"UPDATE f1_events SET acknowledged = 1 WHERE id IN ({placeholders})",
                event_ids,
            )

    def recent_events(self, *, limit: int = 100) -> list[dict[str, Any]]:
        with self._lock, self._connect() as db:
            rows = db.execute(
                "SELECT id, ts, recorded_at, type, message, details, acknowledged FROM f1_events "
                "ORDER BY ts DESC, id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [_event_row(row[:6], bool(row[6])) for row in rows]


def _event_row(row: tuple[Any, ...], acknowledged: bool) -> dict[str, Any]:
    return {
        "id": row[0],
        "ts": row[1],
        "recorded_at": row[2],
        "type": row[3],
        "message": row[4],
        "details": json.loads(row[5]),
        "acknowledged": acknowledged,
    }


class F1Controller:
    """Monotonic F1 state machine driven by visible Tray heartbeats."""

    def __init__(
        self,
        policy: TimePolicy,
        store: TimeStore,
        *,
        monotonic_clock=time.monotonic,
        wall_clock=time.time,
        to_local_datetime=lambda value: datetime.fromtimestamp(value).astimezone(),
        policy_error: str | None = None,
        reset_on_policy_version_change: bool = False,
    ):
        self.policy = policy
        self.store = store
        self._monotonic_clock = monotonic_clock
        self._wall_clock = wall_clock
        self._to_local_datetime = to_local_datetime
        self._last_monotonic = monotonic_clock()
        self._state = store.load_state()
        self._policy_error = policy_error
        self._reset_on_policy_version_change = reset_on_policy_version_change
        self._lock = threading.RLock()
        initial_state = asdict(self._state)
        wall_now = wall_clock()
        logical_wall = max(self._state.trusted_wall_time or wall_now, wall_now)
        moment = self._to_local_datetime(logical_wall)
        if self._policy_error is None:
            self._roll_date(moment.date().isoformat())
            self._reset_for_policy_version(moment)
        if asdict(self._state) != initial_state:
            self._state.trusted_wall_time = logical_wall
            self._save_state(logical_wall)
        self._last_snapshot = self._base_snapshot("disabled" if not policy.enabled else "starting")

    @property
    def enabled(self) -> bool:
        return self.policy.enabled

    def reset_tick_baseline(self) -> None:
        """Do not charge the elapsed time while another profile was active."""
        with self._lock:
            self._last_monotonic = self._monotonic_clock()

    def _base_snapshot(self, mode: str) -> dict[str, Any]:
        return {
            "configured": self._policy_error is None,
            "policy_error": self._policy_error,
            "enabled": self.policy.enabled,
            "policy_version": self.policy.version,
            "mode": mode,
            "active_usage": False,
            "schedule_allowed": True,
            "used_seconds": int(self._state.total_used_seconds or 0),
            "extra_seconds": int(self._state.extra_seconds),
            "quota_seconds": None,
            "remaining_seconds": None,
            "remaining_minutes": None,
            "grace_remaining_seconds": 0,
            "idle_seconds": 0,
            "session_locked": False,
            "lock_required": False,
            "lock_reason": None,
            "lock_completed": False,
            "clock_tamper_detected": self._state.clock_tamper_active,
            "notifications": self.store.pending_events(),
        }

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            result = dict(self._last_snapshot)
            result["notifications"] = self.store.pending_events()
            return result

    def acknowledge_events(self, event_ids: list[str]) -> None:
        self.store.acknowledge_events(event_ids)

    def acknowledge_lock(self, reason: str) -> None:
        if reason not in {"quota_exhausted", "outside_schedule"}:
            raise ValueError("Unsupported lock reason")
        with self._lock:
            if reason not in self._state.completed_lock_reasons:
                self._state.completed_lock_reasons.append(reason)
                self._save_state(self._state.trusted_wall_time or self._wall_clock())

    def replace_policy(self, policy: TimePolicy) -> None:
        """Apply a remote policy immediately while preserving today's usage."""

        with self._lock:
            self.policy = policy
            self._policy_error = None
            logical_wall = max(self._state.trusted_wall_time or 0, self._wall_clock())
            moment = self._to_local_datetime(logical_wall)
            self._roll_date(moment.date().isoformat())
            self._state.policy_version = policy.version
            self._state.local_date = moment.date().isoformat()
            if self._reset_on_policy_version_change:
                self._state.total_used_seconds = 0.0
            self._state.used_seconds = float(self._state.total_used_seconds or 0)
            self._state.extra_seconds = 0.0
            self._state.warned_minutes.clear()
            self._state.grace_deadline_wall = None
            self._state.completed_lock_reasons.clear()
            self._last_monotonic = self._monotonic_clock()
            self._last_snapshot = self._base_snapshot(
                "disabled" if not policy.enabled else "starting"
            )
            quota = policy.quota_seconds(moment)
            remaining = max(0.0, quota - self._state.used_seconds)
            self._last_snapshot.update(
                {
                    "quota_seconds": quota if policy.enabled else None,
                    "remaining_seconds": math.ceil(remaining) if policy.enabled else None,
                    "remaining_minutes": math.ceil(remaining / 60) if policy.enabled else None,
                }
            )
            self._save_state(logical_wall)

    def grant_extra_time(self, minutes: int, *, command_id: str) -> int:
        """Add a separate today-only allowance that bypasses quota and schedule."""

        if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 120:
            raise ValueError("minutes must be an integer between 1 and 120")
        with self._lock:
            if command_id in self._state.applied_time_command_ids:
                return 0
            logical_wall = self._state.trusted_wall_time or self._wall_clock()
            granted = minutes * 60
            self._state.extra_seconds += granted
            if self._last_snapshot.get("remaining_seconds") is not None:
                self._last_snapshot["remaining_seconds"] += granted
                self._last_snapshot["remaining_minutes"] = math.ceil(
                    self._last_snapshot["remaining_seconds"] / 60
                )
                self._last_snapshot["extra_seconds"] = math.ceil(self._state.extra_seconds)
            self._state.applied_time_command_ids.append(command_id)
            del self._state.applied_time_command_ids[:-1000]
            self._state.grace_deadline_wall = None
            self._forget_completed_lock("quota_exhausted")
            self._forget_completed_lock("outside_schedule")
            self.store.add_event(
                "remote_time_added",
                logical_wall,
                f"Phụ huynh đã cộng {minutes} phút từ xa.",
                {
                    "minutes": minutes,
                    "granted_seconds": granted,
                    "command_id": command_id,
                    "policy_version": self.policy.version,
                },
            )
            self._save_state(logical_wall)
            return granted

    def reduce_remaining_for_demo(self, seconds: int) -> int:
        """Consume quota on request from the explicitly visible development UI."""

        if isinstance(seconds, bool) or not isinstance(seconds, int) or not 1 <= seconds <= 3600:
            raise ValueError("seconds must be an integer between 1 and 3600")
        with self._lock:
            if not self.policy.enabled:
                return 0
            logical_wall = self._state.trusted_wall_time or self._wall_clock()
            moment = self._to_local_datetime(logical_wall)
            self._roll_date(moment.date().isoformat())
            self._reset_for_policy_version(moment)
            quota_seconds = self.policy.quota_seconds(moment)
            before = max(0.0, quota_seconds - self._state.used_seconds)
            extra_before = self._state.extra_seconds
            consumed = min(float(seconds), before + extra_before)
            from_quota = min(consumed, before)
            self._state.used_seconds += from_quota
            self._state.extra_seconds = max(0.0, extra_before - (consumed - from_quota))
            self._state.total_used_seconds = float(self._state.total_used_seconds or 0) + consumed
            if consumed:
                self.store.add_event(
                    "demo_time_reduced",
                    logical_wall,
                    f"Chế độ demo đã giảm {int(consumed)} giây còn lại.",
                    {"seconds": int(consumed), "policy_version": self.policy.version},
                )
                self._save_state(logical_wall)
            return int(consumed)

    def tick(
        self,
        *,
        idle_seconds: float,
        session_locked: bool,
        ui_present: bool,
    ) -> dict[str, Any]:
        with self._lock:
            mono_now = self._monotonic_clock()
            wall_now = self._wall_clock()
            raw_delta = max(0.0, mono_now - self._last_monotonic)
            self._last_monotonic = mono_now
            logical_wall, _ = self._trusted_wall_time(wall_now, raw_delta)
            moment = self._to_local_datetime(logical_wall)
            if self._policy_error is None:
                self._roll_date(moment.date().isoformat())
                self._reset_for_policy_version(moment)

            quota_seconds = self.policy.quota_seconds(moment)
            schedule_allowed = self.policy.schedule_allows(moment)
            quota_remaining_before = max(0.0, quota_seconds - self._state.used_seconds)
            remaining_before = (
                quota_remaining_before if schedule_allowed else 0.0
            ) + self._state.extra_seconds
            sample_delta = raw_delta if raw_delta <= MAX_SAMPLE_GAP_SECONDS else 0.0
            active_usage = bool(
                self.policy.enabled
                and ui_present
                and not session_locked
                and idle_seconds < self.policy.idle_threshold_seconds
                and remaining_before > 0
            )
            if active_usage and sample_delta:
                consumed = min(sample_delta, remaining_before)
                remaining_delta = consumed
                if schedule_allowed and quota_remaining_before > 0:
                    from_quota = min(remaining_delta, quota_remaining_before)
                    self._state.used_seconds += from_quota
                    remaining_delta -= from_quota
                if remaining_delta > 0:
                    self._state.extra_seconds = max(
                        0.0, self._state.extra_seconds - remaining_delta
                    )
                self._state.total_used_seconds = (
                    float(self._state.total_used_seconds or 0) + consumed
                )

            quota_remaining = max(0.0, quota_seconds - self._state.used_seconds)
            usable_quota_remaining = quota_remaining if schedule_allowed else 0.0
            remaining = usable_quota_remaining + self._state.extra_seconds
            if remaining > 0:
                self._state.grace_deadline_wall = None
                self._forget_completed_lock("quota_exhausted")
            elif (
                self.policy.enabled and schedule_allowed and self._state.grace_deadline_wall is None
            ):
                self._state.grace_deadline_wall = logical_wall + self.policy.grace_seconds
            if schedule_allowed:
                self._forget_completed_lock("outside_schedule")

            self._record_warnings(remaining, quota_seconds, logical_wall)
            mode, grace_remaining, lock_reason = self._mode(
                ui_present=ui_present,
                session_locked=session_locked,
                idle_seconds=idle_seconds,
                schedule_allowed=schedule_allowed,
                remaining=remaining,
                logical_wall=logical_wall,
            )
            lock_required = bool(
                self.policy.enabled
                and ui_present
                and not session_locked
                and lock_reason is not None
                and lock_reason not in self._state.completed_lock_reasons
            )
            if lock_required and self._state.last_mode != mode:
                self.store.add_event(
                    "locked",
                    logical_wall,
                    "OpenGuard Kids yêu cầu khóa máy theo chính sách thời gian.",
                    {"reason": lock_reason, "policy_version": self.policy.version},
                )

            self._state.last_mode = mode
            self._save_state(logical_wall)
            self._last_snapshot = {
                "configured": self._policy_error is None,
                "policy_error": self._policy_error,
                "enabled": self.policy.enabled,
                "policy_version": self.policy.version,
                "mode": mode,
                "active_usage": active_usage,
                "schedule_allowed": schedule_allowed,
                "used_seconds": int(self._state.total_used_seconds or 0),
                "quota_seconds": quota_seconds if self.policy.enabled else None,
                "remaining_seconds": math.ceil(remaining) if self.policy.enabled else None,
                "extra_seconds": math.ceil(self._state.extra_seconds),
                "remaining_minutes": math.ceil(remaining / 60) if self.policy.enabled else None,
                "grace_remaining_seconds": grace_remaining,
                "idle_seconds": int(idle_seconds),
                "session_locked": session_locked,
                "lock_required": lock_required,
                "lock_reason": lock_reason,
                "lock_completed": bool(
                    lock_reason and lock_reason in self._state.completed_lock_reasons
                ),
                "clock_tamper_detected": self._state.clock_tamper_active,
                "notifications": self.store.pending_events(),
            }
            return dict(self._last_snapshot)

    def _trusted_wall_time(self, wall_now: float, monotonic_delta: float) -> tuple[float, bool]:
        previous = self._state.trusted_wall_time
        if previous is None:
            logical = wall_now
            rollback = False
        else:
            expected = previous + monotonic_delta
            rollback = wall_now + CLOCK_ROLLBACK_TOLERANCE_SECONDS < expected
            logical = expected if rollback else max(previous, wall_now)

        if rollback and not self._state.clock_tamper_active:
            self.store.add_event(
                "clock_tamper",
                logical,
                "Đồng hồ hệ thống đã bị lùi; thời gian sử dụng không được cộng thêm.",
                {
                    "observed_wall_time": wall_now,
                    "trusted_wall_time": logical,
                    "policy_version": self.policy.version,
                },
            )
        self._state.clock_tamper_active = rollback
        self._state.trusted_wall_time = logical
        return logical, rollback

    def _roll_date(self, local_date: str) -> None:
        if self._state.local_date is None or local_date > self._state.local_date:
            self._state.local_date = local_date
            self._state.used_seconds = 0.0
            self._state.total_used_seconds = 0.0
            self._state.extra_seconds = 0.0
            self._state.grace_deadline_wall = None
            self._state.warned_minutes.clear()
            self._state.completed_lock_reasons.clear()

    def _forget_completed_lock(self, reason: str) -> None:
        if reason in self._state.completed_lock_reasons:
            self._state.completed_lock_reasons.remove(reason)

    def _reset_for_policy_version(self, moment: datetime) -> None:
        if self._policy_error is not None:
            return
        if self._state.policy_version != self.policy.version:
            self._state.policy_version = self.policy.version
            self._state.local_date = moment.date().isoformat()
            if self._reset_on_policy_version_change:
                self._state.total_used_seconds = 0.0
            self._state.used_seconds = float(self._state.total_used_seconds or 0)
            self._state.extra_seconds = 0.0
            self._state.warned_minutes.clear()
            self._state.grace_deadline_wall = None
            self._state.completed_lock_reasons.clear()

    def _save_state(self, timestamp: float) -> None:
        self._state.recorded_at = recorded_at(timestamp)
        self.store.save_state(self._state)

    def _record_warnings(self, remaining: float, quota_seconds: int, ts: float) -> None:
        if not self.policy.enabled or remaining <= 0:
            return
        for minutes in self.policy.warnings_minutes:
            threshold = minutes * 60
            if threshold >= quota_seconds or minutes in self._state.warned_minutes:
                continue
            if remaining <= threshold:
                self._state.warned_minutes.append(minutes)
                self.store.add_event(
                    "quota_warning",
                    ts,
                    f"Em còn {minutes} phút sử dụng máy hôm nay.",
                    {"remaining_minutes": minutes, "policy_version": self.policy.version},
                )

    def _mode(
        self,
        *,
        ui_present: bool,
        session_locked: bool,
        idle_seconds: float,
        schedule_allowed: bool,
        remaining: float,
        logical_wall: float,
    ) -> tuple[str, int, str | None]:
        if not self.policy.enabled:
            return "disabled", 0, None
        if not ui_present:
            return "inert_no_tray", 0, None
        if not schedule_allowed and self._state.extra_seconds <= 0:
            return "schedule_blocked", 0, "outside_schedule"
        if remaining <= 0:
            deadline = self._state.grace_deadline_wall or logical_wall
            grace_remaining = max(0, math.ceil(deadline - logical_wall))
            if grace_remaining:
                return "quota_grace", grace_remaining, None
            return "quota_exhausted", 0, "quota_exhausted"
        if session_locked:
            return "session_locked", 0, None
        if idle_seconds >= self.policy.idle_threshold_seconds:
            return "idle", 0, None
        return "active", 0, None
