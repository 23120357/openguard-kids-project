from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    # Password whitespace is significant.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class ChildInput(Input):
    display_name: str = Field(min_length=1, max_length=80)
    pin: str = Field(pattern=r"^[0-9]{6}$")


class ChildPinInput(Input):
    pin: str = Field(pattern=r"^[0-9]{6}$")


class CodeInput(Input):
    child_id: str
    consent: bool


class EnrollInput(Input):
    code: str = Field(pattern=r"^[A-Z2-9]{8}$")
    display_name: str = Field(min_length=1, max_length=80)
    fingerprint: str = Field(min_length=16, max_length=128)


class RefreshInput(Input):
    device_id: str
    refresh_token: str = Field(min_length=1, max_length=128)


class HeartbeatInput(Input):
    policy_version: int = Field(ge=0)
    used_seconds: int = Field(default=0, ge=0)


class PolicyInput(Input):
    expected_version: int = Field(ge=1)
    weekday_minutes: int = Field(ge=1, le=1440)
    weekend_minutes: int = Field(ge=1, le=1440)
    enabled: bool = True
    schedule: list[str] = Field(default_factory=lambda: ["1" * 48] * 7)

    @field_validator("schedule")
    @classmethod
    def validate_schedule(cls, value: list[str]):
        if len(value) != 7 or any(len(row) != 48 or set(row) - {"0", "1"} for row in value):
            raise ValueError("schedule must contain seven rows of 48 zero/one slots")
        return value


class DeviceCommandInput(Input):
    command_type: Literal["lock_now", "add_time"]
    minutes: int | None = Field(default=None, ge=1, le=120)

    @field_validator("minutes")
    @classmethod
    def validate_minutes(cls, value: int | None, info):
        if info.data.get("command_type") == "add_time" and value is None:
            raise ValueError("minutes is required for add_time")
        return value


class DeviceSessionInput(Input):
    active_child_id: str | None = None
    active_user: str | None = Field(default=None, min_length=1, max_length=80)
    active_since: float | None = Field(default=None, ge=0)


class DeviceTimeStatusInput(Input):
    active_child_id: str | None = None
    active_user: str | None = Field(default=None, min_length=1, max_length=80)
    active_since: float | None = Field(default=None, ge=0)
    policy_version: int = Field(ge=0)
    used_seconds: int | None = Field(default=None, ge=0)
    remaining_seconds: int | None = Field(default=None, ge=0)
    quota_seconds: int | None = Field(default=None, ge=0)
    extra_seconds: int | None = Field(default=None, ge=0)
    active_usage: bool = False


class DeviceTimeRequestInput(Input):
    request_id: str = Field(min_length=1, max_length=80)
    child_id: str
    requester: str = Field(min_length=1, max_length=80)
    minutes: int = Field(ge=1, le=120)
    created_at: float = Field(ge=0)


class TimeRequestDecisionInput(Input):
    approved: bool
