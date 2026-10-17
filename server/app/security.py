import base64
import hashlib
import secrets
from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import HTTPException

password_hasher = PasswordHasher()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


class FieldCipher:
    """AES-GCM envelope for sensitive database values."""

    PREFIX = "enc:v1:"

    def __init__(self, encoded_key: str):
        try:
            key = base64.urlsafe_b64decode(encoded_key + "=" * (-len(encoded_key) % 4))
        except (ValueError, TypeError) as exc:
            raise ValueError("OGK_DATA_ENCRYPTION_KEY must be URL-safe base64") from exc
        if len(key) != 32:
            raise ValueError("OGK_DATA_ENCRYPTION_KEY must decode to exactly 32 bytes")
        self._cipher = AESGCM(key)

    def encrypt(self, value: str, *, purpose: str) -> str:
        nonce = secrets.token_bytes(12)
        encrypted = self._cipher.encrypt(nonce, value.encode(), purpose.encode())
        return self.PREFIX + base64.urlsafe_b64encode(nonce + encrypted).decode().rstrip("=")

    def decrypt(self, value: str, *, purpose: str) -> str:
        if not value.startswith(self.PREFIX):
            return value
        encoded = value[len(self.PREFIX) :]
        try:
            payload = base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4))
            return self._cipher.decrypt(payload[:12], payload[12:], purpose.encode()).decode()
        except (InvalidTag, ValueError, TypeError) as exc:
            raise ValueError("Encrypted database value failed authentication") from exc


def verify_password(encoded: str, plain: str) -> bool:
    try:
        return password_hasher.verify(encoded, plain)
    except (VerificationError, InvalidHashError):
        return False


class RateLimiter:
    """Single-process development limiter. Replace before multi-worker deployment."""

    def __init__(self):
        self.attempts = defaultdict(deque)
        self.lock = Lock()

    def check(self, key: str, maximum: int = 20, period: int = 60):
        now = monotonic()
        with self.lock:
            for old_key in list(self.attempts):
                if not self.attempts[old_key] or self.attempts[old_key][-1] <= now - period:
                    del self.attempts[old_key]
            queue = self.attempts[key]
            while queue and queue[0] <= now - period:
                queue.popleft()
            if len(queue) >= maximum:
                raise HTTPException(429, "Too many attempts. Try again later.")
            queue.append(now)
