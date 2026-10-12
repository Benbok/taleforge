"""Небольшой неизменяемый снимок сцены для сообщений и летописи."""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.world import get_scene
from app.db.models import Campaign, Entity


async def message_scene_context(
    session: AsyncSession, campaign: Campaign, place: str | None = None
) -> dict[str, Any] | None:
    """Возвращает контекст места на момент создания сообщения.

    Снимок хранится в ``Message.data``: последующие перемещения отряда не меняют уже написанную хронику.
    """
    scene = await get_scene(session, campaign.id)
    location_id = place or scene.location_id
    if not location_id:
        return None
    entity = await session.scalar(select(Entity).where(Entity.id == location_id, Entity.campaign_id == campaign.id))
    context: dict[str, Any] = {"location_id": location_id}
    if entity is not None:
        context["location_name"] = entity.name
    presentation = (scene.state or {}).get("presentation")
    if isinstance(presentation, dict) and presentation:
        context["presentation"] = dict(presentation)
    return context
