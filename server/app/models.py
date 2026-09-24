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


class Policy(Base):
    __tablename__ = "policies"
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id"), primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    weekday_minutes: Mapped[int] = mapped_column(default=90)
    weekend_minutes: Mapped[int] = mapped_column(default=120)


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
    access_hash: Mapped[str] = mapped_column(unique=True)
    access_expires_at: Mapped[float]
    refresh_hash: Mapped[str] = mapped_column(unique=True)
    refresh_expires_at: Mapped[float]
    last_seen: Mapped[float | None]
    policy_version: Mapped[int] = mapped_column(default=0)
    revoked: Mapped[bool] = mapped_column(default=False)


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
