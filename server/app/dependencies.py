import secrets
import time
from typing import Annotated

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Child, Device, ParentSession
from .security import digest


def database(request: Request):
    with request.app.state.sessions() as session:
        yield session


DB = Annotated[Session, Depends(database)]


def current_parent(request: Request, db: DB):
    token = request.cookies.get("ogk_session", "")
    session = db.get(ParentSession, digest(token))
    if not session or session.expires_at <= time.time():
        raise HTTPException(401, "Please sign in")
    if request.method not in ("GET", "HEAD", "OPTIONS") and not secrets.compare_digest(
        request.headers.get("x-csrf-token", ""), session.csrf_token
    ):
        raise HTTPException(403, "Invalid CSRF token")
    return session


ParentAuth = Annotated[ParentSession, Depends(current_parent)]


def owned_child(db: Session, child_id: str, parent_id: str):
    child = db.scalar(select(Child).where(Child.id == child_id, Child.parent_id == parent_id))
    if child is None:
        raise HTTPException(404, "Child not found")
    return child


def current_device(request: Request, db: DB):
    scheme, _, token = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(401, "Device token required")
    device = db.scalar(select(Device).where(Device.access_hash == digest(token)))
    if not device or device.revoked or device.access_expires_at <= time.time():
        raise HTTPException(401, "Invalid or expired device token")
    return device


DeviceAuth = Annotated[Device, Depends(current_device)]
