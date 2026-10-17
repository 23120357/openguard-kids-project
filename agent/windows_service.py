"""Installable Windows Service for OpenGuard Kids F1 time control."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlsplit

from agent.core import AgentCore
from agent.filtering import AppController, DNSProxy
from agent.named_pipe import NamedPipeClient, NamedPipeServer
from agent.remote_sync import RemoteSync, enroll, load_cached_remote_policy
from agent.time_control import (
    F1Controller,
    PolicyError,
    SQLiteTimeStore,
    TimePolicy,
    load_time_policy,
)
from agent.web_protection import WebProtection

try:
    import win32event
    import win32service
    import win32serviceutil
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise RuntimeError("pywin32 is required to run the Windows service") from exc


SERVICE_NAME = "OpenGuardKidsAgentTest"
DISPLAY_NAME = "OpenGuard Kids Agent (Test)"
DESCRIPTION = "Visible OpenGuard Kids agent. The service stops when its Tray UI is unavailable."
TRAY_STARTUP_GRACE_SECONDS = 60.0
TRAY_WATCHDOG_POLL_SECONDS = 0.5
LOGGER = logging.getLogger(__name__)


def tray_watchdog_reason(
    *,
    elapsed_seconds: float,
    tray_was_seen: bool,
    tray_present: bool,
    startup_grace_seconds: float = TRAY_STARTUP_GRACE_SECONDS,
) -> str | None:
    """Return why the service must stop, or None while Tray presence is valid."""
    if tray_present:
        return None
    if tray_was_seen:
        return "tray heartbeat was lost"
    if elapsed_seconds >= startup_grace_seconds:
        return "Tray did not appear during service startup"
    return None


def f1_data_paths() -> tuple[Path, Path]:
    """Return the administrator-owned policy and state paths."""

    data_root = Path(
        os.environ.get("OGK_AGENT_DATA_DIR")
        or Path(os.environ.get("ProgramData", r"C:\ProgramData")) / "OpenGuardKids"
    )
    policy_path = Path(os.environ.get("OGK_F1_POLICY_PATH") or data_root / "f1-policy.json")
    return policy_path, data_root / "f1-state.db"


def remote_config_path() -> Path:
    policy_path, _ = f1_data_paths()
    return policy_path.parent / "remote-config.json"


def build_time_controller() -> F1Controller:
    policy_path, database_path = f1_data_paths()
    try:
        config_path = remote_config_path()
        if config_path.exists():
            policy = load_cached_remote_policy(
                config_path, config_path.with_name("remote-policy.json")
            )
        else:
            policy = load_time_policy(policy_path)
        policy_error = None
    except (PolicyError, ValueError, OSError, TypeError, KeyError) as exc:
        policy = TimePolicy.disabled()
        policy_error = str(exc)
    return F1Controller(
        policy,
        SQLiteTimeStore(database_path),
        policy_error=policy_error,
        reset_on_policy_version_change=not config_path.exists(),
    )


class ServiceRuntime:
    def __init__(self):
        config_path = remote_config_path()
        pairing_required = config_path.exists() or config_path.with_name("bootstrap.json").exists()
        self.core = AgentCore(
            time_controller=None if pairing_required else build_time_controller(),
            pairing_required=pairing_required,
        )
        self.core.set_enrollment_callback(self.enroll_device)
        self._enrollment_lock = threading.Lock()
        self._running = False
        self._shutdown_requested = threading.Event()
        self._watchdog_thread = None
        self.stop_reason = None
        self.tray_startup_grace_seconds = TRAY_STARTUP_GRACE_SECONDS
        self.tray_watchdog_poll_seconds = TRAY_WATCHDOG_POLL_SECONDS
        self.pipe = NamedPipeServer(self.core.handle)
        signed_policy_path = config_path.with_name("remote-policy.json")
        self.remote = None
        self.app_controller = AppController(self.core)
        self.dns_proxy = DNSProxy(self.core, upstream=os.getenv("OGK_DNS_UPSTREAM", "1.1.1.1"))
        self.dns_proxy_v6 = DNSProxy(
            self.core, host="::1", upstream=os.getenv("OGK_DNS_UPSTREAM", "1.1.1.1")
        )
        self.web_protection = WebProtection(
            self.core,
            config_path.with_name("network-backup.json"),
            ready=lambda: all(
                len(proxy.servers) == 2 and all(server.isAlive() for server in proxy.servers)
                for proxy in (self.dns_proxy, self.dns_proxy_v6)
            ),
        )
        if config_path.exists():
            self.core.mark_enrolled()
            try:
                self.remote = RemoteSync(self.core, config_path, signed_policy_path)
            except (ValueError, OSError, TypeError, KeyError) as exc:
                self.core.set_remote_status(connected=False, error=str(exc))

    def enroll_device(self, code: str) -> None:
        with self._enrollment_lock:
            config_path = remote_config_path()
            if config_path.exists() or self.remote is not None:
                raise ValueError("This device is already paired")
            bootstrap_path = config_path.with_name("bootstrap.json")
            bootstrap = json.loads(bootstrap_path.read_text(encoding="utf-8"))
            server_url = bootstrap["server_url"].rstrip("/")
            parsed = urlsplit(server_url)
            if (
                parsed.scheme != "https"
                and not (
                    parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}
                )
                and not (parsed.scheme == "http" and bootstrap.get("allow_insecure_http") is True)
            ):
                raise ValueError("A remote server must use HTTPS")
            enroll(
                config_path,
                server_url,
                code,
                bootstrap["device_name"],
                certificate_sha256=bootstrap.get("certificate_sha256", ""),
                allow_insecure_http=bootstrap.get("allow_insecure_http") is True,
            )
            self.remote = RemoteSync(
                self.core, config_path, config_path.with_name("remote-policy.json")
            )
            if self._running:
                self.remote.start()

    def _watch_for_visible_tray(self) -> None:
        started = time.monotonic()
        while not self._shutdown_requested.wait(self.tray_watchdog_poll_seconds):
            tray_was_seen, tray_present = self.core.tray_presence()
            reason = tray_watchdog_reason(
                elapsed_seconds=time.monotonic() - started,
                tray_was_seen=tray_was_seen,
                tray_present=tray_present,
                startup_grace_seconds=self.tray_startup_grace_seconds,
            )
            if reason is None:
                continue
            self.stop_reason = reason
            LOGGER.warning("Stopping OpenGuard Kids service: %s", reason)
            # Unblock serve_forever. Its finally block restores DNS and stops
            # all enforcement/synchronization workers before the service exits.
            self.pipe.stop()
            return

    def run(self) -> None:
        self._shutdown_requested.clear()
        self.stop_reason = None
        self._running = True
        self.app_controller.start()
        try:
            self.dns_proxy.start()
            self.dns_proxy_v6.start()
            self.web_protection.start()
        except OSError as exc:
            self.core._filtering_error = f"DNS proxy could not bind loopback port 53: {exc}"
            self.core._web_protection = "error"
            self.core._web_protection_error = str(exc)
            try:
                self.web_protection.restore()
            except (OSError, ValueError, RuntimeError) as restore_error:
                self.core._web_protection_error += f"; restore: {restore_error}"
        try:
            if self.remote is not None:
                self.remote.start()
            self._watchdog_thread = threading.Thread(
                target=self._watch_for_visible_tray,
                name="ogk-tray-watchdog",
                daemon=True,
            )
            self._watchdog_thread.start()
            self.pipe.serve_forever()
        finally:
            self._shutdown_requested.set()
            self._running = False
            self.app_controller.stop()
            try:
                self.web_protection.stop()
            finally:
                self.dns_proxy.stop()
                self.dns_proxy_v6.stop()
                if self.remote is not None:
                    self.remote.stop()
            if (
                self._watchdog_thread is not None
                and self._watchdog_thread is not threading.current_thread()
            ):
                self._watchdog_thread.join(timeout=2)

    def stop(self) -> None:
        self._shutdown_requested.set()
        self.pipe.stop()


class OpenGuardKidsAgentService(win32serviceutil.ServiceFramework):
    _svc_name_ = SERVICE_NAME
    _svc_display_name_ = DISPLAY_NAME
    _svc_description_ = DESCRIPTION

    def __init__(self, args):
        super().__init__(args)
        self.stop_event = win32event.CreateEvent(None, 0, 0, None)
        self.runtime = ServiceRuntime()

    def SvcStop(self):
        self.ReportServiceStatus(win32service.SERVICE_STOP_PENDING)
        self.runtime.stop()
        win32event.SetEvent(self.stop_event)

    def SvcDoRun(self):
        self.runtime.run()


def run_debug() -> int:
    runtime = ServiceRuntime()
    thread = threading.Thread(target=runtime.run, name="ogk-pipe", daemon=True)
    thread.start()
    print(f"{DISPLAY_NAME} is running in foreground mode.")
    policy_path, database_path = f1_data_paths()
    print(f"F1 policy: {policy_path}")
    print(f"F1 state: {database_path}")
    print(f"Remote config: {remote_config_path()}")
    print(
        "The visible Tray must start within 60 seconds and keep sending heartbeats; "
        "otherwise the service stops."
    )
    print("Press Ctrl+C to stop.")
    try:
        while thread.is_alive():
            thread.join(timeout=1)
    except KeyboardInterrupt:
        runtime.stop()
        thread.join(timeout=5)
    return 0


def run_ping() -> int:
    response = NamedPipeClient().request("ping")
    if not response.get("ok"):
        print(response)
        return 1
    print("Named-pipe check succeeded:", response["data"]["reply"])
    return 0


def run_service_dispatcher() -> None:
    import servicemanager

    servicemanager.Initialize()
    servicemanager.PrepareToHostSingle(OpenGuardKidsAgentService)
    servicemanager.StartServiceCtrlDispatcher()


def install_service() -> int:
    runner = Path(__file__).with_name("service_runner.py").resolve()
    win32serviceutil.InstallService(
        f"{__name__}.OpenGuardKidsAgentService",
        SERVICE_NAME,
        DISPLAY_NAME,
        startType=win32service.SERVICE_DEMAND_START,
        exeName=sys.executable,
        exeArgs=f'"{runner}"',
        description=DESCRIPTION,
    )
    print(f"Installed service {SERVICE_NAME}")
    return 0


def remove_service() -> int:
    win32serviceutil.RemoveService(SERVICE_NAME)
    print(f"Removed service {SERVICE_NAME}")
    return 0


def main() -> int:
    if os.name != "nt":
        raise SystemExit("The OpenGuard Kids Windows service can only run on Windows.")
    if len(sys.argv) > 1 and sys.argv[1] == "debug":
        return run_debug()
    if len(sys.argv) > 1 and sys.argv[1] == "ping":
        return run_ping()
    if len(sys.argv) > 1 and sys.argv[1] == "run-service":
        run_service_dispatcher()
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "install":
        return install_service()
    if len(sys.argv) > 1 and sys.argv[1] == "remove":
        return remove_service()
    if len(sys.argv) > 1 and sys.argv[1] == "start":
        win32serviceutil.StartService(SERVICE_NAME)
        return 0
    if len(sys.argv) > 1 and sys.argv[1] == "stop":
        win32serviceutil.StopService(SERVICE_NAME)
        return 0
    if len(sys.argv) <= 1:
        print("Use install, start, stop, remove, debug, or ping.")
        return 2
    print(f"Unknown command: {sys.argv[1]}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
