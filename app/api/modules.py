"""Готовые приключения в админке: загрузка книги и карт, разбор, правка отметок на картах, публикация.

Книга и карты приходят телом запроса (как архив пакета), имя файла — в параметре ``name``. Файлы лежат в
media/modules/<id>/. Разбор идёт в фоне (app/agents/translator.py); клиент спрашивает статус, пока он занят.
"""

from __future__ import annotations

import shutil
from datetime import timedelta
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.agents import translator
from app.api.deps import SessionDep, UserDep
from app.content.upload import PACKS_ROOT
from app.core import modules
from app.core.campaigns import AccessDenied, Conflict, NotFound, is_admin
from app.db.models import AdventureModule, as_utc, new_id, now

router = APIRouter(prefix="/api", tags=["modules"])

STALE = timedelta(minutes=30)  # разбор дольше этого считается прерванным: сервер перезапускали


class ImportIn(BaseModel):
    note: str = Field(default="", max_length=2000)


class Mark(BaseModel):
    number: str
    x: float
    y: float


class MarksIn(BaseModel):
    location_id: str
    marks: list[Mark] = Field(default_factory=list)


def _admin(user) -> None:
    if not is_admin(user):
        raise AccessDenied("только Admin")


def state(m: AdventureModule) -> tuple[str, str | None]:
    if m.status in translator.BUSY and now() - as_utc(m.updated_at) > STALE:
        return "failed", "разбор прервался: запустите его заново"
    return m.status, m.error


def busy(m: AdventureModule) -> bool:
    return state(m)[0] in translator.BUSY


def _short(m: AdventureModule) -> dict[str, Any]:
    status, error = state(m)
    counts = modules.summary(m.draft)["counts"] if m.draft else {}
    return {
        "id": m.id,
        "title": m.title,
        "status": status,
        "error": error,
        "source_name": m.source_name,
        "pages": m.pages,
        "maps": len(m.maps or []),
        "counts": counts,
        "pack_id": m.pack_id,
        "pack_version": m.pack_version,
        "published_at": m.published_at,
        "created_at": m.created_at,
        "updated_at": m.updated_at,
    }


def _full(m: AdventureModule) -> dict[str, Any]:
    return {
        **_short(m),
        "note": m.note,
        "warnings": m.warnings or [],
        "draft": modules.summary(m.draft) if m.draft else None,
        "room_numbers": modules.room_numbers(m.draft) if m.draft else {},
        "map_list": [
            {k: x.get(k) for k in ("id", "name", "location_id", "marks", "missing", "status", "error")}
            for x in m.maps or []
        ],
    }


async def _get(session, module_id: str) -> AdventureModule:
    m = await session.get(AdventureModule, module_id)
    if m is None:
        raise NotFound("приключение не найдено")
    return m


def _settings(request: Request):
    return request.app.state.settings


def _spawn_import(request: Request, module_id: str) -> None:
    svc = request.app.state.master
    svc._spawn(translator.run_import(svc, module_id, _settings(request).media_dir, PACKS_ROOT))


@router.get("/admin/modules")
async def list_modules(user: UserDep, session: SessionDep) -> list[dict]:
    _admin(user)
    rows = (await session.scalars(select(AdventureModule).order_by(AdventureModule.created_at.desc()))).all()
    return [_short(m) for m in rows]


@router.post("/admin/modules", status_code=201)
async def upload_module(request: Request, user: UserDep, session: SessionDep, name: str = "", note: str = "") -> dict:
    """Книга PDF телом запроса. Разбор начинается сразу, карты можно добавить и до, и после него."""
    _admin(user)
    data = await request.body()
    if len(data) > modules.MAX_PDF:
        raise Conflict(f"PDF больше {modules.MAX_PDF // (1024 * 1024)} МБ")
    if not data.startswith(b"%PDF"):
        raise Conflict("это не PDF: загрузите книгу приключения в формате PDF")
    title = (name.rsplit("/", 1)[-1].removesuffix(".pdf").removesuffix(".PDF") or "Приключение")[:255]
    m = AdventureModule(id=new_id("mod"), title=title, source_name=name[:255], note=note[:2000], created_by=user.id)
    base = translator.folder(_settings(request).media_dir, m.id)
    base.mkdir(parents=True, exist_ok=True)
    (base / "source.pdf").write_bytes(data)
    session.add(m)
    await session.commit()
    _spawn_import(request, m.id)
    return _full(m)


@router.get("/admin/modules/{module_id}")
async def get_module(module_id: str, user: UserDep, session: SessionDep) -> dict:
    _admin(user)
    return _full(await _get(session, module_id))


@router.post("/admin/modules/{module_id}/import", status_code=202)
async def reimport(module_id: str, body: ImportIn, request: Request, user: UserDep, session: SessionDep) -> dict:
    """Разобрать книгу заново, например с пожеланием («комнаты храма — из второй главы»)."""
    _admin(user)
    m = await _get(session, module_id)
    if busy(m):
        raise Conflict("разбор уже идёт")
    m.note, m.status, m.error = body.note, "reading", None
    await session.commit()
    _spawn_import(request, m.id)
    return _full(m)


@router.post("/admin/modules/{module_id}/maps", status_code=201)
async def upload_map(module_id: str, request: Request, user: UserDep, session: SessionDep, name: str = "") -> dict:
    """Карта места картинкой. Если книга уже разобрана, модель сразу ищет на ней номера комнат."""
    _admin(user)
    m = await _get(session, module_id)
    data = await request.body()
    mime = _image_type(data)
    if mime is None:
        raise Conflict("карта — картинка PNG, JPEG или WebP")
    if len(data) > modules.MAX_MAP:
        raise Conflict(f"карта больше {modules.MAX_MAP // (1024 * 1024)} МБ")
    map_id = new_id("map")
    file = f"{map_id}.{modules.MAP_TYPES[mime]}"
    (translator.folder(_settings(request).media_dir, m.id) / file).write_bytes(data)
    ready = bool(m.draft) and not busy(m)
    entry = {"id": map_id, "file": file, "mime": mime, "name": name[:255], "location_id": None, "marks": []}
    entry["status"] = "reading" if ready else "pending"
    m.maps = [*(m.maps or []), entry]
    await session.commit()
    if ready:
        svc = request.app.state.master
        svc._spawn(translator.run_maps(svc, m.id, _settings(request).media_dir, only=map_id))
    return _full(m)


@router.post("/admin/modules/{module_id}/maps/{map_id}/read", status_code=202)
async def read_map(module_id: str, map_id: str, request: Request, user: UserDep, session: SessionDep) -> dict:
    """Попросить модель найти номера на карте ещё раз."""
    _admin(user)
    m = await _get(session, module_id)
    if not m.draft:
        raise Conflict("книга ещё не разобрана")
    if busy(m):
        raise Conflict("дождитесь конца разбора")
    maps = [dict(x) for x in m.maps or []]
    target = next((x for x in maps if x["id"] == map_id), None)
    if target is None:
        raise NotFound("карта не найдена")
    target.update(status="reading", error=None)
    m.maps = maps
    await session.commit()
    svc = request.app.state.master
    svc._spawn(translator.run_maps(svc, m.id, _settings(request).media_dir, only=map_id))
    return _full(m)


@router.put("/admin/modules/{module_id}/maps/{map_id}")
async def set_marks(module_id: str, map_id: str, body: MarksIn, user: UserDep, session: SessionDep) -> dict:
    """Админ поправил место карты или отметки номеров."""
    _admin(user)
    m = await _get(session, module_id)
    if not m.draft:
        raise Conflict("книга ещё не разобрана")
    result, errors = modules.check_marks(body.model_dump(), m.draft)
    if result is None:
        raise Conflict("; ".join(errors))
    maps = [dict(x) for x in m.maps or []]
    target = next((x for x in maps if x["id"] == map_id), None)
    if target is None:
        raise NotFound("карта не найдена")
    target.update(result, status="ok", error=None)
    m.maps = maps
    await session.commit()
    return _full(m)


@router.delete("/admin/modules/{module_id}/maps/{map_id}")
async def delete_map(module_id: str, map_id: str, request: Request, user: UserDep, session: SessionDep) -> dict:
    _admin(user)
    m = await _get(session, module_id)
    target = next((x for x in m.maps or [] if x["id"] == map_id), None)
    if target is None:
        raise NotFound("карта не найдена")
    m.maps = [x for x in m.maps if x["id"] != map_id]
    await session.commit()
    if not m.pack_id:  # у опубликованного модуля картинку видят кампании: файл остаётся
        (translator.folder(_settings(request).media_dir, m.id) / target["file"]).unlink(missing_ok=True)
    return _full(m)


@router.post("/admin/modules/{module_id}/publish")
async def publish(module_id: str, user: UserDep, session: SessionDep) -> dict:
    """Записать модуль пакетом в БД. Повторная публикация после правок — новая версия пакета."""
    _admin(user)
    m = await _get(session, module_id)
    status, _ = state(m)
    if status not in ("review", "published") or not m.draft:
        raise Conflict("публиковать можно только разобранное приключение")
    version = modules.next_version(m.pack_version)
    try:
        pack_id = await modules.publish(session, m.draft, list(m.maps or []), version, PACKS_ROOT, m.id)
    except modules.ModuleError as e:
        await session.rollback()
        raise Conflict(f"пакет модуля не прошёл проверку: {e}") from e
    m = await _get(session, module_id)  # импорт пакета закрыл транзакцию
    m.pack_id, m.pack_version, m.status, m.error, m.published_at = pack_id, version, "published", None, now()
    await session.commit()
    return _full(m)


@router.delete("/admin/modules/{module_id}", status_code=204)
async def delete_module(module_id: str, request: Request, user: UserDep, session: SessionDep) -> None:
    _admin(user)
    m = await _get(session, module_id)
    if m.pack_id:
        raise Conflict("приключение опубликовано: на нём могут идти кампании")
    if busy(m):
        raise Conflict("дождитесь конца разбора")
    await session.delete(m)
    await session.commit()
    shutil.rmtree(translator.folder(_settings(request).media_dir, module_id), ignore_errors=True)


@router.get("/modules/{module_id}/maps/{map_id}")
async def map_image(module_id: str, map_id: str, request: Request, user: UserDep, session: SessionDep):
    """Картинка карты. Тайн на ней нет — номера комнат и планировка, поэтому её видит любой вошедший."""
    m = await _get(session, module_id)
    target = next((x for x in m.maps or [] if x["id"] == map_id), None)
    if target is None:
        raise NotFound("карта не найдена")
    path = translator.folder(_settings(request).media_dir, m.id) / target["file"]
    if not path.is_file():
        raise NotFound("файл карты не найден")
    return FileResponse(path, media_type=target.get("mime") or "image/png")


def _image_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None
