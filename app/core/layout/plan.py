"""Место каркаса становится комплексом (спецификация 2026-10-12, §3.1, §3.2, §9): при развороте наброска с
пространством резервируется структура с мандатом — замысел и сюжетные привязки на этот момент. Секрет места,
тайны NPC и тексты зацепок в мандат не идут. Готовое приключение и уже устроенное место не трогаются."""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.core.layout import store
from app.core.layout.spatial import MAX_HOLDERS, Holder, Mandate, SpatialPlan, default_spatial
from app.db.models import Entity, WorldGenerationState


def eligible(world, root: Entity) -> bool:
    from app.core import adventure

    st = root.state or {}
    if root.kind != "location" or store.complex_of(root) is not None or st.get("blueprint") or st.get("sketch"):
        return False
    return adventure.module_place(root, world.catalog, world.entities) is None


async def mandate_for(session, campaign_id: str, plan: dict, sketch: dict, root: Entity) -> Mandate:
    from app.core import plot_anchors

    anchors = [
        Holder(key=b.anchor_id, name=plot_anchors.anchor_reserve(b)["name"][:80])
        for b in await plot_anchors.reserved_for(session, campaign_id, root.id)
    ][:MAX_HOLDERS]
    room = MAX_HOLDERS - len(anchors)
    residents = [
        Holder(key=f"npc:{n['id']}", name=str(n.get("name") or n["id"])[:80])
        for n in plan.get("npcs") or []
        if n.get("location_id") == sketch["id"]
    ][:room]
    return Mandate(
        place=root.name,
        mood=str(sketch.get("mood") or "")[:300],
        spatial=SpatialPlan.model_validate(sketch["spatial"]),
        anchors=anchors,
        residents=residents,
    )


def with_spatial(world, sketch: dict[str, Any], root: Entity) -> dict[str, Any]:
    """Набросок с замыслом пространства: свой из каркаса или простой по шаблону — комплексом становится каждое место."""
    if isinstance(sketch.get("spatial"), dict):
        return sketch
    rec = world.catalog.find(str(sketch.get("template_id") or root.template_id or ""), "location_template")
    tags = (rec.data.get("tags") if rec is not None else None) or []
    template_id = str(sketch.get("template_id") or root.template_id or "")
    return {**sketch, "spatial": default_spatial(root.name, tags, template_id=template_id).model_dump(mode="json")}


async def reserve_from_plan(ctx, root: Entity, sketch: dict[str, Any], inverse: list) -> WorldGenerationState | None:
    """Резерв структуры из наброска; None — место не подходит (готовое приключение, уже устроено)."""
    from app.core.world_generation import storage

    if not eligible(ctx.world, root):
        return None
    sketch = with_spatial(ctx.world, sketch, root)
    row = await storage.find(ctx.session, ctx.campaign.id, root.id, "location_layout")
    if row is not None:
        return row
    try:
        mandate = await mandate_for(ctx.session, ctx.campaign.id, ctx.world.plot, sketch, root)
    except ValidationError:
        return None  # каркас проверен архитектором; испорченный вручную набросок — место без комплекса
    row = await store.reserve_plan_layout(ctx.session, ctx.campaign, root, mandate)
    inverse.append({"table": "world_generation_states", "op": "delete", "id": row.id})
    return row
