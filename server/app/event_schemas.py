from typing import Literal
from uuid import UUID

from pydantic import Field, field_validator

from common.domains import domain_name, event_domain
from common.filter_categories import CATEGORY_LABELS, DEFAULT_ACTIONS

from .schemas import Input


class ActivityPayload(Input):
    ts: float = Field(ge=0, allow_inf_nan=False)
    device_id: str = Field(min_length=1, max_length=80)
    child_id: str = Field(min_length=1, max_length=80)
    type: Literal[
        "app_start",
        "app_stop",
        "domain_query",
        "blocked_app",
        "blocked_domain",
        "quota_warning",
        "locked",
        "unlock_request",
        "override_granted",
    ]
    subject: str = Field(min_length=1, max_length=253)
    duration_sec: int = Field(ge=0, le=90 * 86400)
    policy_id: str = Field(min_length=1, max_length=100)

    @field_validator("subject")
    @classmethod
    def minimal_subject(cls, value, info):
        if info.data.get("type") in {"domain_query", "blocked_domain"}:
            if domain_name(value) != event_domain(value):
                raise ValueError("Event subject must be a registrable domain")
        elif any(c in value for c in ("/", "\\", "\n", "\r")):
            raise ValueError("Event subject must not contain paths or content")
        return value


class Explanation(Input):
    reason: str = Field(default="", max_length=300)
    rule_author: str = Field(default="Phụ huynh", max_length=80)


class EventEnvelope(Input):
    id: UUID
    generation: int = Field(ge=0)
    event: ActivityPayload
    explanation: Explanation = Field(default_factory=Explanation)


class EventBatch(Input):
    events: list[EventEnvelope] = Field(min_length=1, max_length=100)


class GenerationAck(Input):
    generations: dict[str, int] = Field(max_length=100)


class AppRule(Input):
    name: str = Field(min_length=1, max_length=100, pattern=r"^[^/\\\r\n]+$")
    sha256: str = Field(pattern=r"^[a-fA-F0-9]{64}$")


class ObservedAppInput(AppRule):
    child_id: str = Field(min_length=1, max_length=80)


class ObservedAppBatch(Input):
    apps: list[ObservedAppInput] = Field(min_length=1, max_length=500)


class FilterRules(Input):
    enabled: bool = False
    dns_proxy_enabled: bool = True
    safe_search: bool = True
    category_overrides: dict[str, str] = Field(default_factory=dict, max_length=200)
    category_actions: dict[str, Literal["allow", "block"]] = Field(
        default_factory=lambda: dict(DEFAULT_ACTIONS), max_length=6
    )
    app_mode: Literal["blocklist", "allowlist"] = "blocklist"
    app_allow: list[AppRule] = Field(default_factory=list, max_length=200)
    app_block: list[AppRule] = Field(default_factory=list, max_length=200)
    domain_mode: Literal["blocklist", "allowlist"] = "blocklist"
    domain_allow: list[str] = Field(default_factory=list, max_length=500)
    domain_block: list[str] = Field(default_factory=list, max_length=500)
    safety_domains: list[str] = Field(default_factory=lambda: ["111.vn"], max_length=100)

    @field_validator("category_actions")
    @classmethod
    def categories(cls, value):
        if set(value) != set(CATEGORY_LABELS):
            raise ValueError("Provide exactly the six supported categories")
        return value

    @field_validator("category_overrides")
    @classmethod
    def custom_categories(cls, value):
        result = {}
        for host, category in value.items():
            normalized = domain_name(host)
            if category not in CATEGORY_LABELS or normalized in result:
                raise ValueError("Invalid category or duplicate normalized domain")
            result[normalized] = category
        return result

    @field_validator("domain_allow", "domain_block", "safety_domains")
    @classmethod
    def domains(cls, value):
        return sorted({domain_name(item) for item in value})


class FilterInput(FilterRules):
    expected_version: int = Field(ge=0)


class DomainPreview(Input):
    domain: str = Field(min_length=1, max_length=253)
    rules: FilterRules

    @field_validator("domain")
    @classmethod
    def valid_domain(cls, value):
        return domain_name(value)
