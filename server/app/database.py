from pathlib import Path

from sqlalchemy import create_engine, event
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


def get_db(request):
    # Used by the typed dependency in dependencies.py.
    with request.app.state.sessions() as session:
        yield session
