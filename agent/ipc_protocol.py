"""Versioned messages shared by the OpenGuard Kids service and Tray UI."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

PROTOCOL_VERSION = 1
MAX_MESSAGE_BYTES = 64 * 1024
PIPE_NAME = r"\\.\pipe\OpenGuardKids.Agent.v1"


class ProtocolError(ValueError):
    """Raised when a local IPC message does not match the protocol."""


@dataclass(frozen=True)
class Request:
    request_id: str
    message_type: str
    payload: dict[str, Any]


def new_request(message_type: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": str(uuid.uuid4()),
        "type": message_type,
        "payload": payload or {},
    }


def encode_message(message: dict[str, Any]) -> bytes:
    try:
        encoded = json.dumps(
            message,
            ensure_ascii=False,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ProtocolError("Message is not valid JSON data") from exc
    if len(encoded) > MAX_MESSAGE_BYTES:
        raise ProtocolError("Message exceeds the local IPC size limit")
    return encoded


def decode_message(raw: bytes) -> dict[str, Any]:
    if not raw or len(raw) > MAX_MESSAGE_BYTES:
        raise ProtocolError("Message is empty or exceeds the local IPC size limit")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProtocolError("Message is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict):
        raise ProtocolError("Message must be a JSON object")
    return value


def parse_request(message: dict[str, Any]) -> Request:
    if message.get("protocol_version") != PROTOCOL_VERSION:
        raise ProtocolError("Unsupported protocol version")
    request_id = message.get("request_id")
    message_type = message.get("type")
    payload = message.get("payload", {})
    if not isinstance(request_id, str) or not request_id or len(request_id) > 80:
        raise ProtocolError("request_id must be a non-empty string")
    if not isinstance(message_type, str) or not message_type or len(message_type) > 64:
        raise ProtocolError("type must be a non-empty string")
    if not isinstance(payload, dict):
        raise ProtocolError("payload must be an object")
    return Request(request_id=request_id, message_type=message_type, payload=payload)


def success_response(request_id: str, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "ok": True,
        "data": data,
    }


def error_response(request_id: str, code: str, message: str) -> dict[str, Any]:
    return {
        "protocol_version": PROTOCOL_VERSION,
        "request_id": request_id,
        "ok": False,
        "error": {"code": code, "message": message},
    }
