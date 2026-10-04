"""Local IPC operations for the visible Windows time-control agent."""

from __future__ import annotations

import threading
import time
import uuid
from collections.abc import Callable
from typing import Any

import httpx
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, VerifyMismatchError

from agent.ipc_protocol import ProtocolError, error_response, parse_request, success_response
from agent.time_control import F1Controller


class AgentCore:
    """Validate Tray messages and expose the service-owned F1 state machine."""

    UI_PRESENCE_TIMEOUT_SECONDS = 15.0

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        wall_clock: Callable[[], float] = time.time,
        time_controller: F1Controller | None = None,
        child_name: str | None = None,
        child_pin_hash: str | None = None,
        pairing_required: bool = False,
    ):
        self._clock = clock
        self._wall_clock = wall_clock
        self._started_monotonic = clock()
        self._started_at = wall_clock()
        self._last_ui_heartbeat: float | None = None
        self._request_count = 0
        self._time_controller = time_controller
        self._lock = threading.RLock()
        self._remote_connected = False
        self._remote_error: str | None = None
        self._remote_lock: dict[str, Any] | None = None
        self._processed_commands: list[str] = []
        self._command_acks: list[dict[str, str]] = []
        self._child_audit: list[dict[str, Any]] = []
        self._child_name = child_name
        self._child_pin_hash = child_pin_hash
        self._profiles: dict[str, dict[str, Any]] = {}
        self._controllers: dict[str, F1Controller] = {}
        self._active_child_id: str | None = None
        self._remote_profiles_enabled = False
        if child_name and child_pin_hash:
            self._profiles["legacy"] = {
                "id": "legacy",
                "display_name": child_name,
                "pin_hash": child_pin_hash,
            }
            if time_controller is not None:
                self._controllers["legacy"] = time_controller
        self._active_user: str | None = "Bản demo cục bộ" if child_name is None else None
        self._active_since: float | None = wall_clock() if child_name is None else None
        self._pin_failures = 0
        self._pin_locked_until = 0.0
        self._time_requests: list[dict[str, Any]] = []
        self._request_history: list[dict[str, Any]] = []
        self._password_hasher = PasswordHasher()
        self._session_changed: Callable[[], None] | None = None
        self._time_request_queued: Callable[[], None] | None = None
        self._pairing_required = pairing_required
        self._enrolled = not pairing_required
        self._enroll_callback: Callable[[str], None] | None = None

    def set_enrollment_callback(self, callback: Callable[[str], None]) -> None:
        with self._lock:
            self._enroll_callback = callback

    def mark_enrolled(self) -> None:
        with self._lock:
            self._enrolled = True

    def set_session_change_callback(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._session_changed = callback

    def set_time_request_callback(self, callback: Callable[[], None]) -> None:
        with self._lock:
            self._time_request_queued = callback

    def configure_child_login(self, *, child_name: str, child_pin_hash: str) -> None:
        with self._lock:
            self._child_name = child_name
            self._child_pin_hash = child_pin_hash
            self._profiles = {
                "legacy": {"id": "legacy", "display_name": child_name, "pin_hash": child_pin_hash}
            }
            if self._time_controller is not None:
                self._controllers["legacy"] = self._time_controller
            self._active_user = None
            self._active_since = None

    def configure_remote_pending(self) -> None:
        with self._lock:
            self._remote_profiles_enabled = True
            self._active_user = None
            self._active_child_id = None
            self._active_since = None
            self._time_controller = None

    def configure_profiles(
        self,
        profiles: list[dict[str, Any]],
        controller_factory: Callable[[str, Any], F1Controller],
        primary_child_id: str | None = None,
    ) -> None:
        with self._lock:
            old_profiles = self._profiles
            next_profiles: dict[str, dict[str, Any]] = {}
            next_controllers: dict[str, F1Controller] = {}
            for profile in profiles:
                child_id = profile["id"]
                controller = self._controllers.get(child_id)
                if controller is None:
                    controller = controller_factory(child_id, profile["policy"])
                elif controller.policy != profile["policy"]:
                    controller.replace_policy(profile["policy"])
                next_profiles[child_id] = {
                    "id": child_id,
                    "display_name": profile["display_name"],
                    "pin_hash": profile["pin_hash"],
                }
                next_controllers[child_id] = controller
            self._profiles = next_profiles
            self._controllers = next_controllers
            self._remote_profiles_enabled = True
            self._child_name = next_profiles.get(primary_child_id or "", {}).get("display_name")
            if self._active_child_id and (
                self._active_child_id not in next_profiles
                or old_profiles.get(self._active_child_id, {}).get("pin_hash")
                != next_profiles[self._active_child_id]["pin_hash"]
            ):
                self._active_child_id = None
                self._active_user = None
                self._active_since = None
            if self._active_child_id:
                self._active_user = next_profiles[self._active_child_id]["display_name"]
                self._time_controller = next_controllers[self._active_child_id]
            else:
                self._time_controller = None

    def _start_session(
        self, pin: str, child_id: str | None, username: str | None = None
    ) -> tuple[bool, str]:
        with self._lock:
            if self._pairing_required and not self._enrolled:
                return False, "Pair this device before signing in"
            if username is not None:
                matches = [
                    item["id"]
                    for item in self._profiles.values()
                    if item["display_name"].casefold() == username.strip().casefold()
                ]
                if len(matches) != 1 or (child_id is not None and child_id != matches[0]):
                    return False, "Unknown child username"
                child_id = matches[0]
            if not self._remote_profiles_enabled and not self._profiles:
                self._active_user = "Bản demo cục bộ"
                self._active_since = self._wall_clock()
                if self._session_changed:
                    self._session_changed()
                return True, self._active_user
            if child_id is None and len(self._profiles) == 1 and "legacy" in self._profiles:
                child_id = "legacy"
            profile = self._profiles.get(child_id or "")
            if profile is None:
                return False, "Choose an available child profile"
            if time.monotonic() < self._pin_locked_until:
                return False, "Too many incorrect PIN attempts; try again in 15 minutes"
            try:
                valid = self._password_hasher.verify(profile["pin_hash"], pin)
            except (VerificationError, VerifyMismatchError, ValueError):
                valid = False
            if not valid:
                self._pin_failures += 1
                if self._pin_failures >= 5:
                    self._pin_locked_until = time.monotonic() + 15 * 60
                    self._pin_failures = 0
                return False, "Incorrect child PIN"
            self._pin_failures = 0
            self._pin_locked_until = 0.0
            self._active_child_id = child_id
            self._active_user = profile["display_name"]
            self._active_since = self._wall_clock()
            self._time_controller = self._controllers.get(child_id)
            if self._time_controller is not None:
                self._time_controller.reset_tick_baseline()
            if self._session_changed:
                self._session_changed()
            return True, self._active_user

    def _end_session(self) -> None:
        with self._lock:
            self._active_user = None
            self._active_child_id = None
            self._active_since = None
            if self._remote_profiles_enabled:
                self._time_controller = None
            if self._session_changed:
                self._session_changed()

    def pending_time_requests(self) -> list[dict[str, Any]]:
        with self._lock:
            return [dict(item) for item in self._time_requests]

    def acknowledge_time_request(self, request_id: str) -> None:
        with self._lock:
            self._time_requests = [
                item for item in self._time_requests if item["request_id"] != request_id
            ]

    def set_remote_request_status(self, request_id: str, status: str) -> None:
        with self._lock:
            for collection in (self._time_requests, self._request_history):
                for item in collection:
                    if item["request_id"] == request_id and item["status"] not in {
                        "approved",
                        "rejected",
                    }:
                        item["status"] = status

    def set_remote_status(self, *, connected: bool, error: str | None = None) -> None:
        with self._lock:
            self._remote_connected = connected
            self._remote_error = error

    def set_child_audit(self, entries: list[dict[str, Any]]) -> None:
        with self._lock:
            self._child_audit = [dict(entry) for entry in entries[:5]]
            for entry in entries:
                if entry.get("action") != "time_request_decided":
                    continue
                decision = entry.get("new_value") or {}
                if decision.get("status") == "rejected" and isinstance(
                    decision.get("client_request_id"), str
                ):
                    self.set_remote_request_status(decision["client_request_id"], "rejected")

    def apply_remote_policy(self, policy) -> None:
        if self._time_controller is None:
            raise RuntimeError("F1 time controller is unavailable")
        self._time_controller.replace_policy(policy)

    def apply_remote_command(self, command: dict[str, Any]) -> None:
        command_id = command.get("id")
        command_type = command.get("type")
        payload = command.get("payload") or {}
        if not isinstance(command_id, str) or not command_id:
            raise ValueError("Remote command id is missing")
        with self._lock:
            if command_id in self._processed_commands or (
                self._remote_lock and self._remote_lock.get("id") == command_id
            ):
                if command_id in self._processed_commands and not any(
                    ack["command_id"] == command_id for ack in self._command_acks
                ):
                    self._command_acks.append(
                        {"command_id": command_id, "result": "already_applied"}
                    )
                return
            if command_type == "lock_now":
                self._remote_lock = {"id": command_id, "type": command_type}
                return
            if command_type != "add_time":
                raise ValueError("Unsupported remote command")
            minutes = payload.get("minutes")
            target_child_id = command.get("child_id")
            controller = (
                self._controllers.get(target_child_id) if target_child_id else self._time_controller
            )
            if controller is None:
                raise RuntimeError("F1 time controller is unavailable")
            granted = controller.grant_extra_time(minutes, command_id=command_id)
            client_request_id = payload.get("client_request_id")
            if isinstance(client_request_id, str):
                self.set_remote_request_status(client_request_id, "approved")
            self._remember_processed(command_id)
            self._command_acks.append(
                {"command_id": command_id, "result": f"restored_{granted}_seconds"}
            )

    def drain_command_acks(self) -> list[dict[str, str]]:
        with self._lock:
            result = list(self._command_acks)
            self._command_acks.clear()
            return result

    def pending_command_acks(self) -> list[dict[str, str]]:
        with self._lock:
            return list(self._command_acks)

    def remove_command_ack(self, command_id: str) -> None:
        with self._lock:
            self._command_acks = [
                ack for ack in self._command_acks if ack["command_id"] != command_id
            ]

    def _remember_processed(self, command_id: str) -> None:
        self._processed_commands.append(command_id)
        del self._processed_commands[:-100]

    def status(self) -> dict[str, Any]:
        with self._lock:
            ui_connected = (
                self._last_ui_heartbeat is not None
                and self._clock() - self._last_ui_heartbeat <= self.UI_PRESENCE_TIMEOUT_SECONDS
            )
            time_status = (
                self._time_controller.snapshot()
                if self._time_controller
                else {
                    "configured": self._remote_profiles_enabled,
                    "policy_error": None
                    if self._remote_profiles_enabled
                    else "F1 time controller is unavailable",
                    "enabled": False,
                    "mode": "awaiting_profile" if self._remote_profiles_enabled else "disabled",
                    "remaining_seconds": None,
                    "remaining_minutes": None,
                    "lock_required": False,
                    "notifications": [],
                }
            )
            if self._pairing_required and not self._enrolled:
                time_status = dict(time_status)
                time_status.update(
                    {"mode": "awaiting_pairing", "enabled": False, "lock_required": False}
                )
            if not ui_connected and time_status.get("enabled"):
                time_status = dict(time_status)
                time_status.update(
                    {
                        "mode": "inert_no_tray",
                        "active_usage": False,
                        "lock_required": False,
                        "lock_reason": None,
                    }
                )
            if (
                ui_connected
                and self._active_user is None
                and (not self._pairing_required or self._enrolled)
            ):
                time_status = dict(time_status)
                time_status.update(
                    {
                        "mode": "awaiting_profile",
                        "active_usage": False,
                        "lock_required": False,
                        "lock_reason": None,
                    }
                )
            if self._remote_lock is not None and ui_connected:
                time_status = dict(time_status)
                time_status.update(
                    {
                        "mode": "remote_lock",
                        "lock_required": True,
                        "lock_reason": "remote_lock",
                        "remote_command_id": self._remote_lock["id"],
                    }
                )
            agent_active = bool(
                ui_connected
                and self._active_user is not None
                and time_status.get("configured")
                and time_status.get("enabled")
            )
            return {
                "service": "running",
                "service_started_at": self._started_at,
                "uptime_seconds": max(0, int(self._clock() - self._started_monotonic)),
                "ui_connected": ui_connected,
                "agent_active": agent_active,
                "enforcement_mode": time_status["mode"],
                "remaining_minutes": time_status.get("remaining_minutes"),
                "time_control": time_status,
                "extra_time_requests_received": self._request_count,
                "time_requests": [
                    dict(item)
                    for item in self._request_history
                    if item["child_id"] == self._active_child_id
                ],
                "remote": {
                    "connected": self._remote_connected,
                    "last_error": self._remote_error,
                },
                "enrollment": {"required": self._pairing_required, "enrolled": self._enrolled},
                "child_audit": list(self._child_audit),
                "current_policy": (
                    {
                        "version": self._time_controller.policy.version,
                        "enabled": self._time_controller.policy.enabled,
                        "weekday_minutes": self._time_controller.policy.weekday_minutes,
                        "weekend_minutes": self._time_controller.policy.weekend_minutes,
                        "schedule": list(self._time_controller.policy.schedule),
                        "warnings_minutes": list(self._time_controller.policy.warnings_minutes),
                        "grace_seconds": self._time_controller.policy.grace_seconds,
                        "idle_threshold_seconds": self._time_controller.policy.idle_threshold_seconds,
                    }
                    if self._time_controller and self._active_child_id
                    else None
                ),
                "current_user": self._active_user,
                "active_child_id": self._active_child_id,
                "current_user_since": self._active_since,
                "assigned_child": self._child_name,
                "profiles": [
                    {"id": profile["id"], "display_name": profile["display_name"]}
                    for profile in self._profiles.values()
                ],
                "capabilities": {
                    "named_pipe": True,
                    "ui_presence": True,
                    "time_enforcement": self._time_controller is not None,
                    "demo_time_reduction": self._time_controller is not None,
                    "remote_parent_requests": bool(self._profiles),
                    "child_profile_login": self._remote_profiles_enabled,
                    "activity_monitoring": False,
                    "dns_filtering": False,
                },
            }

    def handle(self, message: dict[str, Any]) -> dict[str, Any]:
        request_id = message.get("request_id", "unknown")
        try:
            request = parse_request(message)
        except ProtocolError as exc:
            return error_response(str(request_id)[:80], "invalid_request", str(exc))

        if request.message_type == "ping":
            return success_response(
                request.request_id,
                {"reply": "pong", "service": "OpenGuardKidsAgentTest"},
            )
        if request.message_type == "get_status":
            return success_response(request.request_id, self.status())
        if request.message_type == "enroll_device":
            code = request.payload.get("code")
            if (
                not isinstance(code, str)
                or len(code) != 8
                or any(char not in "ABCDEFGHJKLMNPQRSTUVWXYZ23456789" for char in code.upper())
            ):
                return error_response(
                    request.request_id, "invalid_code", "Enter an eight-character pairing code"
                )
            with self._lock:
                if self._enrolled:
                    return error_response(
                        request.request_id, "already_enrolled", "Device is already paired"
                    )
                callback = self._enroll_callback
            if callback is None:
                return error_response(
                    request.request_id, "enrollment_unavailable", "Pairing is not configured"
                )
            try:
                callback(code.upper())
            except (httpx.HTTPError, OSError, ValueError, RuntimeError, KeyError) as exc:
                return error_response(request.request_id, "enrollment_failed", str(exc)[:200])
            self.mark_enrolled()
            return success_response(request.request_id, {"enrolled": True})
        if request.message_type == "ui_heartbeat":
            visible = request.payload.get("visible")
            idle_seconds = request.payload.get("idle_seconds")
            session_locked = request.payload.get("session_locked")
            if not isinstance(visible, bool):
                return error_response(
                    request.request_id, "invalid_activity", "visible must be a boolean"
                )
            if (
                isinstance(idle_seconds, bool)
                or not isinstance(idle_seconds, (int, float))
                or not 0 <= idle_seconds <= 7 * 86400
            ):
                return error_response(
                    request.request_id,
                    "invalid_activity",
                    "idle_seconds must be a number between 0 and 604800",
                )
            if not isinstance(session_locked, bool):
                return error_response(
                    request.request_id,
                    "invalid_activity",
                    "session_locked must be a boolean",
                )
            with self._lock:
                if visible:
                    self._last_ui_heartbeat = self._clock()
                else:
                    self._last_ui_heartbeat = None
                if self._time_controller is not None:
                    self._time_controller.tick(
                        idle_seconds=float(idle_seconds),
                        session_locked=session_locked,
                        ui_present=visible and self._active_user is not None,
                    )
            return success_response(request.request_id, self.status())
        if request.message_type == "start_session":
            pin = request.payload.get("pin")
            child_id = request.payload.get("child_id")
            username = request.payload.get("username")
            if username is not None and (
                not isinstance(username, str) or not 1 <= len(username.strip()) <= 80
            ):
                return error_response(request.request_id, "invalid_username", "username is invalid")
            if child_id is not None and (not isinstance(child_id, str) or len(child_id) > 80):
                return error_response(request.request_id, "invalid_child_id", "child_id is invalid")
            if not isinstance(pin, str) or len(pin) != 6 or not pin.isdigit():
                return error_response(
                    request.request_id, "invalid_pin", "pin must contain exactly six digits"
                )
            success, value = self._start_session(pin, child_id, username)
            if not success:
                return error_response(request.request_id, "login_failed", value)
            return success_response(
                request.request_id,
                {
                    "current_user": value,
                    "active_child_id": self._active_child_id,
                    "current_user_since": self._active_since,
                },
            )
        if request.message_type == "end_session":
            self._end_session()
            return success_response(
                request.request_id, {"current_user": None, "active_child_id": None}
            )
        if request.message_type == "ack_time_events":
            event_ids = request.payload.get("event_ids")
            if (
                not isinstance(event_ids, list)
                or len(event_ids) > 20
                or any(
                    not isinstance(event_id, str) or not 1 <= len(event_id) <= 80
                    for event_id in event_ids
                )
            ):
                return error_response(
                    request.request_id,
                    "invalid_event_ids",
                    "event_ids must be a list of at most 20 non-empty strings",
                )
            if self._time_controller is not None:
                self._time_controller.acknowledge_events(event_ids)
            return success_response(request.request_id, {"acknowledged": len(event_ids)})
        if request.message_type == "ack_lock":
            reason = request.payload.get("reason")
            if reason not in {"quota_exhausted", "outside_schedule", "remote_lock"}:
                return error_response(
                    request.request_id,
                    "invalid_lock_reason",
                    "reason must be quota_exhausted, outside_schedule, or remote_lock",
                )
            if reason == "remote_lock":
                command_id = request.payload.get("command_id")
                with self._lock:
                    if not self._remote_lock or command_id != self._remote_lock.get("id"):
                        return error_response(
                            request.request_id,
                            "invalid_command_id",
                            "command_id does not match the pending remote lock",
                        )
                    self._remote_lock = None
                    self._remember_processed(command_id)
                    self._command_acks.append(
                        {"command_id": command_id, "result": "workstation_lock_requested"}
                    )
            elif self._time_controller is not None:
                self._time_controller.acknowledge_lock(reason)
            return success_response(request.request_id, {"acknowledged": True, "reason": reason})
        if request.message_type == "demo_reduce_time":
            seconds = request.payload.get("seconds")
            if (
                isinstance(seconds, bool)
                or not isinstance(seconds, int)
                or not 1 <= seconds <= 3600
            ):
                return error_response(
                    request.request_id,
                    "invalid_seconds",
                    "seconds must be an integer between 1 and 3600",
                )
            if self._time_controller is None or not self._time_controller.enabled:
                return error_response(
                    request.request_id,
                    "demo_unavailable",
                    "F1 must be enabled before demo time can be reduced",
                )
            reduced = self._time_controller.reduce_remaining_for_demo(seconds)
            return success_response(
                request.request_id,
                {"requested_seconds": seconds, "reduced_seconds": reduced},
            )
        if request.message_type == "request_more_time":
            minutes = request.payload.get("minutes")
            if isinstance(minutes, bool) or not isinstance(minutes, int) or not 1 <= minutes <= 120:
                return error_response(
                    request.request_id,
                    "invalid_minutes",
                    "minutes must be an integer between 1 and 120",
                )
            with self._lock:
                if not self._profiles:
                    return error_response(
                        request.request_id,
                        "remote_not_enrolled",
                        "Enroll this device with a parent dashboard before requesting time",
                    )
                if not self._active_user or self._active_child_id is None:
                    return error_response(
                        request.request_id,
                        "no_active_session",
                        "A child must sign in before requesting time",
                    )
                self._request_count += 1
                local_request_id = str(uuid.uuid4())
                time_request = {
                    "request_id": local_request_id,
                    "child_id": self._active_child_id,
                    "requester": self._active_user,
                    "minutes": minutes,
                    "created_at": self._wall_clock(),
                    "status": "sending",
                }
                self._time_requests.append(time_request)
                self._request_history.append(dict(time_request))
                self._request_history = self._request_history[-20:]
                request_callback = self._time_request_queued
            if request_callback is not None:
                request_callback()
            return success_response(
                request.request_id,
                {
                    "accepted": True,
                    "local_request_id": local_request_id,
                    "minutes": minutes,
                    "delivery": "queued_for_parent_dashboard",
                    "requester": self._active_user,
                    "child_id": self._active_child_id,
                },
            )
        return error_response(
            request.request_id,
            "unsupported_operation",
            f"Unsupported operation: {request.message_type}",
        )
