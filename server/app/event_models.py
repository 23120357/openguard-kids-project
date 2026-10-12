"""F3 activity and deletion fences; existing policies/accounts stay usable."""

from sqlalchemy import JSON, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from .models import Base


class ActivityEvent(Base):
    __tablename__ = "activity_events"
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id"), index=True)
    ts: Mapped[float] = mapped_column(index=True)
    generation: Mapped[int]
    payload: Mapped[dict] = mapped_column(JSON)
    reason: Mapped[str] = mapped_column(String(300))
    rule_author: Mapped[str] = mapped_column(String(80))


class EventGeneration(Base):
    __tablename__ = "event_generations"
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id"), primary_key=True)
    generation: Mapped[int] = mapped_column(default=0)


class EventDeletionAck(Base):
    __tablename__ = "event_deletion_acks"
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id"), primary_key=True)
    generation: Mapped[int]


class FilteringPolicy(Base):
    __tablename__ = "filtering_policies"
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id"), primary_key=True)
    version: Mapped[int] = mapped_column(default=1)
    rules: Mapped[dict] = mapped_column(JSON)


class ObservedApp(Base):
    """Minimal executable identity reported by an enrolled device.

    Paths are deliberately not collected. The digest is retained only so a
    parent can create an exact allow/block rule without handling it manually.
    """

    __tablename__ = "observed_apps"
    device_id: Mapped[str] = mapped_column(ForeignKey("devices.id"), primary_key=True)
    child_id: Mapped[str] = mapped_column(ForeignKey("children.id"), primary_key=True)
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    last_seen: Mapped[float]
