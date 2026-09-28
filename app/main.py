"""Точка входа сервера: ``uvicorn app.main:app``."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from sqlalchemy import select

from app.api import admin, auth, campaigns
from app.config import Settings
from app.core.campaigns import AccessDenied, Conflict, NotFound
from app.core.security import hash_password
from app.db.models import User
from app.db.session import make_engine, make_sessionmaker
from app.gateway import ws
from app.gateway.hub import Hub, MemoryBus, RedisBus

log = logging.getLogger("taleforge")
STATIC = Path(__file__).parent / "web" / "static"


async def bootstrap_superadmin(maker, settings: Settings) -> None:
    """Первый вход: Super Admin из SUPERADMIN_NAME и SUPERADMIN_PASSWORD, если такого ещё нет."""
    if not (settings.superadmin_name and settings.superadmin_password):
        return
    async with maker() as session:
        exists = (await session.scalars(select(User).where(User.name == settings.superadmin_name))).first()
        if exists is None:
            session.add(
                User(
                    name=settings.superadmin_name,
                    password_hash=hash_password(settings.superadmin_password),
                    platform_role="super_admin",
                )
            )
            await session.commit()
            log.info("создан Super Admin %s", settings.superadmin_name)


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        engine = make_engine(settings.database_url)
        app.state.engine = engine
        app.state.sessionmaker = make_sessionmaker(engine)
        app.state.hub = hub = Hub()
        app.state.bus = RedisBus(hub, settings.redis_url) if settings.redis_url else MemoryBus(hub)
        await app.state.bus.start()
        await bootstrap_superadmin(app.state.sessionmaker, settings)
        try:
            yield
        finally:
            await app.state.bus.stop()
            await engine.dispose()

    app = FastAPI(title="Taleforge", version="0.2.0", lifespan=lifespan)
    app.state.settings = settings

    for exc, code in ((NotFound, 404), (AccessDenied, 403), (Conflict, 409)):

        async def handler(_: Request, e: Exception, code: int = code) -> JSONResponse:
            return JSONResponse({"detail": str(e)}, status_code=code)

        app.add_exception_handler(exc, handler)

    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(campaigns.router)
    app.include_router(ws.router)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    # Временный веб-клиент для проверки каркаса. Настоящий интерфейс — этап «Интерфейс» (React).
    @app.get("/", include_in_schema=False)
    @app.get("/invite/{token}", include_in_schema=False)
    async def index(token: str | None = None) -> FileResponse:
        return FileResponse(STATIC / "index.html")

    return app


app = create_app()
