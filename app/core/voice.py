"""Голосовые реплики: запись хранится на диске сервера рядом с игрой, в чате — ссылка на неё и расшифровка.

Файл лежит в ``MEDIA_DIR/voice/<кампания>/<id>.<расширение>``, рядом — ``<id>.json`` (кто записал, формат,
длительность). Слушать запись может тот, кто видит её сообщение: шёпот мастеру слышат только автор и мастер.
"""

from __future__ import annotations

import json
import re
import secrets
from pathlib import Path
from typing import Any

from app.core.campaigns import Conflict, NotFound

EXT = {"audio/webm": "webm", "audio/ogg": "ogg", "audio/mp4": "m4a", "audio/wav": "wav", "audio/mpeg": "mp3"}
ID_RE = re.compile(r"^v[0-9a-z]{16}$")
MAX_SECONDS = 180


def mime_of(content_type: str | None) -> str:
    mime = (content_type or "").split(";", 1)[0].strip().lower()
    if mime not in EXT:
        raise Conflict("неизвестный формат записи: браузер прислал не webm, ogg, mp4, wav или mp3")
    return mime


def _dir(media_dir: Path, campaign_id: str) -> Path:
    if not re.fullmatch(r"[0-9A-Za-z_-]+", campaign_id):
        raise NotFound("кампания не найдена")
    return media_dir / "voice" / campaign_id


def save(media_dir: Path, campaign_id: str, user_id: str, audio: bytes, content_type: str | None) -> dict[str, Any]:
    if not audio:
        raise Conflict("пустая запись: микрофон ничего не передал")
    mime = mime_of(content_type)
    vid = "v" + secrets.token_hex(8)
    folder = _dir(media_dir, campaign_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{vid}.{EXT[mime]}").write_bytes(audio)
    meta = {"id": vid, "user_id": user_id, "mime": mime, "size": len(audio)}
    (folder / f"{vid}.json").write_text(json.dumps(meta), encoding="utf-8")
    return meta


def meta(media_dir: Path, campaign_id: str, vid: str) -> dict[str, Any]:
    if not ID_RE.fullmatch(vid or ""):
        raise NotFound("запись не найдена")
    path = _dir(media_dir, campaign_id) / f"{vid}.json"
    if not path.is_file():
        raise NotFound("запись не найдена: её удалили с сервера или она из другой кампании")
    return json.loads(path.read_text(encoding="utf-8"))


def read(media_dir: Path, campaign_id: str, vid: str) -> tuple[dict[str, Any], bytes]:
    m = meta(media_dir, campaign_id, vid)
    path = _dir(media_dir, campaign_id) / f"{vid}.{EXT[m['mime']]}"
    if not path.is_file():
        raise NotFound("файл записи пропал с сервера")
    return m, path.read_bytes()


def duration(value: Any) -> float | None:
    """Длительность со слов браузера: только для подписи у плеера."""
    try:
        d = float(value)
    except (TypeError, ValueError):
        return None
    return round(min(max(d, 0.0), MAX_SECONDS), 1)
