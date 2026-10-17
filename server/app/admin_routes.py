"""Separate, development-gated administrator authentication and metadata API."""

import secrets
import time

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import delete, func, select

from .dependencies import DB, AdminAuth
from .models import AdminSession, AdminUser, Child, Device, Parent
from .schemas import AdminLogin
from .security import digest, new_token, password_hasher, verify_password

router = APIRouter(prefix="/api/admin")
DUMMY_HASH = password_hasher.hash(new_token())


def _require_enabled(request: Request) -> None:
    if not request.app.state.settings.admin_enabled:
        raise HTTPException(404, "Not found")


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.post("/auth/login")
def login(body: AdminLogin, request: Request, response: Response, db: DB):
    _require_enabled(request)
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(403, "Cross-origin login denied")
    request.app.state.limiter.check("admin-login:" + _client_ip(request), maximum=10)
    admin = db.scalar(select(AdminUser).where(AdminUser.email == body.email.strip().lower()))
    valid = verify_password(admin.password_hash if admin else DUMMY_HASH, body.password)
    now = time.time()
    if admin and admin.locked_until > now:
        raise HTTPException(401, "Invalid credentials or account temporarily locked")
    if not admin or not valid:
        if admin:
            admin.failed_attempts += 1
            if admin.failed_attempts >= 5:
                admin.locked_until = now + 900
            db.commit()
        raise HTTPException(401, "Invalid credentials or account temporarily locked")
    admin.failed_attempts, admin.locked_until = 0, 0
    db.execute(delete(AdminSession).where(AdminSession.expires_at <= now))
    token, csrf = new_token(), secrets.token_urlsafe(24)
    db.add(
        AdminSession(
            token_hash=digest(token), admin_id=admin.id, csrf_token=csrf, expires_at=now + 3600
        )
    )
    db.commit()
    response.set_cookie(
        "ogk_admin_session",
        token,
        httponly=True,
        secure=request.app.state.settings.cookie_secure or request.url.scheme == "https",
        samesite="strict",
        max_age=3600,
        path="/api/admin",
    )
    return {"email": admin.email, "role": "admin", "csrf_token": csrf}


@router.get("/auth/me")
def me(auth: AdminAuth, db: DB):
    admin = db.get(AdminUser, auth.admin_id)
    return {"email": admin.email, "role": "admin", "csrf_token": auth.csrf_token}


@router.post("/auth/logout", status_code=204)
def logout(auth: AdminAuth, db: DB, response: Response):
    db.delete(auth)
    db.commit()
    response.delete_cookie("ogk_admin_session", path="/api/admin")


@router.get("/overview")
def overview(auth: AdminAuth, db: DB):
    """Operational metadata only; no child names, activity subjects or secrets."""

    return {
        "role": "admin",
        "parents": db.scalar(select(func.count()).select_from(Parent)),
        "children": db.scalar(select(func.count()).select_from(Child)),
        "devices": db.scalar(select(func.count()).select_from(Device)),
        "revoked_devices": db.scalar(
            select(func.count()).select_from(Device).where(Device.revoked.is_(True))
        ),
    }
