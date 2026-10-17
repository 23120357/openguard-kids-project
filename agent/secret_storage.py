"""Windows DPAPI storage for device credentials and signing material."""

from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

FORMAT = "dpapi-local-machine-v1"
DESCRIPTION = "OpenGuard Kids device credentials"
ENTROPY = b"OpenGuardKids/remote-config/v1"


def _win32crypt():
    if os.name != "nt":
        raise OSError("Device credentials require Windows DPAPI")
    try:
        import win32crypt
    except ImportError as exc:
        raise OSError("pywin32 is required for Windows DPAPI") from exc
    return win32crypt


def is_protected_document(value: Any) -> bool:
    return isinstance(value, dict) and value.get("format") == FORMAT and "blob" in value


def protect_json(value: dict[str, Any]) -> dict[str, str]:
    raw = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    win32crypt = _win32crypt()
    encrypted = win32crypt.CryptProtectData(
        raw,
        DESCRIPTION,
        ENTROPY,
        None,
        None,
        0x5,  # CRYPTPROTECT_UI_FORBIDDEN | CRYPTPROTECT_LOCAL_MACHINE
    )
    return {"format": FORMAT, "blob": base64.b64encode(encrypted).decode("ascii")}


def unprotect_json(value: dict[str, Any]) -> dict[str, Any]:
    if not is_protected_document(value):
        raise ValueError("Unsupported protected configuration format")
    try:
        encrypted = base64.b64decode(value["blob"], validate=True)
        win32crypt = _win32crypt()
        _, raw = win32crypt.CryptUnprotectData(encrypted, ENTROPY, None, None, 0x1)
        result = json.loads(raw.decode("utf-8"))
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Protected device configuration could not be decrypted") from exc
    if not isinstance(result, dict):
        raise TypeError("Protected device configuration is not an object")
    return result


def load_json(path: str | Path) -> tuple[dict[str, Any], bool]:
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if is_protected_document(document):
        return unprotect_json(document), True
    if not isinstance(document, dict):
        raise TypeError("Device configuration is not an object")
    return document, False


def save_json(path: str | Path, value: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + ".tmp")
    temporary.write_text(
        json.dumps(protect_json(value), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    os.replace(temporary, target)
