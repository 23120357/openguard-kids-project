"""Local-only Windows named-pipe transport for the agent and Tray UI."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from typing import Any

from agent.ipc_protocol import (
    MAX_MESSAGE_BYTES,
    PIPE_NAME,
    ProtocolError,
    decode_message,
    encode_message,
    error_response,
    new_request,
)

try:
    import pywintypes
    import win32api
    import win32file
    import win32pipe
    import win32security
except ImportError as exc:  # pragma: no cover - exercised by runtime dependency checks
    raise RuntimeError("pywin32 is required for Windows named-pipe support") from exc


ERROR_PIPE_CONNECTED = 535
PIPE_REJECT_REMOTE_CLIENTS = getattr(win32pipe, "PIPE_REJECT_REMOTE_CLIENTS", 0x00000008)
LOGGER = logging.getLogger(__name__)


class PipeUnavailableError(ConnectionError):
    """Raised when the Windows service pipe is not available."""


def _security_attributes():
    # SYSTEM, Administrators, and local users have pipe access;
    # PIPE_REJECT_REMOTE_CLIENTS keeps the endpoint machine-local. Operation-level
    # validation is still required because multiple local sessions may connect.
    descriptor = win32security.ConvertStringSecurityDescriptorToSecurityDescriptor(
        "D:P(A;;GA;;;SY)(A;;GA;;;BA)(A;;GA;;;WD)",
        win32security.SDDL_REVISION_1,
    )
    attributes = pywintypes.SECURITY_ATTRIBUTES()
    attributes.SECURITY_DESCRIPTOR = descriptor
    return attributes


class NamedPipeServer:
    def __init__(self, handler: Callable[[dict[str, Any]], dict[str, Any]]):
        self._handler = handler
        self._stopping = threading.Event()

    def serve_forever(self) -> None:
        while not self._stopping.is_set():
            pipe = win32pipe.CreateNamedPipe(
                PIPE_NAME,
                win32pipe.PIPE_ACCESS_DUPLEX,
                win32pipe.PIPE_TYPE_MESSAGE
                | win32pipe.PIPE_READMODE_MESSAGE
                | win32pipe.PIPE_WAIT
                | PIPE_REJECT_REMOTE_CLIENTS,
                4,
                MAX_MESSAGE_BYTES,
                MAX_MESSAGE_BYTES,
                1000,
                _security_attributes(),
            )
            try:
                try:
                    win32pipe.ConnectNamedPipe(pipe, None)
                except pywintypes.error as exc:
                    if exc.winerror != ERROR_PIPE_CONNECTED:
                        raise
                if self._stopping.is_set():
                    continue
                self._serve_client(pipe)
            finally:
                try:
                    win32pipe.DisconnectNamedPipe(pipe)
                except pywintypes.error:
                    pass
                win32file.CloseHandle(pipe)

    def _serve_client(self, pipe) -> None:
        request_id = "unknown"
        try:
            _, raw = win32file.ReadFile(pipe, MAX_MESSAGE_BYTES + 1)
            message = decode_message(raw)
            if message.get("type") == "ui_heartbeat" and isinstance(message.get("payload"), dict):
                # Session-scoped app enforcement uses the real pipe caller PID.
                message["payload"]["process_id"] = win32pipe.GetNamedPipeClientProcessId(pipe)
            request_id = str(message.get("request_id", "unknown"))[:80]
            response = self._handler(message)
        except ProtocolError as exc:
            response = error_response(request_id, "invalid_message", str(exc))
        except Exception:
            LOGGER.exception("Unexpected error while processing a local pipe request")
            response = error_response(
                request_id, "internal_error", "The service could not process the request"
            )
        try:
            encoded = encode_message(response)
        except ProtocolError:
            LOGGER.error(
                "Local pipe response exceeded the message limit; service remains available"
            )
            encoded = encode_message(
                error_response(
                    request_id, "response_too_large", "The service response is too large"
                )
            )
        try:
            win32file.WriteFile(pipe, encoded)
            win32file.FlushFileBuffers(pipe)
        except pywintypes.error:
            LOGGER.debug(
                "Local pipe client disconnected before receiving a response", exc_info=True
            )

    def stop(self) -> None:
        self._stopping.set()
        try:
            NamedPipeClient(timeout_ms=250).request("ping")
        except PipeUnavailableError:
            pass


class NamedPipeClient:
    def __init__(self, *, timeout_ms: int = 1500):
        self.timeout_ms = timeout_ms

    def request(self, message_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        message = new_request(message_type, payload)
        try:
            win32pipe.WaitNamedPipe(PIPE_NAME, self.timeout_ms)
            pipe = win32file.CreateFile(
                PIPE_NAME,
                win32file.GENERIC_READ | win32file.GENERIC_WRITE,
                0,
                None,
                win32file.OPEN_EXISTING,
                0,
                None,
            )
        except pywintypes.error as exc:
            raise PipeUnavailableError("OpenGuard Kids service is unavailable") from exc
        try:
            win32pipe.SetNamedPipeHandleState(pipe, win32pipe.PIPE_READMODE_MESSAGE, None, None)
            win32file.WriteFile(pipe, encode_message(message))
            _, raw = win32file.ReadFile(pipe, MAX_MESSAGE_BYTES + 1)
            response = decode_message(raw)
        except (pywintypes.error, ProtocolError) as exc:
            raise PipeUnavailableError("The service pipe connection failed") from exc
        finally:
            win32file.CloseHandle(pipe)
        if response.get("request_id") != message["request_id"]:
            raise PipeUnavailableError("The service returned an unmatched response")
        return response


def current_process_id() -> int:
    return win32api.GetCurrentProcessId()
