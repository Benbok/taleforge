"""Библиотека звука (design/audio-mixer.md): файлы треков для плеера и раздел «Звук» в админке.

Треки и карточки лежат в папке ``AUDIO_DIR``; админка пишет в неё же, поэтому загруженное остаётся в проекте.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import SessionDep, UserDep
from app.core import audio
from app.core.campaigns import AccessDenied, Conflict, NotFound, is_admin
from app.db.models import ContentPack

router = APIRouter(prefix="/api", tags=["audio"])
FOREVER = {"Cache-Control": "private, max-age=31536000, immutable"}


def lib(request: Request) -> audio.Library:
    return request.app.state.audio


def _admin(user) -> None:
    if not is_admin(user):
        raise AccessDenied("библиотека звука доступна Admin и Super Admin")


@router.get("/audio/{track_id}")
async def track_file(track_id: str, request: Request, user: UserDep) -> FileResponse:
    """Файл трека. Адрес несёт версию (?v=), поэтому браузер скачивает трек один раз."""
    t = lib(request).get(track_id)
    if t is None:
        raise NotFound("трек не найден: его удалили из библиотеки")
    return FileResponse(
        lib(request).path(t), media_type=audio.EXT.get(lib(request).path(t).suffix.lower()), headers=FOREVER
    )


def _row(library: audio.Library, t: audio.Track) -> dict[str, Any]:
    p = library.path(t)
    return {**t.card(), "url": t.public()["url"], "size": p.stat().st_size if p.is_file() else 0}


@router.get("/admin/audio")
async def admin_audio(request: Request, user: UserDep, session: SessionDep) -> dict:
    _admin(user)
    library = lib(request)
    rows = (await session.scalars(select(ContentPack).order_by(ContentPack.id, ContentPack.imported_at))).all()
    packs = {p.id: p.name for p in rows}  # последняя версия пакета даёт имя
    return {
        "dir": str(library.root),
        "tracks": [_row(library, t) for t in library.all()],
        "unsorted": library.unsorted(),
        "errors": library.errors(),
        "layers": list(audio.LAYERS),
        "moods": list(audio.MOODS),
        "cues": list(audio.CUES),
        "packs": [{"id": k, "name": v} for k, v in packs.items()],
    }


@router.post("/admin/audio/files", status_code=201)
async def upload_file(request: Request, user: UserDep, name: str) -> dict:
    """Файл телом запроса, имя — параметром. Карточку трека админка сохраняет следующим запросом."""
    _admin(user)
    if int(request.headers.get("content-length") or 0) > audio.MAX_BYTES:
        raise Conflict(f"файл больше {audio.MAX_BYTES // (1024 * 1024)} МБ: сократите петлю или сожмите в OGG")
    return {"file": lib(request).save_file(name, await request.body())}


@router.get("/admin/audio/files/{name}")
async def unsorted_file(name: str, request: Request, user: UserDep) -> FileResponse:
    """Прослушать неразобранный файл до того, как заполнить карточку."""
    _admin(user)
    library = lib(request)
    if name not in library.unsorted():
        raise NotFound("файл не найден среди неразобранных")
    p = library.root / name
    return FileResponse(p, media_type=audio.EXT.get(p.suffix.lower()))


@router.delete("/admin/audio/files/{name}", status_code=204)
async def delete_unsorted(name: str, request: Request, user: UserDep) -> None:
    _admin(user)
    lib(request).remove_unsorted(name)


@router.put("/admin/audio/tracks/{track_id}")
async def put_track(track_id: str, body: dict, request: Request, user: UserDep) -> dict:
    _admin(user)
    library = lib(request)
    t = library.put({**body, "id": track_id})
    return _row(library, t)


@router.delete("/admin/audio/tracks/{track_id}", status_code=204)
async def delete_track(track_id: str, request: Request, user: UserDep, delete_file: bool = False) -> None:
    _admin(user)
    lib(request).remove(track_id, delete_file=delete_file)
