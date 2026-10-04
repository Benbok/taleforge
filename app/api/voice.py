"""Голосовые реплики: запись из браузера хранится на сервере, расшифровывает её локальная модель Whisper.

Порядок: клиент загружает запись (POST .../voice) и шлёт по сокету ``message.send`` с ``voice`` вместо текста.
Сервер расшифровывает запись и дальше обрабатывает реплику как обычную: те же проверки хода, шёпота и
видимости. В чате у сообщения — плеер записи и расшифровка; мастер работает с расшифровкой.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy import String, cast, select

from app.agents.stt import MAX_AUDIO_BYTES, SpeechToText
from app.agents.tts import TTSManager
from app.api.deps import SessionDep, UserDep
from app.core import voice
from app.core.campaigns import AccessDenied, NotFound, get_viewer, is_admin, stand_in_seats
from app.core.chat import visible
from app.db.models import Message

router = APIRouter(prefix="/api", tags=["voice"])


def stt(request: Request) -> SpeechToText:
    return request.app.state.stt


@router.get("/voice")
async def voice_status(request: Request, user: UserDep) -> dict:
    """Включён ли голосовой ввод: клиент рисует кнопку микрофона только тогда."""
    return {"enabled": stt(request).enabled}


@router.post("/campaigns/{campaign_id}/voice", status_code=201)
async def upload_voice(campaign_id: str, request: Request, user: UserDep, session: SessionDep) -> dict:
    """Запись телом запроса (audio/webm, audio/ogg, audio/mp4). В чат она попадёт с ``message.send``."""
    await get_viewer(session, user, campaign_id)
    if not stt(request).enabled:
        raise HTTPException(409, "голосовой ввод выключен: на сервере не задан адрес расшифровки STT_API_BASE")
    if int(request.headers.get("content-length") or 0) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "запись слишком длинная: разбейте реплику на части")
    body = await request.body()
    if len(body) > MAX_AUDIO_BYTES:
        raise HTTPException(413, "запись слишком длинная: разбейте реплику на части")
    saved = voice.save(
        request.app.state.settings.media_dir, campaign_id, user.id, body, request.headers.get("content-type")
    )
    return {"voice_id": saved["id"]}


@router.get("/campaigns/{campaign_id}/voice/{voice_id}")
async def get_voice(campaign_id: str, voice_id: str, request: Request, user: UserDep, session: SessionDep) -> Response:
    """Запись слышит тот, кто видит её сообщение в чате."""
    viewer = await get_viewer(session, user, campaign_id)
    q = select(Message).where(Message.campaign_id == campaign_id, Message.data["voice"]["id"].as_string() == voice_id)
    msg = (await session.scalars(q)).first()
    if msg is None:
        # длинное повествование озвучено частями (data.voices): ищем по тексту данных и сверяем id точно
        q = select(Message).where(Message.campaign_id == campaign_id, cast(Message.data, String).contains(voice_id))
        msg = next(
            (
                m
                for m in (await session.scalars(q)).all()
                if any(isinstance(v, dict) and v.get("id") == voice_id for v in (m.data or {}).get("voices") or [])
            ),
            None,
        )
    seats = [viewer.seat.id] if viewer.seat else []
    seats += stand_in_seats(viewer.campaign, user.id)
    # запись отдаётся только вместе с видимым сообщением: голос мастера прикрепляется к тексту хода при коммите
    if msg is None or not any(visible(msg, s) for s in seats or [None]):
        raise NotFound("запись не найдена")
    meta, audio = voice.read(request.app.state.settings.media_dir, campaign_id, voice_id)
    return Response(audio, media_type=meta["mime"], headers={"Cache-Control": "private, max-age=86400"})


@router.get("/admin/voice")
async def admin_voice(request: Request, user: UserDep) -> dict:
    if not is_admin(user):
        raise AccessDenied("настройка голосового ввода доступна Admin и Super Admin")
    return stt(request).status()


@router.post("/admin/voice/check")
async def admin_voice_check(request: Request, user: UserDep) -> dict:
    if not is_admin(user):
        raise AccessDenied("настройка голосового ввода доступна Admin и Super Admin")
    return await stt(request).check()


@router.get("/voice/tts-test")
async def tts_test(request: Request, user: UserDep, provider: str = "gemini", voice: str = "Fenrir") -> Response:
    """Генерация тестовой аудиозаписи для проверки настроек TTS."""
    if not is_admin(user):
        raise AccessDenied("проверка озвучки доступна Admin и Super Admin: синтез речи платный")
    tts_manager: TTSManager = request.app.state.tts
    engine = tts_manager.get_engine(provider)
    if not engine.enabled:
        raise HTTPException(400, "Провайдер выключен или не настроен в .env")

    text_ru = f"Приветствую! Это проверка синтеза речи. Выбранный провайдер: {provider}. Надеюсь, звучит отлично!"
    res = await engine.synthesize(text_ru, voice_name=voice if provider in ("gemini", "voicestudio") else None)
    if not res:
        raise HTTPException(500, "Ошибка синтеза речи")

    audio_bytes, mime, dur = res
    return Response(content=audio_bytes, media_type=mime)


@router.get("/voice/vs-profiles")
async def get_vs_profiles(user: UserDep):
    import httpx

    from app.config import settings

    url = f"{settings.voicestudio_api_base.replace('/v1', '')}/profiles"
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(url)
            if res.status_code == 200:
                return res.json()
    except Exception:
        pass
    return []
