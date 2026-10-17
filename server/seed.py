"""Create a local demo parent. Never resets existing passwords."""

import os

from sqlalchemy import select

from server.app.config import Settings
from server.app.database import build_database
from server.app.models import AdminUser, Base, Parent
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
        admin_email = os.getenv("OGK_ADMIN_EMAIL", "").strip().lower()
        admin_password = os.getenv("OGK_ADMIN_PASSWORD", "")
        if settings.admin_enabled:
            if not admin_email or len(admin_password) < 10:
                raise SystemExit(
                    "Admin mode requires OGK_ADMIN_EMAIL and OGK_ADMIN_PASSWORD (10+ characters)"
                )
            admin = db.scalar(select(AdminUser).where(AdminUser.email == admin_email))
            if admin:
                print("Development admin already exists; left unchanged.")
            else:
                db.add(
                    AdminUser(
                        email=admin_email,
                        password_hash=password_hasher.hash(admin_password),
                    )
                )
                db.commit()
                print("Development admin created with a separate credential.")
    engine.dispose()


if __name__ == "__main__":
    main()
