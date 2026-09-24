import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from agent.cache import PolicyCache
from server.app.schemas import ChildInput, EnrollInput, PolicyInput
from server.app.security import RateLimiter, digest, new_token, password_hasher, verify_password


def test_password_is_hashed_and_verified():
    password = "ExamplePassword123!"
    encoded = password_hasher.hash(password)
    assert encoded.startswith("$argon2id$")
    assert verify_password(encoded, password)
    assert not verify_password(encoded, "wrong")


def test_invalid_password_hash_is_rejected():
    assert not verify_password("invalid", "password")


def test_tokens_are_unique_and_hashed():
    first, second = new_token(), new_token()
    assert first != second
    assert len(first) >= 40
    assert digest(first) != first


@pytest.mark.parametrize("minutes", [0, -1, 1441])
def test_invalid_quota(minutes):
    with pytest.raises(ValidationError):
        PolicyInput(expected_version=1, weekday_minutes=minutes, weekend_minutes=90)


@pytest.mark.parametrize("name", ["", "   ", "a" * 81])
def test_invalid_child_name(name):
    with pytest.raises(ValidationError):
        ChildInput(display_name=name)


@pytest.mark.parametrize("code", ["SHORT", "abcdefgh", "00000000"])
def test_invalid_pairing_code(code):
    with pytest.raises(ValidationError):
        EnrollInput(code=code, display_name="PC", fingerprint="random-installation-id")


def test_input_rejects_unexpected_sensitive_fields():
    with pytest.raises(ValidationError):
        ChildInput(display_name="An", full_url="https://example.test/private")


def test_rate_limit():
    limiter = RateLimiter()
    limiter.check("ip", maximum=1)
    with pytest.raises(HTTPException) as error:
        limiter.check("ip", maximum=1)
    assert error.value.status_code == 429
    limiter.check("other-ip", maximum=1)


def test_cache_survives_restart(tmp_path):
    path = tmp_path / "cache.db"
    assert PolicyCache(path).load() is None
    PolicyCache(path).save({"version": 1})
    PolicyCache(path).save({"version": 2})
    assert PolicyCache(path).load() == {"version": 2}
