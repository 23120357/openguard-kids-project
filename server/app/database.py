from pathlib import Path

from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


def build_database(url: str):
    parsed = make_url(url)
    if parsed.get_backend_name() != "sqlite":
        raise ValueError("This scaffold currently supports SQLite only")
    memory = parsed.database in (None, "", ":memory:")
    if not memory:
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    options = {"poolclass": StaticPool} if memory else {}
    engine = create_engine(url, connect_args={"check_same_thread": False}, **options)

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        cursor = connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=5000")
        cursor.close()

    return engine, sessionmaker(bind=engine, expire_on_commit=False)


def migrate_development_schema(engine) -> None:
    """Apply additive Week-2 fields to an existing local scaffold DB.

    Production must use a real migration tool; these idempotent ALTERs only keep
    the documented local Week-1 database usable during the course milestone.
    """

    if "policies" not in inspect(engine).get_table_names():
        return
    columns = {column["name"] for column in inspect(engine).get_columns("policies")}
    statements = []
    if "enabled" not in columns:
        statements.append("ALTER TABLE policies ADD COLUMN enabled BOOLEAN NOT NULL DEFAULT 1")
    if "schedule" not in columns:
        default_schedule = '["' + '","'.join(["1" * 48] * 7) + '"]'
        statements.append(
            "ALTER TABLE policies ADD COLUMN schedule JSON NOT NULL DEFAULT '"
            + default_schedule
            + "'"
        )
    if "updated_at" not in columns:
        statements.append("ALTER TABLE policies ADD COLUMN updated_at FLOAT NOT NULL DEFAULT 0")
    child_columns = {column["name"] for column in inspect(engine).get_columns("children")}
    if "pin_hash" not in child_columns:
        statements.append("ALTER TABLE children ADD COLUMN pin_hash VARCHAR(255)")
    device_columns = {column["name"] for column in inspect(engine).get_columns("devices")}
    if "policy_signing_key" not in device_columns:
        statements.append("ALTER TABLE devices ADD COLUMN policy_signing_key VARCHAR(128)")
    if "active_user" not in device_columns:
        statements.append("ALTER TABLE devices ADD COLUMN active_user VARCHAR(80)")
    if "active_since" not in device_columns:
        statements.append("ALTER TABLE devices ADD COLUMN active_since FLOAT")
    if "active_child_id" not in device_columns:
        statements.append("ALTER TABLE devices ADD COLUMN active_child_id VARCHAR(36)")
    for name in ("used_seconds", "remaining_seconds", "quota_seconds", "extra_seconds"):
        if name not in device_columns:
            statements.append(f"ALTER TABLE devices ADD COLUMN {name} INTEGER")
    if "active_usage" not in device_columns:
        statements.append("ALTER TABLE devices ADD COLUMN active_usage BOOLEAN NOT NULL DEFAULT 0")
    if "time_status_at" not in device_columns:
        statements.append("ALTER TABLE devices ADD COLUMN time_status_at FLOAT")
    if statements:
        with engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))


def get_db(request):
    # Used by the typed dependency in dependencies.py.
    with request.app.state.sessions() as session:
        yield session
