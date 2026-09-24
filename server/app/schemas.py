from pydantic import BaseModel, ConfigDict, Field


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Login(Input):
    # Password whitespace is significant.
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=False)
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class ChildInput(Input):
    display_name: str = Field(min_length=1, max_length=80)


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


class PolicyInput(Input):
    expected_version: int = Field(ge=1)
    weekday_minutes: int = Field(ge=1, le=1440)
    weekend_minutes: int = Field(ge=1, le=1440)
