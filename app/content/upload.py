"""Загрузка пакета сеттинга архивом из админки (этап 7, часть 6).

Архив .zip распаковывается во временную папку с проверкой путей, затем пакет проверяется тем же загрузчиком,
что и команда ``python -m app.content validate``. Зависимости ищутся среди пакетов, поставляемых с сервером
(папка content/). Пакеты загружает только Admin (решение Arty, см. ТЗ).
"""

from __future__ import annotations

import io
import tempfile
import zipfile
from dataclasses import asdict
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.content.importer import import_pack
from app.content.loader import PackError, load_with_dependencies

PACKS_ROOT = Path(__file__).resolve().parents[2] / "content"
MAX_ARCHIVE = 20 * 1024 * 1024  # сжатый архив
MAX_UNPACKED = 100 * 1024 * 1024
MAX_FILES = 5000


class UploadError(Exception):
    """Архив не принят: причина для админа."""


def _unpack(data: bytes, dest: Path) -> Path:
    if len(data) > MAX_ARCHIVE:
        raise UploadError(f"архив больше {MAX_ARCHIVE // (1024 * 1024)} МБ")
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise UploadError("это не zip-архив") from e
    infos = zf.infolist()
    if len(infos) > MAX_FILES:
        raise UploadError(f"в архиве больше {MAX_FILES} файлов")
    if sum(i.file_size for i in infos) > MAX_UNPACKED:
        raise UploadError(f"распакованный пакет больше {MAX_UNPACKED // (1024 * 1024)} МБ")
    base = dest.resolve()
    for i in infos:
        target = (dest / i.filename).resolve()
        if not target.is_relative_to(base) or (i.external_attr >> 16) & 0o170000 == 0o120000:
            raise UploadError(f"недопустимый путь в архиве: {i.filename}")
    zf.extractall(dest)
    # pack.yaml в корне архива или в единственной папке верхнего уровня
    if (dest / "pack.yaml").is_file():
        return dest
    roots = [p.parent for p in dest.glob("*/pack.yaml")]
    if len(roots) != 1:
        raise UploadError("в архиве нет pack.yaml: положите его в корень архива или в одну папку верхнего уровня")
    return roots[0]


async def upload(session: AsyncSession, data: bytes, *, dry_run: bool) -> dict[str, Any]:
    """Проверяет пакет; без dry_run и без ошибок — записывает его с зависимостями в БД."""
    with tempfile.TemporaryDirectory(prefix="tf-pack-") as tmp:
        root = _unpack(data, Path(tmp))
        try:
            _, report = load_with_dependencies(root, PACKS_ROOT)
        except PackError as e:
            raise UploadError(str(e)) from e
        out: dict[str, Any] = {
            "ok": report.ok,
            "pack_id": report.pack_id,
            "version": report.version,
            "summary": report.summary(),
            "report": {k: v for k, v in asdict(report).items() if k != "errors"},
            "errors": report.errors[:100],
            "errors_total": len(report.errors),
            "imported": [],
        }
        if dry_run or not report.ok:
            return out
        try:
            result = await import_pack(session, root, PACKS_ROOT)
        except PackError as e:
            raise UploadError(str(e)) from e
        out["imported"] = [{"id": pid, "version": v, "state": state} for pid, v, state in result]
        return out
