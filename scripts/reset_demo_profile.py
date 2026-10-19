"""Preview and remove one demo child profile without touching the household."""

from __future__ import annotations

import argparse
import re
import sqlite3
from datetime import datetime
from pathlib import Path


CHILD_TABLES = (
    "activity_events",
    "observed_apps",
    "event_deletion_acks",
    "event_generations",
    "filtering_policies",
    "device_commands",
    "time_requests",
    "audit",
    "enrollment_codes",
    "policies",
)


def placeholders(values: list[str]) -> str:
    return ",".join("?" for _ in values)


def matching_profile(connection: sqlite3.Connection, name: str, parent_email: str | None):
    sql = (
        "SELECT children.id, children.display_name, parents.email "
        "FROM children JOIN parents ON parents.id = children.parent_id "
        "WHERE lower(children.display_name) = lower(?)"
    )
    parameters: list[str] = [name]
    if parent_email:
        sql += " AND lower(parents.email) = lower(?)"
        parameters.append(parent_email)
    rows = connection.execute(sql, parameters).fetchall()
    if not rows:
        raise SystemExit(f"Không tìm thấy hồ sơ có tên chính xác: {name}")
    if len(rows) != 1:
        owners = ", ".join(row[2] for row in rows)
        raise SystemExit(
            "Tên hồ sơ xuất hiện ở nhiều tài khoản. Chạy lại với --parent-email. "
            f"Các tài khoản: {owners}"
        )
    return rows[0]


def profile_summary(connection: sqlite3.Connection, child_id: str) -> tuple[list[str], dict[str, int]]:
    device_ids = [
        row[0]
        for row in connection.execute(
            "SELECT id FROM devices WHERE child_id = ?", (child_id,)
        ).fetchall()
    ]
    counts = {
        table: connection.execute(
            f"SELECT count(*) FROM {table} WHERE child_id = ?", (child_id,)
        ).fetchone()[0]
        for table in CHILD_TABLES
    }
    counts["devices"] = len(device_ids)
    counts["active_on_other_devices"] = connection.execute(
        "SELECT count(*) FROM devices WHERE active_child_id = ? AND child_id <> ?",
        (child_id, child_id),
    ).fetchone()[0]
    return device_ids, counts


def backup_database(connection: sqlite3.Connection, database: Path, profile_name: str) -> Path:
    safe_name = re.sub(r"[^A-Za-z0-9_-]+", "-", profile_name).strip("-") or "profile"
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    backup = database.with_name(f"{database.stem}.before-reset-{safe_name}-{timestamp}.db")
    with sqlite3.connect(backup) as destination:
        connection.backup(destination)
    return backup


def delete_profile(connection: sqlite3.Connection, child_id: str, device_ids: list[str]) -> None:
    connection.execute("BEGIN IMMEDIATE")
    try:
        for table in ("activity_events", "observed_apps", "event_deletion_acks"):
            if device_ids:
                connection.execute(
                    f"DELETE FROM {table} WHERE child_id = ? OR device_id IN "
                    f"({placeholders(device_ids)})",
                    [child_id, *device_ids],
                )
            else:
                connection.execute(f"DELETE FROM {table} WHERE child_id = ?", (child_id,))
        for table in CHILD_TABLES:
            if table not in {"activity_events", "observed_apps", "event_deletion_acks"}:
                connection.execute(f"DELETE FROM {table} WHERE child_id = ?", (child_id,))
        connection.execute(
            "UPDATE devices SET active_child_id = NULL, active_user = NULL, active_since = NULL, "
            "used_seconds = NULL, remaining_seconds = NULL, quota_seconds = NULL, "
            "extra_seconds = NULL, active_usage = 0, time_status_at = NULL "
            "WHERE active_child_id = ? AND child_id <> ?",
            (child_id, child_id),
        )
        connection.execute("DELETE FROM devices WHERE child_id = ?", (child_id,))
        connection.execute("DELETE FROM children WHERE id = ?", (child_id,))
        connection.commit()
    except Exception:
        connection.rollback()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Xem trước hoặc xóa sạch đúng một hồ sơ demo OpenGuard Kids."
    )
    parser.add_argument("--name", required=True, help="Tên hồ sơ, so khớp toàn bộ")
    parser.add_argument("--parent-email", help="Email phụ huynh nếu tên bị trùng")
    parser.add_argument("--database", type=Path, default=Path("data/server.db"))
    parser.add_argument(
        "--confirm-name",
        help="Phải trùng chính xác --name để thực hiện xóa; bỏ qua để chỉ xem trước.",
    )
    args = parser.parse_args()
    database = args.database.resolve()
    if not database.is_file():
        raise SystemExit(f"Không tìm thấy database: {database}")

    with sqlite3.connect(database, timeout=10) as connection:
        connection.execute("PRAGMA foreign_keys=ON")
        child_id, display_name, email = matching_profile(
            connection, args.name, args.parent_email
        )
        device_ids, counts = profile_summary(connection, child_id)
        print(f"Hồ sơ: {display_name} ({child_id})")
        print(f"Phụ huynh: {email}")
        for table, count in counts.items():
            print(f"  {table}: {count}")

        if args.confirm_name != args.name:
            print("CHỈ XEM TRƯỚC: chưa xóa dữ liệu.")
            print(f"Để xóa, thêm: --confirm-name {args.name}")
            return 0

        backup = backup_database(connection, database, display_name)
        delete_profile(connection, child_id, device_ids)
        print(f"Đã xóa hồ sơ {display_name} và dữ liệu liên quan.")
        print(f"Backup có thể phục hồi: {backup}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
