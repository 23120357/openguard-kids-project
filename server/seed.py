"""Create a local demo parent. Never resets existing passwords."""

import os

from sqlalchemy import select

from server.app.config import Settings
from server.app.database import build_database
from server.app.models import Base, Parent
from server.app.security import password_hasher


def main():
    settings = Settings.from_env()
    email = os.getenv("OGK_DEMO_EMAIL", "").strip().lower()
    password = os.getenv("OGK_DEMO_PASSWORD", "")
    if not email or len(password) < 10:
        raise SystemExit(
            "Set OGK_DEMO_EMAIL and OGK_DEMO_PASSWORD (at least 10 characters) in .env"
        )
    engine, sessions = build_database(settings.database_url)
    Base.metadata.create_all(engine)
    with sessions() as db:
        existing = db.scalar(select(Parent).where(Parent.email == email))
        if existing:
            print("Demo parent already exists; left unchanged.")
        else:
            db.add(Parent(email=email, password_hash=password_hasher.hash(password)))
            db.commit()
            print("Demo parent created. Use credentials from your local .env.")
    engine.dispose()


if __name__ == "__main__":
    main()
