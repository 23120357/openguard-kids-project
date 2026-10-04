import asyncio
import json
import secrets
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import StreamingResponse
from sqlalchemy import delete, select, update

from .dependencies import DB, DeviceAuth, ParentAuth, owned_child
from .models import (
    Audit,
    Child,
    Device,
    DeviceCommand,
    EnrollmentCode,
    Parent,
    ParentSession,
    Policy,
    TimeRequest,
)
from .policy_signing import sign_policy
from .schemas import (
    ChildInput,
    ChildPinInput,
    CodeInput,
    DeviceCommandInput,
    DeviceSessionInput,
    DeviceTimeRequestInput,
    DeviceTimeStatusInput,
    EnrollInput,
    HeartbeatInput,
    Login,
    PolicyInput,
    RefreshInput,
    TimeRequestDecisionInput,
)
from .security import digest, new_token, password_hasher, verify_password

router = APIRouter(prefix="/api")
# Equalize password hashing work for unknown accounts.
DUMMY_HASH = password_hasher.hash(new_token())


def policy_data(policy):
    return {
        "child_id": policy.child_id,
        "version": policy.version,
        "enabled": policy.enabled,
        "weekday_minutes": policy.weekday_minutes,
        "weekend_minutes": policy.weekend_minutes,
        "schedule": policy.schedule,
        "warnings_minutes": [10, 5, 1],
        "grace_seconds": 60,
        "idle_threshold_seconds": 300,
        "issued_at": policy.updated_at,
    }


def signed_policy_data(policy, key):
    result = policy_data(policy)
    result["integrity"] = {
        "algorithm": "hmac-sha256",
        "signature": sign_policy(result, key),
    }
    return result


def command_data(command):
    return {
        "id": command.id,
        "child_id": command.child_id,
        "type": command.command_type,
        "payload": command.payload,
        "created_at": command.created_at,
    }


def pending_commands(db, device_id):
    return db.scalars(
        select(DeviceCommand)
        .where(
            DeviceCommand.device_id == device_id,
            DeviceCommand.status != "acknowledged",
        )
        .order_by(DeviceCommand.created_at)
        .limit(20)
    ).all()


def client_ip(request):
    return request.client.host if request.client else "unknown"


def device_parent_id(db, device):
    return db.get(Child, device.child_id).parent_id


def accessible_child(db, device, child_id):
    child = db.get(Child, child_id)
    if child is None or child.parent_id != device_parent_id(db, device):
        raise HTTPException(403, "Child profile is not available on this device")
    return child


def active_policy_child_id(device):
    return device.active_child_id or device.child_id


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


@router.get("/parent/events")
async def parent_events(request: Request):
    token = request.cookies.get("ogk_session", "")
    with request.app.state.sessions() as db:
        session = db.get(ParentSession, digest(token))
        if session is None or session.expires_at <= time.time():
            raise HTTPException(401, "Please sign in")
        parent_id = session.parent_id
    manager = request.app.state.parent_events

    async def stream():
        queue = await manager.subscribe(parent_id)
        try:
            yield "event: ready\ndata: {}\n\n"
            while True:
                try:
                    kind = await asyncio.wait_for(queue.get(), timeout=20)
                    yield "event: change\ndata: " + json.dumps({"kind": kind}) + "\n\n"
                except TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            manager.unsubscribe(parent_id, queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/auth/logout", status_code=204)
def logout(auth: ParentAuth, db: DB, response: Response):
    db.delete(auth)
    db.commit()
    response.delete_cookie("ogk_session", path="/")


@router.get("/children")
def children(auth: ParentAuth, db: DB):
    rows = db.scalars(select(Child).where(Child.parent_id == auth.parent_id)).all()
    return [
        {"id": row.id, "display_name": row.display_name, "has_pin": bool(row.pin_hash)}
        for row in rows
    ]


@router.post("/children", status_code=201)
def create_child(body: ChildInput, request: Request, auth: ParentAuth, db: DB):
    existing_names = db.scalars(select(Child.display_name).where(Child.parent_id == auth.parent_id))
    if any(name.casefold() == body.display_name.casefold() for name in existing_names):
        raise HTTPException(409, "A child username already exists in this household")
    child = Child(
        parent_id=auth.parent_id,
        display_name=body.display_name,
        pin_hash=password_hasher.hash(body.pin),
    )
    db.add(child)
    db.flush()
    db.add(Policy(child_id=child.id))
    db.commit()
    request.app.state.parent_events.notify(auth.parent_id, "children")
    return {"id": child.id, "display_name": child.display_name}


@router.put("/children/{child_id}/pin")
def set_child_pin(child_id: str, body: ChildPinInput, request: Request, auth: ParentAuth, db: DB):
    child = owned_child(db, child_id, auth.parent_id)
    had_pin = bool(child.pin_hash)
    child.pin_hash = password_hasher.hash(body.pin)
    db.add(
        Audit(
            parent_id=auth.parent_id,
            child_id=child.id,
            action="child_pin_changed",
            ip=client_ip(request),
            old_value={"has_pin": had_pin},
            new_value={"has_pin": True},
        )
    )
    db.commit()
    request.app.state.parent_events.notify(auth.parent_id, "children")
    return {"id": child.id, "has_pin": True}


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
    request.app.state.parent_events.notify(auth.parent_id)
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
        policy_signing_key=new_token(),
        access_hash="",
        refresh_hash="",
        access_expires_at=0,
        refresh_expires_at=0,
    )
    result = issue_device_tokens(device)
    db.add(device)
    db.flush()
    result["device_id"] = device.id
    child = db.get(Child, child_id)
    result["child_id"] = child.id
    result["child_name"] = child.display_name
    result["policy_signing_key"] = device.policy_signing_key
    db.commit()
    request.app.state.parent_events.notify(child.parent_id)
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
def heartbeat(body: HeartbeatInput, request: Request, device: DeviceAuth, db: DB):
    device.last_seen = time.time()
    device.policy_version = body.policy_version
    policy = db.get(Policy, active_policy_child_id(device))
    commands = pending_commands(db, device.id)
    now = time.time()
    for command in commands:
        if command.status == "pending":
            command.status = "delivered"
            command.delivered_at = now
    db.commit()
    request.app.state.parent_events.notify(device_parent_id(db, device))
    return {
        "server_time": device.last_seen,
        "policy_version": policy.version,
        "heartbeat_after_seconds": 60,
        "commands": [command_data(row) for row in commands],
    }


@router.post("/device/session")
def update_device_session(body: DeviceSessionInput, request: Request, device: DeviceAuth, db: DB):
    if body.active_child_id is None:
        device.active_child_id = None
        device.active_user = None
        device.active_since = None
    else:
        child = accessible_child(db, device, body.active_child_id)
        if not child.pin_hash or (body.active_user and body.active_user != child.display_name):
            raise HTTPException(403, "Child profile is not ready for this device")
        device.active_child_id = child.id
        device.active_user = child.display_name
        device.active_since = body.active_since or time.time()
    db.commit()
    request.app.state.parent_events.notify(device_parent_id(db, device))
    return {
        "active_child_id": device.active_child_id,
        "active_user": device.active_user,
        "active_since": device.active_since,
    }


@router.post("/device/time-status")
def update_device_time_status(
    body: DeviceTimeStatusInput, request: Request, device: DeviceAuth, db: DB
):
    if body.active_child_id is None:
        device.active_child_id = None
        device.active_user = None
        device.active_since = None
        device.used_seconds = None
        device.remaining_seconds = None
        device.quota_seconds = None
        device.extra_seconds = None
        device.active_usage = False
    else:
        child = accessible_child(db, device, body.active_child_id)
        if not child.pin_hash or body.active_user != child.display_name:
            raise HTTPException(403, "Child profile is not ready for this device")
        device.active_child_id = child.id
        device.active_user = child.display_name
        device.active_since = body.active_since or time.time()
        device.used_seconds = body.used_seconds
        device.remaining_seconds = body.remaining_seconds
        device.quota_seconds = body.quota_seconds
        device.extra_seconds = body.extra_seconds
        device.active_usage = body.active_usage
    device.policy_version = body.policy_version
    device.time_status_at = time.time()
    device.last_seen = device.time_status_at
    db.commit()
    request.app.state.parent_events.notify(device_parent_id(db, device))
    return {"received_at": device.time_status_at}


@router.get("/device/profiles")
def device_profiles(request: Request, device: DeviceAuth, db: DB):
    rows = db.execute(
        select(Child, Policy)
        .join(Policy, Policy.child_id == Child.id)
        .where(Child.parent_id == device_parent_id(db, device), Child.pin_hash.is_not(None))
        .order_by(Child.display_name, Child.id)
    ).all()
    key = device.policy_signing_key or request.app.state.settings.policy_signing_key
    result = {
        "device_id": device.id,
        "primary_child_id": device.child_id,
        "profiles": [
            {
                "id": child.id,
                "display_name": child.display_name,
                "pin_hash": child.pin_hash,
                "policy": signed_policy_data(policy, key),
            }
            for child, policy in rows
        ],
    }
    result["integrity"] = {"algorithm": "hmac-sha256", "signature": sign_policy(result, key)}
    return result


@router.post("/device/requests", status_code=201)
def create_time_request(body: DeviceTimeRequestInput, request: Request, device: DeviceAuth, db: DB):
    child = accessible_child(db, device, body.child_id)
    if child.display_name != body.requester:
        raise HTTPException(403, "Requester must match the child assigned to this device")
    existing = db.scalar(
        select(TimeRequest).where(TimeRequest.client_request_id == body.request_id)
    )
    if existing:
        if existing.device_id != device.id:
            raise HTTPException(409, "Request ID belongs to another device")
        return {"id": existing.id, "status": existing.status}
    row = TimeRequest(
        client_request_id=body.request_id,
        device_id=device.id,
        child_id=child.id,
        requester=body.requester,
        minutes=body.minutes,
        created_at=body.created_at,
    )
    db.add(row)
    db.add(
        Audit(
            parent_id=child.parent_id,
            child_id=child.id,
            action="time_requested",
            ip=client_ip(request),
            old_value={},
            new_value={
                "request_id": body.request_id,
                "device_id": device.id,
                "device_name": device.display_name,
                "requester": body.requester,
                "minutes": body.minutes,
            },
        )
    )
    db.commit()
    request.app.state.parent_events.notify(child.parent_id)
    return {"id": row.id, "status": row.status}


@router.get("/policy")
def device_policy(request: Request, device: DeviceAuth, db: DB):
    return signed_policy_data(
        db.get(Policy, active_policy_child_id(device)),
        device.policy_signing_key or request.app.state.settings.policy_signing_key,
    )


@router.get("/children/{child_id}/policy")
def parent_policy(child_id: str, auth: ParentAuth, db: DB):
    owned_child(db, child_id, auth.parent_id)
    return policy_data(db.get(Policy, child_id))


@router.put("/children/{child_id}/policy")
async def update_policy(
    child_id: str, body: PolicyInput, request: Request, auth: ParentAuth, db: DB
):
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
            enabled=body.enabled,
            weekday_minutes=body.weekday_minutes,
            weekend_minutes=body.weekend_minutes,
            schedule=body.schedule,
            updated_at=time.time(),
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
    request.app.state.parent_events.notify(auth.parent_id, "policy")
    device_ids = db.scalars(
        select(Device.id)
        .join(Child, Child.id == Device.child_id)
        .where(Child.parent_id == auth.parent_id)
    ).all()
    for device_id in device_ids:
        await request.app.state.device_connections.send(
            device_id, {"kind": "policy_changed", "child_id": child_id}
        )
    return new


@router.post("/devices/{device_id}/commands", status_code=202)
async def create_device_command(
    device_id: str,
    body: DeviceCommandInput,
    request: Request,
    auth: ParentAuth,
    db: DB,
):
    device = db.scalar(
        select(Device)
        .join(Child, Child.id == Device.child_id)
        .where(Device.id == device_id, Child.parent_id == auth.parent_id, Device.revoked.is_(False))
    )
    if device is None:
        raise HTTPException(404, "Device not found")
    if body.command_type == "add_time" and device.active_child_id is None:
        raise HTTPException(409, "A child must sign in before time can be added")
    command_child_id = device.active_child_id or device.child_id
    payload = {"minutes": body.minutes} if body.command_type == "add_time" else {}
    command = DeviceCommand(
        device_id=device.id,
        child_id=command_child_id,
        parent_id=auth.parent_id,
        command_type=body.command_type,
        payload=payload,
    )
    db.add(command)
    db.flush()
    db.add(
        Audit(
            parent_id=auth.parent_id,
            child_id=command_child_id,
            action="emergency_command_created",
            ip=client_ip(request),
            old_value={},
            new_value={
                "command_id": command.id,
                "device_id": device.id,
                "type": body.command_type,
                "payload": payload,
            },
        )
    )
    db.commit()
    request.app.state.parent_events.notify(auth.parent_id)
    delivered = await request.app.state.device_connections.send(
        device.id, {"kind": "command", "command": command_data(command)}
    )
    if delivered:
        db.execute(
            update(DeviceCommand)
            .where(
                DeviceCommand.id == command.id,
                DeviceCommand.status != "acknowledged",
            )
            .values(status="delivered", delivered_at=time.time())
        )
        db.commit()
        db.refresh(command)
    return {"id": command.id, "status": command.status, "realtime_delivered": delivered}


@router.get("/time-requests")
def parent_time_requests(auth: ParentAuth, db: DB):
    rows = db.execute(
        select(TimeRequest, Device.display_name, Child.display_name)
        .join(Device, Device.id == TimeRequest.device_id)
        .join(Child, Child.id == TimeRequest.child_id)
        .where(Child.parent_id == auth.parent_id)
        .order_by(TimeRequest.created_at.desc())
        .limit(100)
    ).all()
    return [
        {
            "id": request.id,
            "device_id": request.device_id,
            "device_name": device_name,
            "child_name": child_name,
            "requester": request.requester,
            "minutes": request.minutes,
            "status": request.status,
            "created_at": request.created_at,
            "decided_at": request.decided_at,
        }
        for request, device_name, child_name in rows
    ]


@router.post("/time-requests/{request_id}/decision")
async def decide_time_request(
    request_id: str,
    body: TimeRequestDecisionInput,
    request: Request,
    auth: ParentAuth,
    db: DB,
):
    row = db.scalar(
        select(TimeRequest)
        .join(Child, Child.id == TimeRequest.child_id)
        .where(TimeRequest.id == request_id, Child.parent_id == auth.parent_id)
    )
    if row is None:
        raise HTTPException(404, "Time request not found")
    if row.status != "pending":
        raise HTTPException(409, "Time request has already been decided")
    device = db.get(Device, row.device_id)
    old_value = {"status": row.status}
    row.status = "approved" if body.approved else "rejected"
    row.decided_at = time.time()
    row.decided_by = auth.parent_id
    command = None
    if body.approved:
        command = DeviceCommand(
            device_id=row.device_id,
            child_id=row.child_id,
            parent_id=auth.parent_id,
            command_type="add_time",
            payload={
                "minutes": row.minutes,
                "time_request_id": row.id,
                "client_request_id": row.client_request_id,
            },
        )
        db.add(command)
        db.flush()
    db.add(
        Audit(
            parent_id=auth.parent_id,
            child_id=row.child_id,
            action="time_request_decided",
            ip=client_ip(request),
            old_value=old_value,
            new_value={
                "status": row.status,
                "request_id": row.id,
                "client_request_id": row.client_request_id,
                "requester": row.requester,
                "minutes": row.minutes,
                "device_id": row.device_id,
                "command_id": command.id if command else None,
            },
        )
    )
    db.commit()
    request.app.state.parent_events.notify(auth.parent_id)
    if not body.approved:
        await request.app.state.device_connections.send(
            device.id,
            {
                "kind": "time_request_decision",
                "client_request_id": row.client_request_id,
                "status": "rejected",
            },
        )
    delivered = False
    if command:
        delivered = await request.app.state.device_connections.send(
            device.id, {"kind": "command", "command": command_data(command)}
        )
        if delivered:
            db.execute(
                update(DeviceCommand)
                .where(DeviceCommand.id == command.id, DeviceCommand.status != "acknowledged")
                .values(status="delivered", delivered_at=time.time())
            )
            db.commit()
    return {
        "request_id": row.id,
        "status": row.status,
        "command_id": command.id if command else None,
        "realtime_delivered": delivered,
    }


@router.get("/devices")
def devices(auth: ParentAuth, db: DB):
    rows = db.scalars(
        select(Device)
        .join(Child, Child.id == Device.child_id)
        .where(Child.parent_id == auth.parent_id)
    ).all()
    now = time.time()
    return [
        {
            "id": row.id,
            "child_id": row.child_id,
            "active_child_id": row.active_child_id,
            "display_name": row.display_name,
            "last_seen": row.last_seen,
            "policy_version": row.policy_version,
            "online": bool(not row.revoked and row.last_seen and now - row.last_seen < 120),
            "active_user": row.active_user,
            "active_since": row.active_since,
            "used_seconds": row.used_seconds,
            "remaining_seconds": row.remaining_seconds,
            "quota_seconds": row.quota_seconds,
            "extra_seconds": row.extra_seconds,
            "active_usage": row.active_usage,
            "time_status_at": row.time_status_at,
            "server_time": now,
        }
        for row in rows
    ]


@router.get("/audit")
def audits(auth: ParentAuth, db: DB):
    rows = db.execute(
        select(Audit, Parent.email)
        .join(Parent, Parent.id == Audit.parent_id)
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
            "actor": email,
        }
        for row, email in rows
    ]


@router.get("/device/audit")
def device_audits(device: DeviceAuth, db: DB):
    rows = db.execute(
        select(Audit, Parent.email)
        .join(Parent, Parent.id == Audit.parent_id)
        .where(Audit.child_id == active_policy_child_id(device))
        .order_by(Audit.ts.desc())
        .limit(50)
    ).all()
    return [
        {
            "id": row.id,
            "action": row.action,
            "ts": row.ts,
            "actor": email,
            "ip": row.ip,
            "old_value": row.old_value,
            "new_value": row.new_value,
        }
        for row, email in rows
    ]


@router.websocket("/device/ws")
async def device_websocket(websocket: WebSocket):
    token = websocket.query_params.get("access_token", "")
    sessions = websocket.app.state.sessions
    with sessions() as db:
        device = db.scalar(select(Device).where(Device.access_hash == digest(token)))
        if not device or device.revoked or device.access_expires_at <= time.time():
            await websocket.close(code=4401, reason="invalid or expired device token")
            return
        device_id = device.id
    manager = websocket.app.state.device_connections
    await manager.connect(device_id, websocket)
    try:
        with sessions() as db:
            rows = pending_commands(db, device_id)
            now = time.time()
            for row in rows:
                await websocket.send_json({"kind": "command", "command": command_data(row)})
                if row.status == "pending":
                    row.status = "delivered"
                    row.delivered_at = now
            db.commit()
        while True:
            message = await websocket.receive_json()
            if message.get("kind") != "command_ack" or not isinstance(
                message.get("command_id"), str
            ):
                continue
            with sessions() as db:
                command = db.scalar(
                    select(DeviceCommand).where(
                        DeviceCommand.id == message["command_id"],
                        DeviceCommand.device_id == device_id,
                    )
                )
                if command and command.status != "acknowledged":
                    command.status = "acknowledged"
                    command.acknowledged_at = time.time()
                    db.add(
                        Audit(
                            parent_id=command.parent_id,
                            child_id=command.child_id,
                            action="emergency_command_acknowledged",
                            ip=(websocket.client.host if websocket.client else "unknown"),
                            old_value={"status": "delivered"},
                            new_value={
                                "status": "acknowledged",
                                "command_id": command.id,
                                "result": message.get("result", "applied"),
                            },
                        )
                    )
                    db.commit()
                    websocket.app.state.parent_events.notify(command.parent_id)
    except WebSocketDisconnect:
        pass
    finally:
        await manager.disconnect(device_id, websocket)
