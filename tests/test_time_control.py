import json
import sqlite3
from datetime import UTC, datetime

import pytest

from agent.time_control import (
    ALL_ALLOWED_DAY,
    F1Controller,
    F1State,
    MemoryTimeStore,
    PolicyError,
    SQLiteTimeStore,
    TimePolicy,
    load_time_policy,
)


class SimulatedTime:
    def __init__(self, wall: float | None = None):
        self.monotonic = 0.0
        self.wall = wall or datetime(2026, 9, 28, 9, tzinfo=UTC).timestamp()

    def mono(self) -> float:
        return self.monotonic

    def current_wall(self) -> float:
        return self.wall

    def advance(self, seconds: float) -> None:
        self.monotonic += seconds
        self.wall += seconds


def policy(**overrides) -> TimePolicy:
    values = {
        "version": 1,
        "enabled": True,
        "weekday_minutes": 90,
        "weekend_minutes": 120,
        "schedule": (ALL_ALLOWED_DAY,) * 7,
        "warnings_minutes": (10, 5, 1),
        "grace_seconds": 60,
        "idle_threshold_seconds": 300,
    }
    values.update(overrides)
    return TimePolicy(**values)


def controller(
    selected_policy: TimePolicy | None = None,
    *,
    simulated: SimulatedTime | None = None,
    store=None,
) -> tuple[F1Controller, SimulatedTime, MemoryTimeStore | SQLiteTimeStore]:
    simulated = simulated or SimulatedTime()
    store = store or MemoryTimeStore()
    instance = F1Controller(
        selected_policy or policy(),
        store,
        monotonic_clock=simulated.mono,
        wall_clock=simulated.current_wall,
        to_local_datetime=lambda value: datetime.fromtimestamp(value, UTC),
    )
    return instance, simulated, store


def heartbeat(instance: F1Controller, *, idle=0, locked=False, present=True):
    return instance.tick(idle_seconds=idle, session_locked=locked, ui_present=present)


def advance_heartbeats(instance: F1Controller, simulated: SimulatedTime, seconds: int):
    result = heartbeat(instance)
    for _ in range(seconds):
        simulated.advance(1)
        result = heartbeat(instance)
    return result


def test_policy_schema_requires_seven_48_slot_rows():
    valid = {
        "version": 1,
        "enabled": True,
        "weekday_minutes": 90,
        "weekend_minutes": 120,
        "schedule": [ALL_ALLOWED_DAY] * 7,
    }
    assert TimePolicy.from_dict(valid).schedule[0] == ALL_ALLOWED_DAY

    with pytest.raises(PolicyError):
        TimePolicy.from_dict({**valid, "schedule": [ALL_ALLOWED_DAY] * 6})
    with pytest.raises(PolicyError):
        TimePolicy.from_dict({**valid, "schedule": ["1" * 47] * 7})


def test_policy_loader_accepts_windows_utf8_bom(tmp_path):
    path = tmp_path / "policy.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "enabled": True,
                "weekday_minutes": 90,
                "weekend_minutes": 120,
                "schedule": [ALL_ALLOWED_DAY] * 7,
            }
        ),
        encoding="utf-8-sig",
    )
    assert load_time_policy(path).enabled is True


def test_weekday_and_weekend_have_separate_quotas():
    selected = policy(weekday_minutes=15, weekend_minutes=45)
    monday = datetime(2026, 9, 28, 9, tzinfo=UTC)
    saturday = datetime(2026, 10, 3, 9, tzinfo=UTC)
    assert selected.quota_seconds(monday) == 15 * 60
    assert selected.quota_seconds(saturday) == 45 * 60


def test_schedule_uses_monday_to_sunday_half_hour_slots():
    rows = ["0" * 48 for _ in range(7)]
    monday_0930_slot = 19
    rows[0] = rows[0][:monday_0930_slot] + "1" + rows[0][monday_0930_slot + 1 :]
    selected = policy(schedule=tuple(rows))
    assert selected.schedule_allows(datetime(2026, 9, 28, 9, 30, tzinfo=UTC))
    assert not selected.schedule_allows(datetime(2026, 9, 28, 9, 29, tzinfo=UTC))


def test_outside_schedule_requests_lock_on_first_heartbeat():
    instance, _, store = controller(policy(schedule=("0" * 48,) * 7))
    result = heartbeat(instance)
    assert result["mode"] == "schedule_blocked"
    assert result["lock_required"] is True
    assert result["lock_reason"] == "outside_schedule"
    assert any(event["type"] == "locked" for event in store.events)


def test_active_use_accuracy_is_within_one_second_per_hour():
    instance, simulated, _ = controller(policy(weekday_minutes=120))
    result = advance_heartbeats(instance, simulated, 3600)
    assert abs(result["used_seconds"] - 3600) <= 1


@pytest.mark.parametrize(
    ("idle", "locked", "present", "expected_mode"),
    [
        (300, False, True, "idle"),
        (0, True, True, "session_locked"),
        (0, False, False, "inert_no_tray"),
    ],
)
def test_inactive_states_do_not_consume_quota(idle, locked, present, expected_mode):
    instance, simulated, _ = controller()
    heartbeat(instance, idle=idle, locked=locked, present=present)
    simulated.advance(5)
    result = heartbeat(instance, idle=idle, locked=locked, present=present)
    assert result["used_seconds"] == 0
    assert result["mode"] == expected_mode


def test_large_heartbeat_gap_does_not_count_sleep_or_tray_absence():
    instance, simulated, _ = controller()
    heartbeat(instance)
    simulated.advance(30)
    result = heartbeat(instance)
    assert result["used_seconds"] == 0


def test_warning_events_are_emitted_once_at_10_5_and_1_minutes():
    instance, simulated, store = controller(policy(weekday_minutes=11))
    advance_heartbeats(instance, simulated, 10 * 60)
    warning_values = [
        event["details"]["remaining_minutes"]
        for event in store.events
        if event["type"] == "quota_warning"
    ]
    assert warning_values == [10, 5, 1]
    heartbeat(instance)
    assert len([event for event in store.events if event["type"] == "quota_warning"]) == 3


def test_quota_has_60_second_grace_then_requires_lock():
    instance, simulated, _ = controller(policy(weekday_minutes=1, warnings_minutes=(1,)))
    result = advance_heartbeats(instance, simulated, 60)
    assert result["mode"] == "quota_grace"
    assert result["grace_remaining_seconds"] == 60
    assert result["lock_required"] is False

    simulated.advance(59)
    result = heartbeat(instance)
    assert result["mode"] == "quota_grace"
    simulated.advance(1)
    result = heartbeat(instance)
    assert result["mode"] == "quota_exhausted"
    assert result["lock_required"] is True


def test_acknowledged_quota_lock_is_not_repeated_after_unlock():
    instance, simulated, _ = controller(
        policy(weekday_minutes=1, warnings_minutes=(1,), grace_seconds=0)
    )
    result = advance_heartbeats(instance, simulated, 60)
    assert result["lock_required"] is True

    instance.acknowledge_lock("quota_exhausted")
    result = heartbeat(instance, locked=True)
    assert result["lock_required"] is False
    result = heartbeat(instance, locked=False)
    assert result["mode"] == "quota_exhausted"
    assert result["lock_required"] is False
    assert result["lock_completed"] is True


def test_demo_control_reduces_remaining_time_and_records_event():
    instance, _, store = controller(policy(weekday_minutes=3))
    heartbeat(instance)
    assert instance.reduce_remaining_for_demo(60) == 60
    result = heartbeat(instance)
    assert result["remaining_seconds"] == 120
    assert any(event["type"] == "demo_time_reduced" for event in store.events)


def test_timer_tracks_elapsed_monotonic_time_without_charging_status_reads():
    instance, simulated, _ = controller(policy(weekday_minutes=3))
    assert heartbeat(instance)["remaining_seconds"] == 180
    for _ in range(20):
        assert instance.snapshot()["remaining_seconds"] == 180
    simulated.advance(1.25)
    assert heartbeat(instance)["remaining_seconds"] == 179
    for _ in range(20):
        assert instance.snapshot()["remaining_seconds"] == 179
    simulated.advance(0.75)
    assert heartbeat(instance)["remaining_seconds"] == 178


def test_demo_control_cannot_reduce_below_zero():
    instance, _, _ = controller(policy(weekday_minutes=1))
    heartbeat(instance)
    assert instance.reduce_remaining_for_demo(3600) == 60
    assert instance.reduce_remaining_for_demo(60) == 0


def test_new_policy_version_preserves_today_usage_and_recalculates_remaining():
    store = MemoryTimeStore()
    store.state = F1State(
        local_date="2026-09-28",
        used_seconds=220,
        policy_version=1,
    )
    instance, _, _ = controller(policy(version=2, weekday_minutes=11), store=store)
    assert store.state.used_seconds == 220
    assert store.state.policy_version == 2
    result = heartbeat(instance)
    assert result["used_seconds"] == 220
    assert result["remaining_seconds"] == 11 * 60 - 220


def test_local_demo_policy_can_explicitly_reset_allocation():
    store = MemoryTimeStore()
    store.state = F1State(local_date="2026-09-28", used_seconds=220, policy_version=1)
    simulated = SimulatedTime()
    instance = F1Controller(
        policy(version=2, weekday_minutes=3),
        store,
        monotonic_clock=simulated.mono,
        wall_clock=simulated.current_wall,
        to_local_datetime=lambda value: datetime.fromtimestamp(value, UTC),
        reset_on_policy_version_change=True,
    )
    assert heartbeat(instance)["remaining_seconds"] == 180
    assert store.state.used_seconds == 0


def test_policy_change_clamps_to_zero_when_new_quota_is_below_today_usage():
    store = MemoryTimeStore()
    store.state = F1State(local_date="2026-09-28", used_seconds=240, policy_version=1)
    instance, _, _ = controller(policy(weekday_minutes=5), store=store)
    instance.replace_policy(policy(version=2, weekday_minutes=3))
    assert instance.snapshot()["remaining_seconds"] == 0
    result = heartbeat(instance)
    assert result["used_seconds"] == 240
    assert result["remaining_seconds"] == 0


def test_policy_change_discards_one_time_grant_but_counts_time_used_from_it():
    store = MemoryTimeStore()
    store.state = F1State(local_date="2026-09-28", used_seconds=60, policy_version=1)
    instance, _, _ = controller(policy(weekday_minutes=1), store=store)
    heartbeat(instance)
    assert instance.grant_extra_time(15, command_id="once") == 900
    assert instance.reduce_remaining_for_demo(120) == 120
    assert heartbeat(instance)["used_seconds"] == 180
    instance.replace_policy(policy(version=2, weekday_minutes=5))
    result = heartbeat(instance)
    assert result["used_seconds"] == 180
    assert result["extra_seconds"] == 0
    assert result["remaining_seconds"] == 120
    assert instance.grant_extra_time(15, command_id="once") == 0


def test_one_time_grant_survives_restart_without_policy_change():
    store = MemoryTimeStore()
    instance, simulated, _ = controller(policy(weekday_minutes=1), store=store)
    heartbeat(instance)
    instance.grant_extra_time(15, command_id="once")
    restarted, _, _ = controller(policy(weekday_minutes=1), simulated=simulated, store=store)
    assert heartbeat(restarted)["remaining_seconds"] == 16 * 60
    assert restarted.grant_extra_time(15, command_id="once") == 0


def test_enabling_after_disabled_policy_keeps_usage_before_first_tray_heartbeat():
    store = MemoryTimeStore()
    store.state = F1State(
        local_date="2026-09-28",
        used_seconds=180,
        policy_version=1,
    )
    controller(policy(version=2, enabled=True, weekday_minutes=3), store=store)
    assert store.state.policy_version == 2
    assert store.state.used_seconds == 180
    assert store.state.recorded_at == "2026-09-28T09:00:00Z"


def test_same_policy_version_preserves_usage_across_restart():
    store = MemoryTimeStore()
    store.state = F1State(
        local_date="2026-09-28",
        used_seconds=220,
        policy_version=1,
    )
    instance, _, _ = controller(policy(version=1, weekday_minutes=11), store=store)
    result = heartbeat(instance)
    assert result["used_seconds"] == 220
    assert result["remaining_seconds"] == 440


def test_state_and_every_event_have_iso_recorded_date_time():
    instance, _, store = controller(policy(schedule=("0" * 48,) * 7))
    heartbeat(instance)
    assert store.state.recorded_at == "2026-09-28T09:00:00Z"
    assert store.events
    assert all(event["recorded_at"] == "2026-09-28T09:00:00Z" for event in store.events)


def test_sqlite_store_migrates_event_timestamp_to_recorded_at(tmp_path):
    database = tmp_path / "legacy.db"
    with sqlite3.connect(database) as db:
        db.execute(
            "CREATE TABLE f1_events ("
            "id TEXT PRIMARY KEY, ts REAL NOT NULL, type TEXT NOT NULL, "
            "message TEXT NOT NULL, details TEXT NOT NULL, acknowledged INTEGER NOT NULL)"
        )
        db.execute(
            "INSERT INTO f1_events VALUES (?, ?, ?, ?, ?, ?)",
            ("event-1", 0.0, "legacy", "old event", "{}", 0),
        )

    store = SQLiteTimeStore(database)
    assert store.recent_events()[0]["recorded_at"] == "1970-01-01T00:00:00Z"


def test_three_hour_clock_rollback_neither_resets_nor_adds_quota():
    instance, simulated, store = controller(policy(weekday_minutes=30))
    result = advance_heartbeats(instance, simulated, 10)
    remaining_before = result["remaining_seconds"]
    simulated.monotonic += 1
    simulated.wall -= 3 * 3600
    result = heartbeat(instance)
    assert result["remaining_seconds"] == remaining_before - 1
    assert result["clock_tamper_detected"] is True
    assert len([event for event in store.events if event["type"] == "clock_tamper"]) == 1


def test_state_and_grace_survive_service_restart(tmp_path):
    simulated = SimulatedTime()
    store = SQLiteTimeStore(tmp_path / "f1.db")
    selected = policy(weekday_minutes=1, warnings_minutes=(1,))
    first, _, _ = controller(selected, simulated=simulated, store=store)
    advance_heartbeats(first, simulated, 60)

    restarted, _, _ = controller(selected, simulated=simulated, store=store)
    simulated.advance(61)
    result = heartbeat(restarted)
    assert result["used_seconds"] == 60
    assert result["mode"] == "quota_exhausted"
    assert result["lock_required"] is True


def test_completed_lock_survives_service_restart(tmp_path):
    simulated = SimulatedTime()
    store = SQLiteTimeStore(tmp_path / "f1.db")
    selected = policy(weekday_minutes=1, warnings_minutes=(1,), grace_seconds=0)
    first, _, _ = controller(selected, simulated=simulated, store=store)
    advance_heartbeats(first, simulated, 60)
    first.acknowledge_lock("quota_exhausted")

    restarted, _, _ = controller(selected, simulated=simulated, store=store)
    result = heartbeat(restarted)
    assert result["mode"] == "quota_exhausted"
    assert result["lock_required"] is False
    assert result["lock_completed"] is True


def test_forward_date_change_resets_daily_usage():
    instance, simulated, _ = controller()
    advance_heartbeats(instance, simulated, 10)
    simulated.wall += 86400
    simulated.monotonic += 1
    result = heartbeat(instance)
    assert result["used_seconds"] == 1


def test_events_can_be_acknowledged():
    instance, _, store = controller(policy(schedule=("0" * 48,) * 7))
    result = heartbeat(instance)
    event_ids = [event["id"] for event in result["notifications"]]
    assert event_ids
    instance.acknowledge_events(event_ids)
    assert store.pending_events() == []
