"""Пакет кампании: записи, которые мастер придумал в игре (спецификация 2026-10-13, §5).

Пакет неизменен в своей версии, а каталог кешируется по цепочке версий. Поэтому каждое добавление — новая
версия со всеми прежними записями; суффикс версии случаен, чтобы откат хода и повтор не попали в чужой кэш.
Пакет кампании стоит последним в цепочке и перекрывает одноимённые записи мира.
"""

from __future__ import annotations

import hashlib
import json
import secrets

from sqlalchemy import select

from app.content.catalog import CatalogView, campaign_catalog
from app.db.models import Campaign, ContentPack, ContentRecord

OVERLAY_PREFIX = "campaign."
OVERLAY_KIND = "campaign_overlay"


def overlay_id(campaign_id: str) -> str:
    return f"{OVERLAY_PREFIX}{campaign_id}"[:64]


def is_overlay(pack_id: str | None) -> bool:
    return bool(pack_id) and str(pack_id).startswith(OVERLAY_PREFIX)


def _current(campaign: Campaign) -> str | None:
    pid = overlay_id(campaign.id)
    return next((v for p, v in campaign.content_chain or [] if p == pid), None)


async def overlay_records(session, campaign: Campaign) -> list[ContentRecord]:
    version = _current(campaign)
    if version is None:
        return []
    q = select(ContentRecord).where(
        ContentRecord.pack_id == overlay_id(campaign.id), ContentRecord.pack_version == version
    )
    return list((await session.scalars(q)).all())


async def add_record(session, campaign: Campaign, kind: str, record: dict) -> CatalogView:
    pid = overlay_id(campaign.id)
    old = [r for r in await overlay_records(session, campaign) if r.id != record["id"]]
    version = f"{len(old) + 1}-{secrets.token_hex(4)}"
    body = json.dumps([[r.id, r.data] for r in old] + [[record["id"], record]], ensure_ascii=False, sort_keys=True)
    session.add(
        ContentPack(
            id=pid,
            version=version,
            name=f"Придумано мастером: {campaign.name}"[:255],
            manifest={"id": pid, "kind": OVERLAY_KIND, "campaign_id": campaign.id},
            checksum=hashlib.sha256(body.encode()).hexdigest(),
            import_report={},
        )
    )
    for r in old:
        session.add(
            ContentRecord(pack_id=pid, pack_version=version, id=r.id, kind=r.kind, status=r.status, name=r.name,
                          data=r.data)  # fmt: skip
        )
    session.add(
        ContentRecord(
            pack_id=pid, pack_version=version, id=record["id"], kind=kind, status="proposal",
            name=str(record["name"])[:255], data=record,
        )  # fmt: skip
    )
    campaign.content_chain = [list(x) for x in campaign.content_chain or [] if x[0] != pid] + [[pid, version]]
    await session.flush()
    return await campaign_catalog(session, campaign)
