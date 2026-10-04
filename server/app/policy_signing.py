"""Canonical F4 policy signing shared by server and agent tests."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any


def canonical_policy(policy: dict[str, Any]) -> bytes:
    return json.dumps(
        policy,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def sign_policy(policy: dict[str, Any], key: str) -> str:
    return hmac.new(key.encode("utf-8"), canonical_policy(policy), hashlib.sha256).hexdigest()


def verify_policy(policy: dict[str, Any], signature: str, key: str) -> bool:
    if not isinstance(signature, str):
        return False
    return hmac.compare_digest(sign_policy(policy, key), signature)
