import secrets
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import delete, select, update

from .dependencies import DB, DeviceAuth, ParentAuth, owned_child
from .models import Audit, Child, Device, EnrollmentCode, Parent, ParentSession, Policy
from .schemas import (
    ChildInput,
    CodeInput,
    EnrollInput,
    HeartbeatInput,
    Login,
    PolicyInput,
    RefreshInput,
)
from .security import digest, new_token, password_hasher, verify_password

router = APIRouter(prefix="/api")
# Equalize password hashing work for unknown accounts.
DUMMY_HASH = password_hasher.hash(new_token())


def policy_data(policy):
    return {
        "child_id": policy.child_id,
        "version": policy.version,
        "weekday_minutes": policy.weekday_minutes,
        "weekend_minutes": policy.weekend_minutes,
    }


def client_ip(request):
    return request.client.host if request.client else "unknown"


def issue_device_tokens(device):
    access, refresh = new_token(), new_token()
    now = time.time()
    device.access_hash, device.refresh_hash = digest(access), digest(refresh)
    device.access_expires_at = now + 900
    device.refresh_expires_at = now + 30 * 86400
    return {
        "device_id": device.id,
        "access_token": access,
        "refresh_token": refresh,
        "token_type": "bearer",
        "expires_in": 900,
    }


@router.get("/health")
def health():
    return {"status": "ok", "mode": "development-scaffold"}


@router.post("/auth/login")
def login(body: Login, request: Request, response: Response, db: DB):
    # JSON-only login plus Origin check prevent cross-site login requests.
    origin = request.headers.get("origin")
    if origin and origin != f"{request.url.scheme}://{request.url.netloc}":
        raise HTTPException(403, "Cross-origin login denied")
    if urlsplit(str(request.url)).scheme not in ("http", "https"):
        raise HTTPException(400, "Invalid request URL")
    request.app.state.limiter.check("login:" + client_ip(request))
    parent = db.scalar(select(Parent).where(Parent.email == body.email.strip().lower()))
    valid = verify_password(parent.password_hash if parent else DUMMY_HASH, body.password)
    now = time.time()
    if parent and parent.locked_until > now:
        raise HTTPException(401, "Invalid credentials or account temporarily locked")
    if not parent or not valid:
        if parent:
            if parent.locked_until:
                parent.failed_attempts = 0
                parent.locked_until = 0
            parent.failed_attempts += 1
            if parent.failed_attempts >= 5:
                parent.locked_until = now + 900
            db.commit()
        raise HTTPException(401, "Invalid credentials or account temporarily locked")
    parent.failed_attempts, parent.locked_until = 0, 0
    # Rotate an existing browser session at login.
    old = request.cookies.get("ogk_session")
    if old:
        db.execute(delete(ParentSession).where(ParentSession.token_hash == digest(old)))
    db.execute(delete(ParentSession).where(ParentSession.expires_at <= now))
    token, csrf = new_token(), new_token()
    db.add(
        ParentSession(
            token_hash=digest(token),
            parent_id=parent.id,
            csrf_token=csrf,
            expires_at=now + 43200,
        )
    )
    db.commit()
    response.set_cookie(
        "ogk_session",
        token,
        httponly=True,
        secure=request.app.state.settings.cookie_secure,
        samesite="lax",
        max_age=43200,
        path="/",
    )
    response.headers["Cache-Control"] = "no-store"
    return {"email": parent.email, "csrf_token": csrf}


@router.get("/auth/me")
def me(auth: ParentAuth, db: DB):
    return {"email": db.get(Parent, auth.parent_id).email, "csrf_token": auth.csrf_token}


@router.post("/auth/logout", status_code=204)
def logout(auth: ParentAuth, db: DB, response: Response):
    db.delete(auth)
    db.commit()
    response.delete_cookie("ogk_session", path="/")


@router.get("/children")
def children(auth: ParentAuth, db: DB):
    rows = db.scalars(select(Child).where(Child.parent_id == auth.parent_id)).all()
    return [{"id": row.id, "display_name": row.display_name} for row in rows]


@router.post("/children", status_code=201)
def create_child(body: ChildInput, auth: ParentAuth, db: DB):
    child = Child(parent_id=auth.parent_id, display_name=body.display_name)
    db.add(child)
    db.flush()
    db.add(Policy(child_id=child.id))
    db.commit()
    return {"id": child.id, "display_name": child.display_name}


@router.post("/enrollment-codes", status_code=201)
def create_code(body: CodeInput, request: Request, auth: ParentAuth, db: DB):
    owned_child(db, body.child_id, auth.parent_id)
    if not body.consent:
        raise HTTPException(422, "Explicit parent consent is required")
    request.app.state.limiter.check("code:" + auth.parent_id)
    code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
    expires = time.time() + 600
    db.execute(delete(EnrollmentCode).where(EnrollmentCode.child_id == body.child_id))
    db.add(EnrollmentCode(code_hash=digest(code), child_id=body.child_id, expires_at=expires))
    db.add(
        Audit(
            parent_id=auth.parent_id,
            child_id=body.child_id,
            action="enrollment_consent",
            ip=client_ip(request),
            old_value={},
            new_value={"consent": True},
        )
    )
    db.commit()
    return {"code": code, "expires_at": expires}


@router.post("/enroll", status_code=201)
def enroll(body: EnrollInput, request: Request, db: DB):
    request.app.state.limiter.check("enroll:" + client_ip(request), maximum=10)
    # DELETE ... RETURNING makes consuming a single-use code atomic.
    child_id = db.scalar(
        delete(EnrollmentCode)
        .where(
            EnrollmentCode.code_hash == digest(body.code),
            EnrollmentCode.expires_at > time.time(),
        )
        .returning(EnrollmentCode.child_id)
    )
    if child_id is None:
        raise HTTPException(400, "Invalid or expired enrollment code")
    device = Device(
        child_id=child_id,
        display_name=body.display_name,
        fingerprint=digest(body.fingerprint),
        access_hash="",
        refresh_hash="",
        access_expires_at=0,
        refresh_expires_at=0,
    )
    result = issue_device_tokens(device)
    db.add(device)
    db.flush()
    result["device_id"] = device.id
    db.commit()
    return result


@router.post("/auth/device/refresh")
def refresh(body: RefreshInput, request: Request, db: DB):
    request.app.state.limiter.check("refresh:" + client_ip(request), maximum=60)
    access, refresh_token = new_token(), new_token()
    now = time.time()
    result = db.execute(
        update(Device)
        .where(
            Device.id == body.device_id,
            Device.refresh_hash == digest(body.refresh_token),
            Device.refresh_expires_at > now,
            Device.revoked.is_(False),
        )
        .values(
            access_hash=digest(access),
            access_expires_at=now + 900,
            refresh_hash=digest(refresh_token),
            refresh_expires_at=now + 30 * 86400,
        )
    )
    if result.rowcount != 1:
        raise HTTPException(401, "Invalid or expired refresh token")
    db.commit()
    return {
        "device_id": body.device_id,
        "access_token": access,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in": 900,
    }


@router.post("/heartbeat")
def heartbeat(body: HeartbeatInput, device: DeviceAuth, db: DB):
    device.last_seen = time.time()
    device.policy_version = body.policy_version
    policy = db.get(Policy, device.child_id)
    db.commit()
    return {"server_time": device.last_seen, "policy_version": policy.version, "commands": []}


@router.get("/policy")
def device_policy(device: DeviceAuth, db: DB):
    return policy_data(db.get(Policy, device.child_id))


@router.get("/children/{child_id}/policy")
def parent_policy(child_id: str, auth: ParentAuth, db: DB):
    owned_child(db, child_id, auth.parent_id)
    return policy_data(db.get(Policy, child_id))


@router.put("/children/{child_id}/policy")
def update_policy(child_id: str, body: PolicyInput, request: Request, auth: ParentAuth, db: DB):
    owned_child(db, child_id, auth.parent_id)
    policy = db.get(Policy, child_id)
    old = policy_data(policy)
    result = db.execute(
        update(Policy)
        .where(
            Policy.child_id == child_id,
            Policy.version == body.expected_version,
        )
        .values(
            version=Policy.version + 1,
            weekday_minutes=body.weekday_minutes,
            weekend_minutes=body.weekend_minutes,
        )
    )
    if result.rowcount != 1:
        raise HTTPException(409, "Policy changed. Reload before editing.")
    db.refresh(policy)
    new = policy_data(policy)
    db.add(
        Audit(
            parent_id=auth.parent_id,
            child_id=child_id,
            action="policy_updated",
            ip=client_ip(request),
            old_value=old,
            new_value=new,
        )
    )
    db.commit()
    return new


@router.get("/devices")
def devices(auth: ParentAuth, db: DB):
    rows = db.scalars(select(Device).join(Child).where(Child.parent_id == auth.parent_id)).all()
    now = time.time()
    return [
        {
            "id": row.id,
            "child_id": row.child_id,
            "display_name": row.display_name,
            "last_seen": row.last_seen,
            "policy_version": row.policy_version,
            "online": bool(not row.revoked and row.last_seen and now - row.last_seen < 120),
        }
        for row in rows
    ]


@router.get("/audit")
def audits(auth: ParentAuth, db: DB):
    rows = db.scalars(
        select(Audit)
        .where(
            Audit.parent_id == auth.parent_id,
        )
        .order_by(Audit.ts.desc())
        .limit(100)
    ).all()
    return [
        {
            "id": row.id,
            "child_id": row.child_id,
            "action": row.action,
            "ts": row.ts,
            "ip": row.ip,
            "old_value": row.old_value,
            "new_value": row.new_value,
        }
        for row in rows
    ]
