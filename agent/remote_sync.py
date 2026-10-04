"""Authenticated F4 policy and command channel for the Windows service."""

from __future__ import annotations

import argparse
import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
import websocket
from dotenv import load_dotenv

from agent.time_control import F1Controller, SQLiteTimeStore, TimePolicy
from server.app.policy_signing import verify_policy


@dataclass
class RemoteConfig:
    server_url: str
    device_id: str
    access_token: str
    refresh_token: str
    policy_signing_key: str
    fingerprint: str
    child_id: str = ""
    child_name: str = ""
    child_pin_hash: str = ""
    legacy_state_child_id: str = ""
    heartbeat_seconds: int = 30

    @classmethod
    def load(cls, path: str | Path) -> RemoteConfig:
        return cls(**json.loads(Path(path).read_text(encoding="utf-8")))

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_suffix(target.suffix + ".tmp")
        temporary.write_text(
            json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8"
        )
        os.replace(temporary, target)


def verified_time_policy(document: dict[str, Any], key: str) -> TimePolicy:
    envelope = dict(document)
    integrity = envelope.pop("integrity", None)
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "hmac-sha256":
        raise ValueError("Policy has no supported integrity marker")
    if not verify_policy(envelope, integrity.get("signature", ""), key):
        raise ValueError("Policy signature is invalid; cached policy was preserved")
    accepted = {
        name: envelope[name]
        for name in (
            "version",
            "enabled",
            "weekday_minutes",
            "weekend_minutes",
            "schedule",
            "warnings_minutes",
            "grace_seconds",
            "idle_threshold_seconds",
        )
    }
    return TimePolicy.from_dict(accepted)


def save_signed_policy(path: str | Path, document: dict[str, Any]) -> None:
    target = Path(path)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(json.dumps(document, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(temporary, target)


def verified_profiles_document(
    document: dict[str, Any], key: str, device_id: str | None = None
) -> dict[str, Any]:
    envelope = dict(document)
    integrity = envelope.pop("integrity", None)
    if not isinstance(integrity, dict) or integrity.get("algorithm") != "hmac-sha256":
        raise ValueError("Profile list has no supported integrity marker")
    if not verify_policy(envelope, integrity.get("signature", ""), key):
        raise ValueError("Profile list signature is invalid")
    if device_id is not None and envelope.get("device_id") != device_id:
        raise ValueError("Profile cache belongs to another device")
    profiles = []
    for item in envelope["profiles"]:
        if not isinstance(item, dict) or not all(
            isinstance(item.get(field), str) and item[field]
            for field in ("id", "display_name", "pin_hash")
        ):
            raise ValueError("Profile list has an invalid child")
        if not item["pin_hash"].startswith("$argon2"):
            raise ValueError("Profile PIN hash is invalid")
        policy = verified_time_policy(item["policy"], key)
        if item["policy"].get("child_id") != item["id"]:
            raise ValueError("Profile policy belongs to another child")
        profiles.append({**item, "policy": policy})
    return {"primary_child_id": envelope["primary_child_id"], "profiles": profiles}


def load_cached_remote_policy(config_path: str | Path, policy_path: str | Path) -> TimePolicy:
    config = RemoteConfig.load(config_path)
    document = json.loads(Path(policy_path).read_text(encoding="utf-8"))
    return verified_time_policy(document, config.policy_signing_key)


class RemoteSync:
    def __init__(self, core, config_path: str | Path, policy_path: str | Path):
        self.core = core
        self.config_path = Path(config_path)
        self.policy_path = Path(policy_path)
        self.config = RemoteConfig.load(config_path)
        self.stop_event = threading.Event()
        self._sync_wake = threading.Event()
        self._request_wake = threading.Event()
        self._time_status_wake = threading.Event()
        self._threads: list[threading.Thread] = []
        self._token_lock = threading.RLock()
        self._access_deadline = time.monotonic() + 14 * 60
        self.profiles_path = self.policy_path.with_name("profiles-cache.json")
        self.primary_child_id = self.config.child_id
        self._legacy_state_child_id = self.config.legacy_state_child_id or self.config.child_id
        self.core.set_session_change_callback(self._wake_session_sync)
        self.core.set_time_request_callback(self._request_wake.set)
        self.core.configure_remote_pending()
        if self.profiles_path.exists():
            try:
                cached = verified_profiles_document(
                    json.loads(self.profiles_path.read_text(encoding="utf-8")),
                    self.config.policy_signing_key,
                    self.config.device_id,
                )
                self._configure_profiles(cached)
            except (OSError, ValueError, KeyError, TypeError) as exc:
                self.core.set_remote_status(connected=False, error=str(exc))

    def _controller_for_profile(self, child_id: str, policy: TimePolicy) -> F1Controller:
        uuid.UUID(child_id)
        database_path = self.policy_path.with_name(
            "f1-state.db" if child_id == self._legacy_state_child_id else f"f1-{child_id}.db"
        )
        store = SQLiteTimeStore(database_path)
        return F1Controller(policy, store)

    def _configure_profiles(self, document: dict[str, Any]) -> None:
        self.primary_child_id = document["primary_child_id"]
        self.core.configure_profiles(
            document["profiles"], self._controller_for_profile, self.primary_child_id
        )

    def _wake_session_sync(self) -> None:
        self._sync_wake.set()
        self._time_status_wake.set()

    def start(self) -> None:
        self._threads = [
            threading.Thread(target=self._heartbeat_loop, name="ogk-heartbeat", daemon=True),
            threading.Thread(target=self._websocket_loop, name="ogk-emergency", daemon=True),
            threading.Thread(target=self._time_request_loop, name="ogk-time-requests", daemon=True),
            threading.Thread(target=self._time_status_loop, name="ogk-time-status", daemon=True),
        ]
        for thread in self._threads:
            thread.start()
        self._request_wake.set()
        self._time_status_wake.set()

    def stop(self) -> None:
        self.stop_event.set()
        self._sync_wake.set()
        self._request_wake.set()
        self._time_status_wake.set()
        for thread in self._threads:
            thread.join(timeout=5)

    def _refresh(self, client: httpx.Client) -> None:
        with self._token_lock:
            response = client.post(
                "/api/auth/device/refresh",
                json={
                    "device_id": self.config.device_id,
                    "refresh_token": self.config.refresh_token,
                },
            )
            response.raise_for_status()
            result = response.json()
            self.config.access_token = result["access_token"]
            self.config.refresh_token = result["refresh_token"]
            self._access_deadline = time.monotonic() + result["expires_in"] - 60
            self.config.save(self.config_path)

    def _request(self, client: httpx.Client, method: str, path: str, **kwargs):
        if time.monotonic() >= self._access_deadline:
            self._refresh(client)
        with self._token_lock:
            token = self.config.access_token
        response = client.request(
            method, path, headers={"Authorization": "Bearer " + token}, **kwargs
        )
        if response.status_code == 401:
            self._refresh(client)
            with self._token_lock:
                token = self.config.access_token
            response = client.request(
                method, path, headers={"Authorization": "Bearer " + token}, **kwargs
            )
        response.raise_for_status()
        return response

    def _heartbeat_loop(self) -> None:
        with httpx.Client(base_url=self.config.server_url, timeout=10, trust_env=False) as client:
            while not self.stop_event.is_set():
                started = time.monotonic()
                try:
                    profiles_document = self._request(client, "GET", "/api/device/profiles").json()
                    profiles = verified_profiles_document(
                        profiles_document, self.config.policy_signing_key, self.config.device_id
                    )
                    self._configure_profiles(profiles)
                    self._time_status_wake.set()
                    save_signed_policy(self.profiles_path, profiles_document)
                    status = self.core.status()
                    current_version = int(status["time_control"].get("policy_version", 0))
                    self._request(
                        client,
                        "POST",
                        "/api/device/session",
                        json={
                            "active_child_id": status.get("active_child_id"),
                            "active_user": status.get("current_user"),
                            "active_since": status.get("current_user_since"),
                        },
                    )
                    heartbeat = self._request(
                        client,
                        "POST",
                        "/api/heartbeat",
                        json={
                            "policy_version": current_version,
                            "used_seconds": int(status["time_control"].get("used_seconds", 0)),
                        },
                    ).json()
                    for command in heartbeat.get("commands", []):
                        self.core.apply_remote_command(command)
                    audit = self._request(client, "GET", "/api/device/audit").json()
                    self.core.set_child_audit(audit)
                    self.core.set_remote_status(connected=True)
                except (httpx.HTTPError, OSError, ValueError, KeyError) as exc:
                    self.core.set_remote_status(connected=False, error=str(exc))
                delay = max(1, self.config.heartbeat_seconds - (time.monotonic() - started))
                self._sync_wake.wait(delay)
                self._sync_wake.clear()

    def _time_status_loop(self) -> None:
        with httpx.Client(base_url=self.config.server_url, timeout=10, trust_env=False) as client:
            while not self.stop_event.is_set():
                try:
                    status = self.core.status()
                    control = status["time_control"]
                    self._request(
                        client,
                        "POST",
                        "/api/device/time-status",
                        json={
                            "active_child_id": status.get("active_child_id"),
                            "active_user": status.get("current_user")
                            if status.get("active_child_id")
                            else None,
                            "active_since": status.get("current_user_since"),
                            "policy_version": int(control.get("policy_version", 0)),
                            "used_seconds": control.get("used_seconds")
                            if status.get("active_child_id")
                            else None,
                            "remaining_seconds": control.get("remaining_seconds"),
                            "quota_seconds": control.get("quota_seconds"),
                            "extra_seconds": control.get("extra_seconds"),
                            "active_usage": bool(control.get("active_usage")),
                        },
                    )
                except (httpx.HTTPError, OSError, ValueError, KeyError):
                    pass
                self._time_status_wake.wait(3)
                self._time_status_wake.clear()

    def _time_request_loop(self) -> None:
        with httpx.Client(base_url=self.config.server_url, timeout=10, trust_env=False) as client:
            while not self.stop_event.is_set():
                self._request_wake.wait()
                self._request_wake.clear()
                while not self.stop_event.is_set():
                    pending = self.core.pending_time_requests()
                    if not pending:
                        break
                    failed = False
                    for time_request in pending:
                        try:
                            result = self._request(
                                client,
                                "POST",
                                "/api/device/requests",
                                json={
                                    "request_id": time_request["request_id"],
                                    "child_id": time_request["child_id"],
                                    "requester": time_request["requester"],
                                    "minutes": time_request["minutes"],
                                    "created_at": time_request["created_at"],
                                },
                            ).json()
                            self.core.set_remote_request_status(
                                time_request["request_id"],
                                "approved_pending"
                                if result["status"] == "approved"
                                else result["status"],
                            )
                            self.core.acknowledge_time_request(time_request["request_id"])
                        except (httpx.HTTPError, OSError, ValueError, KeyError):
                            self.core.set_remote_request_status(
                                time_request["request_id"], "retrying"
                            )
                            failed = True
                            break
                    if failed and self.stop_event.wait(5):
                        return

    def _websocket_url(self) -> str:
        parsed = urlsplit(self.config.server_url)
        scheme = "wss" if parsed.scheme == "https" else "ws"
        with self._token_lock:
            token = quote(self.config.access_token, safe="")
        return urlunsplit((scheme, parsed.netloc, "/api/device/ws", "access_token=" + token, ""))

    def _websocket_loop(self) -> None:
        while not self.stop_event.is_set():
            connection = None
            try:
                connection = websocket.create_connection(
                    self._websocket_url(), timeout=2, http_proxy_host=None
                )
                self.core.set_remote_status(connected=True)
                while not self.stop_event.is_set():
                    for ack in self.core.pending_command_acks():
                        connection.send(json.dumps({"kind": "command_ack", **ack}))
                        self.core.remove_command_ack(ack["command_id"])
                    try:
                        raw = connection.recv()
                    except websocket.WebSocketTimeoutException:
                        continue
                    if not raw:
                        break
                    message = json.loads(raw)
                    if message.get("kind") == "command":
                        self.core.apply_remote_command(message["command"])
                        self._time_status_wake.set()
                    elif message.get("kind") == "policy_changed":
                        self._sync_wake.set()
                    elif (
                        message.get("kind") == "time_request_decision"
                        and message.get("status") == "rejected"
                        and isinstance(message.get("client_request_id"), str)
                    ):
                        self.core.set_remote_request_status(
                            message["client_request_id"], "rejected"
                        )
            except (
                OSError,
                ValueError,
                KeyError,
                json.JSONDecodeError,
                websocket.WebSocketException,
            ) as exc:
                self.core.set_remote_status(connected=False, error=str(exc))
            finally:
                if connection is not None:
                    connection.close()
            self.stop_event.wait(2)


def enroll(
    config_path: Path,
    server: str,
    code: str,
    name: str,
    signing_key: str = "",
) -> None:
    existing = RemoteConfig.load(config_path) if config_path.exists() else None
    fingerprint = existing.fingerprint if existing else str(uuid.uuid4())
    with httpx.Client(base_url=server, timeout=10, trust_env=False) as client:
        response = client.post(
            "/api/enroll",
            json={
                "code": code.strip().upper(),
                "display_name": name,
                "fingerprint": fingerprint,
            },
        )
        if response.status_code == 400:
            raise ValueError("Mã ghép đôi không hợp lệ, đã hết hạn hoặc đã được sử dụng")
        response.raise_for_status()
        tokens = response.json()
    if not tokens.get("child_id") or not tokens.get("child_name"):
        raise ValueError("Enrollment response is missing the assigned child profile")
    policy_key = tokens.get("policy_signing_key") or signing_key
    if not isinstance(policy_key, str) or len(policy_key) < 32:
        raise ValueError("Server did not provide a valid device policy key")
    RemoteConfig(
        server_url=server.rstrip("/"),
        device_id=tokens["device_id"],
        access_token=tokens["access_token"],
        refresh_token=tokens["refresh_token"],
        policy_signing_key=policy_key,
        fingerprint=fingerprint,
        child_id=tokens["child_id"],
        child_name=tokens["child_name"],
        child_pin_hash="",
        legacy_state_child_id=(
            existing.legacy_state_child_id or existing.child_id if existing else tokens["child_id"]
        ),
    ).save(config_path)


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Enroll the Week-2 Windows service agent")
    parser.add_argument("--config", required=True)
    parser.add_argument("--server", default="http://127.0.0.1:8000")
    parser.add_argument("--code", required=True)
    parser.add_argument("--name", default="Windows lab device")
    parser.add_argument(
        "--signing-key",
        default=os.getenv(
            "OGK_POLICY_SIGNING_KEY", "development-only-policy-signing-key-change-me"
        ),
    )
    args = parser.parse_args()
    if len(args.signing_key) < 32:
        parser.error("OGK_POLICY_SIGNING_KEY/--signing-key must contain at least 32 characters")
    parsed = urlsplit(args.server)
    if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("Week-2 enrollment only permits HTTP loopback; production requires HTTPS")
    enroll(Path(args.config), args.server, args.code, args.name, args.signing_key)
    print(f"Agent enrollment saved to {args.config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
