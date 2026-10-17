import asyncio
from contextlib import asynccontextmanager, suppress
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import select

from .admin_routes import router as admin_router
from .config import Settings
from .database import build_database, migrate_development_schema
from .event_routes import expire_events, retention_loop
from .event_routes import router as event_router
from .models import Base, Device
from .realtime import DeviceConnections, ParentEvents
from .routes import router
from .security import FieldCipher, RateLimiter

DASHBOARD = Path(__file__).resolve().parents[2] / "dashboard"


def create_app(settings: Settings | None = None):
    settings = settings or Settings.from_env()
    if len(settings.policy_signing_key) < 32:
        raise ValueError("OGK_POLICY_SIGNING_KEY must contain at least 32 characters")
    field_cipher = FieldCipher(settings.data_encryption_key)
    engine, sessions = build_database(settings.database_url)

    @asynccontextmanager
    async def lifespan(app):
        # Initial scaffold only. Replace with migrations before schema evolution.
        Base.metadata.create_all(engine)
        migrate_development_schema(engine)
        with sessions() as db:
            changed = False
            for device in db.scalars(select(Device).where(Device.policy_signing_key.is_not(None))):
                if not device.policy_signing_key.startswith(FieldCipher.PREFIX):
                    device.policy_signing_key = field_cipher.encrypt(
                        device.policy_signing_key,
                        purpose=f"device-policy-signing-key:{device.id}",
                    )
                    changed = True
            if changed:
                db.commit()
        expire_events(sessions)
        retention = asyncio.create_task(retention_loop(sessions))
        try:
            yield
        finally:
            retention.cancel()
            with suppress(asyncio.CancelledError):
                await retention
            engine.dispose()

    app = FastAPI(title="OpenGuard Kids API", version="0.1.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.state.sessions = sessions
    app.state.limiter = RateLimiter()
    app.state.field_cipher = field_cipher
    app.state.device_connections = DeviceConnections()
    app.state.parent_events = ParentEvents()

    @app.middleware("http")
    async def security_headers(request, call_next):
        if (
            request.url.scheme == "http"
            and request.url.hostname not in {"127.0.0.1", "localhost", "::1"}
            and not settings.allow_insecure_http
        ):
            return JSONResponse({"detail": "Remote connections require HTTPS"}, status_code=400)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        if request.url.path == "/" or request.url.path.startswith("/static"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; "
                "img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; "
                "base-uri 'self'; form-action 'self'"
            )
        if request.url.path == "/" or request.url.path.startswith(("/static/", "/api/")):
            response.headers["Cache-Control"] = "no-store"
        if request.url.scheme == "https":
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        return response

    app.include_router(router)
    app.include_router(event_router)
    app.include_router(admin_router)
    app.mount("/static", StaticFiles(directory=DASHBOARD / "static"), name="static")

    @app.get("/", include_in_schema=False)
    def dashboard():
        return FileResponse(DASHBOARD / "index.html")

    return app
