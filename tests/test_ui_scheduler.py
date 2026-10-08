from unittest.mock import Mock

import pytest

from agent.core import AgentCore
from agent.ipc_protocol import new_request
from agent.ui_scheduler import MonotonicScheduler
from tests.test_time_control import SimulatedTime, controller, policy


@pytest.mark.parametrize("jump", [-3 * 3600, 3 * 3600])
def test_tray_heartbeat_keeps_counting_when_wall_clock_changes(jump):
    clock = SimulatedTime()
    timer, _, _ = controller(policy(weekday_minutes=30), simulated=clock)
    core = AgentCore(clock=clock.mono, wall_clock=clock.current_wall, time_controller=timer)
    scheduler = MonotonicScheduler(clock=clock.mono)
    snapshots = []

    def refresh():
        response = core.handle(
            new_request(
                "ui_heartbeat", {"visible": True, "idle_seconds": 0, "session_locked": False}
            )
        )
        snapshots.append(response["data"]["time_control"])
        scheduler.after(1000, refresh)

    scheduler.after(0, refresh)
    scheduler.run_due()
    for _ in range(3):
        clock.advance(1)
        scheduler.run_due()
    before = snapshots[-1]["remaining_seconds"]
    clock.wall += jump
    for _ in range(10):
        clock.advance(1)
        scheduler.run_due()
    assert len(snapshots) == 14
    assert snapshots[-1]["remaining_seconds"] == before - 10
    if jump < 0:
        assert snapshots[-1]["clock_tamper_detected"] is True


def test_scheduler_preserves_order_and_defers_new_callbacks_until_next_pump():
    clock = SimulatedTime()
    scheduler = MonotonicScheduler(clock=clock.mono)
    seen = []

    def first():
        seen.append("first")
        scheduler.after(0, seen.append, "next pump")

    scheduler.after(0, first)
    scheduler.after(0, seen.append, "second")
    scheduler.run_due()
    assert seen == ["first", "second"]
    scheduler.run_due()
    assert seen == ["first", "second", "next pump"]


def test_failed_callback_does_not_stop_heartbeat_callbacks():
    scheduler = MonotonicScheduler()
    failed = Mock(side_effect=RuntimeError("render failed"))
    heartbeat = Mock()
    scheduler.after(0, failed)
    scheduler.after(0, heartbeat)
    scheduler.run_due()
    heartbeat.assert_called_once()
