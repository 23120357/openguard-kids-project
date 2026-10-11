"""Authenticated activity ingestion, browsing, filtering and erasure."""

import asyncio
import csv
import io
import time
from datetime import date, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.sqlite import insert

from agent.event_queue import RETENTION_SECONDS
from common.activity_reports import REPORT_ZONE, activity_report, report_bounds
from common.report_charts import render_report_chart, rolling_week_columns

from .dependencies import DB, DeviceAuth, ParentAuth, owned_child
from .event_models import ActivityEvent, EventDeletionAck, EventGeneration, FilteringPolicy
from .event_schemas import EventBatch, FilterInput, FilterRules, GenerationAck
from .models import Audit, Child, Device, TimeRequest
from .policy_signing import sign_policy
from .routes import accessible_child, client_ip, device_parent_id

router = APIRouter(prefix="/api")


def generation_for(db, child_id):
    row = db.get(EventGeneration, child_id)
    return row.generation if row else 0


def serialize(row):
    return {
        "id": row.id,
        "generation": row.generation,
        "event": row.payload,
        "explanation": {"reason": row.reason, "rule_author": row.rule_author},
    }


def expire_events(sessions, now=None):
    with sessions() as db:
        db.execute(
            delete(ActivityEvent).where(ActivityEvent.ts < (now or time.time()) - RETENTION_SECONDS)
        )
        db.execute(
            delete(TimeRequest).where(
                TimeRequest.created_at < (now or time.time()) - RETENTION_SECONDS
            )
        )
        db.execute(
            delete(Audit).where(
                Audit.action == "time_request_decided",
                Audit.ts < (now or time.time()) - RETENTION_SECONDS,
            )
        )
        db.commit()


async def retention_loop(sessions):
    while True:
        await asyncio.to_thread(expire_events, sessions)
        await asyncio.sleep(3600)


@router.get("/device/event-state")
def event_state(device: DeviceAuth, db: DB):
    children = db.scalars(
        select(Child).where(Child.parent_id == device_parent_id(db, device))
    ).all()
    return {"generations": {child.id: generation_for(db, child.id) for child in children}}


@router.post("/device/event-state/ack")
def acknowledge_erasure(body: GenerationAck, device: DeviceAuth, db: DB):
    db.execute(text("BEGIN IMMEDIATE"))
    for child_id, generation in body.generations.items():
        accessible_child(db, device, child_id)
        if generation != generation_for(db, child_id):
            raise HTTPException(409, "Deletion state changed; synchronize again")
        db.execute(
            insert(EventDeletionAck)
            .values(device_id=device.id, child_id=child_id, generation=generation)
            .on_conflict_do_update(
                index_elements=["device_id", "child_id"], set_={"generation": generation}
            )
        )
    db.commit()
    return {"acknowledged": True}


@router.post("/device/activity-events")
def ingest(body: EventBatch, request: Request, device: DeviceAuth, db: DB):
    # Serialize ingestion and deletion, including concurrent requests on different connections.
    db.execute(text("BEGIN IMMEDIATE"))
    now = time.time()
    acknowledged, discarded = [], []
    parent_id = device_parent_id(db, device)
    for item in body.events:
        payload = item.event.model_dump()
        if payload["device_id"] != device.id:
            raise HTTPException(403, "Event belongs to another device")
        accessible_child(db, device, payload["child_id"])
        if payload["ts"] > now + 300:
            raise HTTPException(422, "Event timestamp is too far in the future")
        event_id = str(item.id)
        generation = generation_for(db, payload["child_id"])
        if item.generation != generation or payload["ts"] < now - RETENTION_SECONDS:
            discarded.append(event_id)
            continue
        if payload["type"].startswith("blocked_") and not item.explanation.reason:
            raise HTTPException(422, "Blocked events require an explanation")
        values = dict(
            device_id=device.id,
            id=event_id,
            child_id=payload["child_id"],
            ts=payload["ts"],
            generation=generation,
            payload=payload,
            **item.explanation.model_dump(),
        )
        db.execute(
            insert(ActivityEvent)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["device_id", "id"])
        )
        existing = db.get(ActivityEvent, (device.id, event_id))
        if (
            existing.payload != payload
            or existing.reason != item.explanation.reason
            or existing.rule_author != item.explanation.rule_author
            or existing.generation != generation
        ):
            raise HTTPException(409, "Idempotency key reused with different data")
        acknowledged.append(event_id)
    db.commit()
    request.app.state.parent_events.notify(parent_id, "activity")
    return {"acknowledged": acknowledged, "discarded": discarded}


@router.get("/children/{child_id}/activity-events")
def history(
    child_id: str,
    auth: ParentAuth,
    db: DB,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
):
    owned_child(db, child_id, auth.parent_id)
    rows = db.scalars(
        select(ActivityEvent)
        .where(
            ActivityEvent.child_id == child_id,
            ActivityEvent.ts >= time.time() - RETENTION_SECONDS,
            ActivityEvent.payload["type"].as_string().in_(["blocked_app", "blocked_domain"]),
        )
        .order_by(ActivityEvent.ts.desc(), ActivityEvent.id.desc(), ActivityEvent.device_id)
        .offset(offset)
        .limit(limit + 1)
    ).all()
    return {"items": [serialize(row) for row in rows[:limit]], "has_more": len(rows) > limit}


def build_report(db, child_id, end_date=None, days=28):
    try:
        _, _, lower, upper = report_bounds(end_date, days)
    except ValueError as exc:
        raise HTTPException(422, "Invalid report dates") from exc
    rows = db.scalars(
        select(ActivityEvent.payload)
        .where(
            ActivityEvent.child_id == child_id,
            ActivityEvent.ts >= max(lower, time.time() - RETENTION_SECONDS),
        )
        .execution_options(yield_per=1000)
    )
    report = activity_report(rows, end_date=end_date, days=days)
    requests = db.scalars(
        select(TimeRequest)
        .where(
            TimeRequest.child_id == child_id,
            TimeRequest.created_at >= max(lower, time.time() - RETENTION_SECONDS),
            TimeRequest.created_at < upper,
        )
        .order_by(TimeRequest.created_at.desc())
    )
    report["requests"] = [
        {"created_at": item.created_at, "minutes": item.minutes, "status": item.status}
        for item in requests
    ]
    return report


@router.get("/children/{child_id}/activity-report")
def parent_report(
    child_id: str,
    auth: ParentAuth,
    db: DB,
    end_date: str | None = None,
    days: int = Query(28, ge=1, le=90),
):
    owned_child(db, child_id, auth.parent_id)
    return build_report(db, child_id, end_date, days)


@router.get("/children/{child_id}/activity-report/chart.png")
def parent_report_chart(
    child_id: str,
    auth: ParentAuth,
    db: DB,
    kind: str = Query(pattern="^(daily|weekly|apps)$"),
    days: int = Query(28, ge=1, le=90),
):
    owned_child(db, child_id, auth.parent_id)
    chart_days = {"daily": 7, "weekly": 56, "apps": days}[kind]
    report = build_report(db, child_id, days=chart_days)
    items = {
        "daily": lambda: report["daily"],
        "weekly": lambda: rolling_week_columns(report["daily"]),
        "apps": lambda: report["top_apps"],
    }[kind]()
    return Response(
        render_report_chart(items, kind),
        media_type="image/png",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/device/activity-report")
def child_report(child_id: str, device: DeviceAuth, db: DB, days: int = Query(1, ge=1, le=90)):
    accessible_child(db, device, child_id)
    return {
        "child_id": child_id,
        "generation": generation_for(db, child_id),
        "report": build_report(db, child_id, days=days),
    }


@router.get("/children/{child_id}/activity-report.csv")
def weekly_csv(child_id: str, auth: ParentAuth, db: DB, week_start: str | None = None):
    owned_child(db, child_id, auth.parent_id)
    try:
        start = date.fromisoformat(week_start) if week_start else datetime.now(REPORT_ZONE).date()
    except ValueError as exc:
        raise HTTPException(422, "Invalid week date") from exc
    start -= timedelta(days=start.weekday())
    report = build_report(db, child_id, (start + timedelta(days=6)).isoformat(), 7)
    output = io.StringIO(newline="")
    writer = csv.writer(output)

    def row(*values):
        writer.writerow(
            [
                "'" + value
                if isinstance(value, str) and value.lstrip()[:1] in {"=", "+", "-", "@"}
                else value
                for value in values
            ]
        )

    row("Nhóm", "Ngày / tên", "Giá trị", "Đơn vị")
    for item in report["daily"]:
        row("Thời gian dùng máy", item["date"], item["duration_sec"], "giây")
    for item in report["top_apps"]:
        row("Ứng dụng", item["subject"], item["duration_sec"], "giây chạy")
    for item in report["top_domains"]:
        row("Tên miền", item["subject"], item["queries"], "lượt truy vấn")
    row(
        "Lần bị chặn",
        f"{report['start_date']} - {report['end_date']}",
        report["blocked_count"],
        "lần",
    )
    for item in report["requests"]:
        row(
            "Xin thêm giờ",
            datetime.fromtimestamp(item["created_at"], REPORT_ZONE).isoformat(),
            item["minutes"],
            item["status"],
        )
    return Response(
        output.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="ogk-week-{start.isoformat()}.csv"',
            "Cache-Control": "no-store",
        },
    )


def deletion_status(db, child_id, parent_id):
    generation = generation_for(db, child_id)
    # Every household device can cache events for this child, not only its enrollment child.
    devices = db.scalars(
        select(Device).join(Child, Device.child_id == Child.id).where(Child.parent_id == parent_id)
    ).all()
    pending = []
    for device in devices:
        ack = db.get(EventDeletionAck, (device.id, child_id))
        if generation and (ack is None or ack.generation < generation):
            pending.append(
                {"id": device.id, "name": device.display_name, "revoked": device.revoked}
            )
    return {"generation": generation, "pending_devices": pending, "complete": not pending}


@router.get("/children/{child_id}/activity-data/deletion")
def erasure_status(child_id: str, auth: ParentAuth, db: DB):
    owned_child(db, child_id, auth.parent_id)
    return deletion_status(db, child_id, auth.parent_id)


@router.delete("/children/{child_id}/activity-data")
def erase(child_id: str, request: Request, auth: ParentAuth, db: DB):
    db.execute(text("BEGIN IMMEDIATE"))
    owned_child(db, child_id, auth.parent_id)
    generation = generation_for(db, child_id) + 1
    db.execute(
        insert(EventGeneration)
        .values(child_id=child_id, generation=generation)
        .on_conflict_do_update(index_elements=["child_id"], set_={"generation": generation})
    )
    db.execute(delete(ActivityEvent).where(ActivityEvent.child_id == child_id))
    db.execute(delete(TimeRequest).where(TimeRequest.child_id == child_id))
    db.execute(
        delete(Audit).where(Audit.child_id == child_id, Audit.action == "time_request_decided")
    )
    db.commit()
    request.app.state.parent_events.notify(auth.parent_id, "activity")
    return deletion_status(db, child_id, auth.parent_id)


def filtering_document(db, child_id):
    row = db.get(FilteringPolicy, child_id)
    return dict(
        child_id=child_id,
        version=row.version if row else 0,
        **(row.rules if row else FilterRules().model_dump()),
    )


@router.get("/children/{child_id}/filtering")
def parent_filtering(child_id: str, auth: ParentAuth, db: DB):
    owned_child(db, child_id, auth.parent_id)
    return filtering_document(db, child_id)


@router.put("/children/{child_id}/filtering")
def set_filtering(child_id: str, body: FilterInput, request: Request, auth: ParentAuth, db: DB):
    db.execute(text("BEGIN IMMEDIATE"))
    owned_child(db, child_id, auth.parent_id)
    old = filtering_document(db, child_id)
    if old["version"] != body.expected_version:
        raise HTTPException(409, "Filtering policy changed; reload before saving")
    rules = body.model_dump(exclude={"expected_version"})
    rules["safety_domains"] = sorted(set(rules["safety_domains"]) | {"111.vn"})
    db.execute(
        insert(FilteringPolicy)
        .values(child_id=child_id, version=old["version"] + 1, rules=rules)
        .on_conflict_do_update(
            index_elements=["child_id"], set_={"version": old["version"] + 1, "rules": rules}
        )
    )
    new = filtering_document(db, child_id)
    db.add(
        Audit(
            parent_id=auth.parent_id,
            child_id=child_id,
            action="filtering_updated",
            ip=client_ip(request),
            old_value=old,
            new_value=new,
        )
    )
    db.commit()
    request.app.state.parent_events.notify(auth.parent_id, "policy")
    return new


@router.get("/device/filtering")
def device_filtering(device: DeviceAuth, db: DB):
    children = db.scalars(
        select(Child).where(Child.parent_id == device_parent_id(db, device))
    ).all()
    document = {
        "device_id": device.id,
        "policies": [filtering_document(db, child.id) for child in children],
    }
    document["integrity"] = {
        "algorithm": "hmac-sha256",
        "signature": sign_policy(document, device.policy_signing_key),
    }
    return document
