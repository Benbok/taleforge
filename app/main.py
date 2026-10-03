"""РўРѕС‡РєР° РІС…РѕРґР° СЃРµСЂРІРµСЂР°: ``uvicorn app.main:app``."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from sqlalchemy import select

from app.agents.llm import LLM, LiteLLMClient
from app.agents.master import MasterService
from app.agents.player import PlayerAgents
from app.agents.stt import SpeechToText
from app.agents.tts import GeminiTTS, SileroTTS, DisabledTTS
from app.api import (
    admin,
    auth,
    campaigns,
    characters,
    home,
    library,
    models,
    personas,
    plan,
    profile,
    voice,
)
from app.api import audio as audio_api
from app.api.errors import validation_handler
from app.config import Settings
from app.core import audio
from app.core.campaigns import AccessDenied, Conflict, NotFound
from app.core.security import hash_password
from app.db.models import User
from app.db.session import make_engine, make_sessionmaker
from app.gateway import ws
from app.gateway.hub import Hub, MemoryBus, RedisBus
from app.gateway.presence import Presence
from app.rules.dice import Dice

log = logging.getLogger("taleforge")
DIST = Path(__file__).parent / "web" / "dist"  # СЃР±РѕСЂРєР° РєР»РёРµРЅС‚Р° (web/, npm run build)
NOT_BUILT = (
    '<!doctype html><html lang="ru"><meta charset="utf-8"><title>Taleforge</title>'
    "<p>РљР»РёРµРЅС‚ РЅРµ СЃРѕР±СЂР°РЅ: РІС‹РїРѕР»РЅРёС‚Рµ <code>npm ci &amp;&amp; npm run build</code> РІ РїР°РїРєРµ web/.</p></html>"
)


async def bootstrap_superadmin(maker, settings: Settings) -> None:
    """РџРµСЂРІС‹Р№ РІС…РѕРґ: Super Admin РёР· SUPERADMIN_NAME Рё SUPERADMIN_PASSWORD, РµСЃР»Рё С‚Р°РєРѕРіРѕ РµС‰С‘ РЅРµС‚."""
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
            log.info("СЃРѕР·РґР°РЅ Super Admin %s", settings.superadmin_name)


def create_app(settings: Settings | None = None, llm: LLM | None = None, dice_factory=Dice) -> FastAPI:
    """``llm`` Рё ``dice_factory`` РїРѕРґРјРµРЅСЏСЋС‚СЃСЏ РІ С‚РµСЃС‚Р°С…: РјРѕРґРµР»СЊ СЃ Р·Р°РґР°РЅРЅС‹РјРё РѕС‚РІРµС‚Р°РјРё Рё РєСѓР±РёРєРё СЃ seed."""
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
        app.state.dice_factory = dice_factory
        from app.agents.tts import TTSManager
        app.state.tts = TTSManager(settings)
        app.state.master = MasterService(
            app.state.sessionmaker,
            app.state.bus,
            llm or LiteLLMClient(),
            dice_factory,
            media_dir=settings.media_dir,
            tts=app.state.tts,
        )
        await app.state.master.resume_timers()
        app.state.presence = Presence(app.state.sessionmaker, app.state.bus, hub, app.state.master)
        app.state.master.presence = app.state.presence
        app.state.master.players = PlayerAgents(app.state.master)
        app.state.stt = SpeechToText(
            settings.stt_api_base, settings.stt_model, settings.stt_language, settings.stt_concurrency
        )
        try:
            yield
        finally:
            await app.state.presence.stop()
            await app.state.master.players.stop()
            await app.state.master.stop()
            await app.state.bus.stop()
            await engine.dispose()

    app = FastAPI(title="Taleforge", version="0.3.0", lifespan=lifespan)
    app.state.settings = settings
    app.state.audio = audio.configure(settings.audio_dir)

    for exc, code in ((NotFound, 404), (AccessDenied, 403), (Conflict, 409)):

        async def handler(_: Request, e: Exception, code: int = code) -> JSONResponse:
            return JSONResponse({"detail": str(e)}, status_code=code)

        app.add_exception_handler(exc, handler)
    app.add_exception_handler(RequestValidationError, validation_handler)

    app.include_router(auth.router)
    app.include_router(admin.router)
    app.include_router(campaigns.router)
    app.include_router(characters.router)
    app.include_router(home.router)
    app.include_router(library.router)
    app.include_router(models.router)
    app.include_router(personas.router)
    app.include_router(plan.router)
    app.include_router(profile.router)
    app.include_router(voice.router)
    app.include_router(audio_api.router)
    app.include_router(ws.router)

    @app.get("/api/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/assets/{path:path}", include_in_schema=False)
    async def asset(path: str) -> FileResponse:
        file_path = (DIST / "assets" / path).resolve()
        assets_dir = (DIST / "assets").resolve()
        if not file_path.is_relative_to(assets_dir) or not file_path.is_file():
            raise HTTPException(404)
        return FileResponse(file_path, headers={"Cache-Control": "public, max-age=31536000, immutable"})

    # Р’СЃРµ РѕСЃС‚Р°Р»СЊРЅС‹Рµ Р°РґСЂРµСЃР° вЂ” СЃС‚СЂР°РЅРёС†С‹ РѕРґРЅРѕСЃС‚СЂР°РЅРёС‡РЅРѕРіРѕ РєР»РёРµРЅС‚Р°, РјР°СЂС€СЂСѓС‚С‹ СЂР°Р·Р±РёСЂР°РµС‚ РѕРЅ СЃР°Рј.
    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> Response:
        if path.startswith(("api/", "assets/")) or path == "ws":
            raise HTTPException(404)
        if path:
            candidate = (DIST / path).resolve()
            if candidate.is_file() and candidate.is_relative_to(DIST):
                return FileResponse(candidate)
        index = DIST / "index.html"
        if not index.is_file():
            # СЂР°Р·СЂР°Р±РѕС‚РєР° СЃРµСЂРІРµСЂР° Рё С‚РµСЃС‚С‹: РєР»РёРµРЅС‚ РЅРµ СЃРѕР±СЂР°РЅ
            return HTMLResponse(NOT_BUILT, status_code=503)
        return FileResponse(index, headers={"Cache-Control": "no-cache"})

    return app


app = create_app()


