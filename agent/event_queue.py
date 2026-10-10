"""Durable event history/outbox. Transport metadata stays outside the F3 payload."""

import json
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

RETENTION_SECONDS = 90 * 86400
EVENT_TYPES = {
    "app_start",
    "app_stop",
    "domain_query",
    "blocked_app",
    "blocked_domain",
    "quota_warning",
    "locked",
    "unlock_request",
    "override_granted",
}


class EventQueue:
    def __init__(self, path, clock=time.time):
        self.path = str(path)
        self.clock = clock
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS event_generations (
                    child_id TEXT PRIMARY KEY, generation INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS activity_events (
                    id TEXT PRIMARY KEY, child_id TEXT NOT NULL, ts REAL NOT NULL,
                    generation INTEGER NOT NULL, payload TEXT NOT NULL,
                    reason TEXT NOT NULL, rule_author TEXT NOT NULL,
                    sent INTEGER NOT NULL DEFAULT 0, notified INTEGER NOT NULL DEFAULT 0);
                CREATE INDEX IF NOT EXISTS activity_child_time ON activity_events(child_id, ts);
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA secure_delete=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def expire(self):
        with self.connect() as db:
            db.execute(
                "DELETE FROM activity_events WHERE ts < ?", (self.clock() - RETENTION_SECONDS,)
            )

    def append(
        self,
        *,
        device_id,
        child_id,
        type,
        subject,
        policy_id,
        reason="",
        rule_author="Phụ huynh",
        duration_sec=0,
    ):
        if type not in EVENT_TYPES:
            raise ValueError("Unsupported event type")
        if not child_id or not device_id or not 1 <= len(subject) <= 253:
            raise ValueError("Invalid event identity/subject")
        payload = {
            "ts": self.clock(),
            "device_id": device_id,
            "child_id": child_id,
            "type": type,
            "subject": subject,
            "duration_sec": duration_sec,
            "policy_id": policy_id,
        }
        event_id = str(uuid.uuid4())
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT generation FROM event_generations WHERE child_id=?", (child_id,)
            ).fetchone()
            generation = row[0] if row else 0
            db.execute(
                "INSERT INTO activity_events(id, child_id, ts, generation, payload, reason, rule_author) VALUES (?,?,?,?,?,?,?)",
                (
                    event_id,
                    child_id,
                    payload["ts"],
                    generation,
                    json.dumps(payload, ensure_ascii=False),
                    reason[:300],
                    rule_author[:80],
                ),
            )
        return event_id

    @staticmethod
    def document(row):
        return {
            "id": row["id"],
            "generation": row["generation"],
            "event": json.loads(row["payload"]),
            "explanation": {"reason": row["reason"], "rule_author": row["rule_author"]},
        }

    def pending(self, limit=100):
        self.expire()
        with self.connect() as db:
            return [
                self.document(row)
                for row in db.execute(
                    "SELECT * FROM activity_events WHERE sent=0 ORDER BY ts, id LIMIT ?", (limit,)
                )
            ]

    def acknowledge(self, ids):
        with self.connect() as db:
            db.executemany("UPDATE activity_events SET sent=1 WHERE id=?", [(id,) for id in ids])

    def history(self, child_id, limit=30):
        self.expire()
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM activity_events WHERE child_id=? AND json_extract(payload, '$.type') IN ('blocked_app','blocked_domain') ORDER BY ts DESC, id DESC LIMIT ?",
                (child_id, limit),
            )
            return [self.document(row) for row in rows]

    def notifications(self, child_id):
        with self.connect() as db:
            rows = db.execute(
                "SELECT * FROM activity_events WHERE child_id=? AND notified=0 AND json_extract(payload, '$.type') IN ('blocked_app','blocked_domain') ORDER BY ts LIMIT 10",
                (child_id,),
            )
            return [self.document(row) for row in rows]

    def acknowledge_notifications(self, child_id, ids):
        with self.connect() as db:
            db.executemany(
                "UPDATE activity_events SET notified=1 WHERE id=? AND child_id=?",
                [(id, child_id) for id in ids],
            )

    def apply_generations(self, generations):
        """Purge atomically before acknowledging deletion or uploading any batch."""
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            for child_id, generation in generations.items():
                row = db.execute(
                    "SELECT generation FROM event_generations WHERE child_id=?", (child_id,)
                ).fetchone()
                old = row[0] if row else 0
                if generation < old:
                    raise ValueError("Deletion generation rollback")
                if generation > old:
                    db.execute("DELETE FROM activity_events WHERE child_id=?", (child_id,))
                db.execute(
                    "DELETE FROM activity_events WHERE child_id=? AND generation<>?",
                    (child_id, generation),
                )
                db.execute(
                    "INSERT INTO event_generations VALUES (?,?) ON CONFLICT(child_id) DO UPDATE SET generation=excluded.generation",
                    (child_id, generation),
                )
        self.expire()
