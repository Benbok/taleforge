"""Журнал канона: что мастер сам завёл в мир по ходу игры (вещи, приметы, контейнеры, придуманные предметы).

Нужен владельцу кампании: творчество мастера остаётся под контролем, а не растворяется в прозе. Источник один —
события инструментов; ничего отдельно не хранится, откат хода убирает и запись журнала."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Event

# инструмент -> подпись вида записи
CREATIVE_TOOLS: dict[str, str] = {
    "keep_found_item": "Находка в инвентаре героя",
    "place_item": "Вещь в сцене",
    "create_container": "Контейнер",
    "add_landmark": "Примета места",
    "invent_item": "Придуманный предмет (нужен ревью)",
}


def entry(event: Event) -> dict[str, Any] | None:
    """Одна запись журнала или ``None``, если событие не творческое."""
    label = CREATIVE_TOOLS.get(event.tool)
    if label is None:
        return None
    p = event.payload or {}
    if event.tool == "invent_item":
        record = p.get("record") or {}
        name, subject = record.get("name"), p.get("missing_id")
    elif event.tool == "keep_found_item":
        name, subject = p.get("item"), p.get("inventory_id")
    elif event.tool == "place_item":
        name, subject = p.get("item"), p.get("entity_id")
    else:
        name, subject = p.get("name"), event.target_id
    return {
        "event_id": event.id,
        "at": event.created_at,
        "tool": event.tool,
        "kind": label,
        "name": name or "без названия",
        "subject_id": subject,
        "reason": p.get("reason"),
        "turn_id": event.turn_id,
    }


async def canon_journal(session: AsyncSession, campaign_id: str, limit: int = 100) -> list[dict[str, Any]]:
    """Последние творческие записи кампании, новые сверху."""
    q = (
        select(Event)
        .where(Event.campaign_id == campaign_id, Event.tool.in_(CREATIVE_TOOLS))
        .order_by(Event.created_at.desc())
        .limit(limit)
    )
    return [e for e in map(entry, (await session.scalars(q)).all()) if e is not None]
