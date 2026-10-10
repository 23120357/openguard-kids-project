"""Installable Windows Service for OpenGuard Kids F1 time control."""

from __future__ import annotations

import json
import os
import sys
import threading
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

try:
    import win32event
    import win32service
    import win32serviceutil
except ImportError as exc:  # pragma: no cover - runtime dependency check
    raise RuntimeError("pywin32 is required to run the Windows service") from exc


SERVICE_NAME = "OpenGuardKidsAgentTest"
DISPLAY_NAME = "OpenGuard Kids Agent (Test)"
DESCRIPTION = (
    "Development service for visible OpenGuard Kids daily quotas, weekly schedules, "
    "idle-aware usage accounting, and local Tray UI communication."
)


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
        self.pipe = NamedPipeServer(self.core.handle)
        signed_policy_path = config_path.with_name("remote-policy.json")
        self.remote = None
        self.app_controller = AppController(self.core)
        self.dns_proxy = DNSProxy(self.core, upstream=os.getenv("OGK_DNS_UPSTREAM", "1.1.1.1"))
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
            enroll(config_path, server_url, code, bootstrap["device_name"])
            self.remote = RemoteSync(
                self.core, config_path, config_path.with_name("remote-policy.json")
            )
            if self._running:
                self.remote.start()

    def run(self) -> None:
        self._running = True
        self.app_controller.start()
        try:
            self.dns_proxy.start()
        except OSError as exc:
            self.core._filtering_error = f"DNS proxy could not bind 127.0.0.1:53: {exc}"
        if self.remote is not None:
            self.remote.start()
        try:
            self.pipe.serve_forever()
        finally:
            self._running = False
            self.app_controller.stop()
            self.dns_proxy.stop()
            if self.remote is not None:
                self.remote.stop()

    def stop(self) -> None:
        self.pipe.stop()
        self.app_controller.stop()
        if self.remote is not None:
            self.remote.stop()


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
    print("The visible Tray must be running before time accounting or locking can occur.")
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
