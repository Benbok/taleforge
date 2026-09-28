"""Импорт пакета в БД (ТЗ, раздел 3.2, шаг 5): паспорт в content_packs, записи в content_records.

Пакет с той же версией и той же контрольной суммой повторно не пишется. Та же версия с другим
содержимым — ошибка: версию нужно поднять, потому что идущие кампании привязаны к версии.
Нарезка базы знаний с эмбеддингами (шаг 6) — этап «Память».
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.loader import Pack, PackError, load_with_dependencies
from app.db.models import ContentPack, ContentRecord


def pack_checksum(root: Path) -> str:
    h = hashlib.sha256()
    for path in sorted(p for p in root.rglob("*.yaml") if p.is_file()):
        h.update(str(path.relative_to(root)).encode())
        h.update(b"\0")
        h.update(path.read_bytes())
    return h.hexdigest()


async def import_pack(
    session: AsyncSession, root: Path | str, packs_root: Path | str | None = None
) -> list[tuple[str, str, str]]:
    """Импортирует пакет с зависимостями. Возвращает [(id, версия, imported|unchanged)].
    Если проверка не пройдена — PackError, в БД ничего не пишется."""
    chain, report = load_with_dependencies(root, packs_root)
    if not report.ok:
        raise PackError(f"пакет {report.pack_id} не проходит проверку:\n" + "\n".join(report.errors[:50]))
    reports = {chain[-1].id: asdict(report)}
    result = []
    for pack in chain:
        result.append((pack.id, pack.version, await _store(session, pack, reports.get(pack.id, {}))))
    await session.commit()
    return result


async def _store(session: AsyncSession, pack: Pack, report: dict) -> str:
    checksum = pack_checksum(pack.root)
    existing = await session.get(ContentPack, (pack.id, pack.version))
    if existing is not None:
        if existing.checksum == checksum:
            return "unchanged"
        raise PackError(
            f"пакет {pack.id} {pack.version} уже импортирован с другим содержимым: поднимите версию в pack.yaml"
        )
    session.add(
        ContentPack(
            id=pack.id,
            version=pack.version,
            name=pack.manifest.name,
            manifest=pack.manifest.model_dump(mode="json"),
            checksum=checksum,
            import_report=_jsonable(report),
        )
    )
    for rec in pack.records.values():
        session.add(
            ContentRecord(
                pack_id=pack.id,
                pack_version=pack.version,
                id=rec.id,
                kind=rec.kind,
                status=rec.status,
                name=str(rec.data.get("name", rec.id)),
                data=_jsonable(rec.data),
            )
        )
    await session.flush()
    return "imported"


def _jsonable(obj):
    """YAML даёт даты и прочие не-JSON значения; в JSONB они уходят строками."""
    return json.loads(json.dumps(obj, default=str, ensure_ascii=False))


async def latest_version(session: AsyncSession, pack_id: str) -> ContentPack | None:
    from app.content.manifest import version_tuple

    rows = (await session.scalars(select(ContentPack).where(ContentPack.id == pack_id))).all()
    return max(rows, key=lambda p: version_tuple(p.version), default=None)
