import time
import uuid

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def new_id():
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Parent(Base):
    __tablename__ = "parents"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(254), unique=True)
    password_hash: Mapped[str]
    failed_attempts: Mapped[int] = mapped_column(default=0)
    locked_until: Mapped[float] = mapped_column(default=0)


class ParentSession(Base):
    __tablename__ = "parent_sessions"
    token_hash: Mapped[str] = mapped_column(primary_key=True)
    parent_id: Mapped[str] = mapped_column(ForeignKey("parents.id"))
    csrf_token: Mapped[str]
    expires_at: Mapped[float]


class Child(Base):
    __tablename__ = "children"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    parent_id: Mapped[str] = mapped_column(ForeignKey("parents.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    pin_hash: Mapped[str | None] = mapped_column(String(255))


class Policy(Base):
    __tablename__ = "policies"
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id"), primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    weekday_minutes: Mapped[int] = mapped_column(default=90)
    weekend_minutes: Mapped[int] = mapped_column(default=120)
    enabled: Mapped[bool] = mapped_column(default=True)
    schedule: Mapped[list] = mapped_column(JSON, default=lambda: ["1" * 48] * 7)
    updated_at: Mapped[float] = mapped_column(default=time.time)


class EnrollmentCode(Base):
    __tablename__ = "enrollment_codes"
    code_hash: Mapped[str] = mapped_column(primary_key=True)
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id"))
    expires_at: Mapped[float]
    consent_at: Mapped[float] = mapped_column(default=time.time)


class Device(Base):
    __tablename__ = "devices"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id"), index=True)
    display_name: Mapped[str] = mapped_column(String(80))
    # Random installation identifier, not hardware inventory.
    fingerprint: Mapped[str]
    policy_signing_key: Mapped[str | None] = mapped_column(String(128))
    access_hash: Mapped[str] = mapped_column(unique=True)
    access_expires_at: Mapped[float]
    refresh_hash: Mapped[str] = mapped_column(unique=True)
    refresh_expires_at: Mapped[float]
    last_seen: Mapped[float | None]
    policy_version: Mapped[int] = mapped_column(default=0)
    revoked: Mapped[bool] = mapped_column(default=False)
    active_user: Mapped[str | None] = mapped_column(String(80))
    active_child_id: Mapped[str | None] = mapped_column(ForeignKey("children.id"))
    active_since: Mapped[float | None]
    used_seconds: Mapped[int | None]
    remaining_seconds: Mapped[int | None]
    quota_seconds: Mapped[int | None]
    extra_seconds: Mapped[int | None]
    active_usage: Mapped[bool] = mapped_column(default=False)
    time_status_at: Mapped[float | None]


class Audit(Base):
    __tablename__ = "audit"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    parent_id: Mapped[str] = mapped_column(ForeignKey("parents.id"), index=True)
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id"))
    action: Mapped[str]
    ts: Mapped[float] = mapped_column(default=time.time)
    ip: Mapped[str]
    old_value: Mapped[dict] = mapped_column(JSON)
    new_value: Mapped[dict] = mapped_column(JSON)


class DeviceCommand(Base):
    __tablename__ = "device_commands"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id"), index=True)
    parent_id: Mapped[str] = mapped_column(ForeignKey("parents.id"), index=True)
    command_type: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[float] = mapped_column(default=time.time)
    delivered_at: Mapped[float | None]
    acknowledged_at: Mapped[float | None]


class TimeRequest(Base):
    __tablename__ = "time_requests"
    id: Mapped[str] = mapped_column(primary_key=True, default=new_id)
    client_request_id: Mapped[str] = mapped_column(String(80), unique=True)
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), index=True)
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id"), index=True)
    requester: Mapped[str] = mapped_column(String(80))
    minutes: Mapped[int]
    status: Mapped[str] = mapped_column(String(20), default="pending")
    created_at: Mapped[float] = mapped_column(default=time.time)
    decided_at: Mapped[float | None]
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("parents.id"))
