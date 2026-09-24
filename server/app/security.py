import hashlib
import secrets
from collections import defaultdict, deque
from threading import Lock
from time import monotonic

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError
from fastapi import HTTPException

password_hasher = PasswordHasher()


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


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
