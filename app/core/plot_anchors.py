"""Сюжетные резервы (спецификация генерации сцен, §8.1; docs/world-objects-delivery4.md).

Зацепка каркаса с физическим носителем (``clue.carrier``) получает ``PlotAnchorBinding`` по стабильному id зацепки.
Сюжет назначает обязательства сам, независимо от наполнения: ``sync_bindings`` сверяет привязки с каркасом при
каждой его записи. Носитель создаёт подготовка места (поставка 3) или вход в уже готовое место; созданный факт
пересмотр не переписывает, утраченный носитель генератор не восстанавливает.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import plot
from app.db.models import Entity, PlotAnchorBinding, WorldGenerationState

NOTE = "item.plot_note"  # записка без механики: носитель по умолчанию, стоимость 0


def carriers(plan: dict | None) -> dict[str, dict[str, Any]]:
    """Зацепки с носителем: anchor_id → {reveal_id, at, text, carrier}."""
    out: dict[str, dict[str, Any]] = {}
    if not plot.has_plan(plan):
        return out
    for r in plan.get("reveals") or []:
        for c in r.get("clues") or []:
            if isinstance(c, dict) and c.get("id") and isinstance(c.get("carrier"), dict):
                out[c["id"]] = {
                    "reveal_id": r.get("id"),
                    "at": c.get("at"),
                    "text": c.get("text"),
                    "carrier": c["carrier"],
                    "used_fact_refs": list(c.get("used_fact_refs") or []),
                }
    return out


def find_clue(plan: dict | None, anchor_id: str) -> tuple[dict, dict] | None:
    for r in (plan or {}).get("reveals") or []:
        for c in r.get("clues") or []:
            if isinstance(c, dict) and c.get("id") == anchor_id:
                return r, c
    return None


def _target(plan: dict, at: str | None) -> str | None:
    """Место каркаса → его сущность после разворота. NPC и неразвёрнутое место цели не дают."""
    kind, x = plot._index(plan).get(at or "", (None, {}))
    return x.get("entity_id") if kind == "location" else None


def snapshot(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "reveal_id": data["reveal_id"],
        "text": data.get("text"),
        "carrier": dict(data["carrier"]),
        "used_fact_refs": list(data.get("used_fact_refs") or []),
    }


async def sync_bindings(session: AsyncSession, campaign_id: str, plan: dict | None) -> None:
    """Привести привязки к каркасу. Созданные и раскрытые факты не переписываются."""
    rows = {b.anchor_id: b for b in await session.scalars(_of(campaign_id))}
    wanted = carriers(plan)
    revealed = {r.get("id") for r in (plan or {}).get("reveals") or [] if r.get("revealed")}
    for anchor, data in wanted.items():
        snap, target = snapshot(data), _target(plan or {}, data.get("at"))
        b = rows.get(anchor)
        if b is None:
            session.add(
                PlotAnchorBinding(
                    campaign_id=campaign_id,
                    anchor_id=anchor,
                    plot_ref=data["reveal_id"],
                    target_location_id=target,
                    state="reserved",
                    source_snapshot=snap,
                )
            )
        elif b.state == "reserved":
            if b.source_snapshot != snap:
                b.source_snapshot = snap
            if b.target_location_id != target:
                b.target_location_id = target
            if b.plot_ref != data["reveal_id"]:
                b.plot_ref = data["reveal_id"]
    for anchor, b in rows.items():
        if b.state == "reserved" and anchor not in wanted:
            b.state = "replaced_by_story"
        elif b.state == "materialized" and b.plot_ref in revealed and b.holder_entity_id is not None:
            b.state = "revealed"
    await session.flush()
    await mark_lost(session, campaign_id)


async def mark_lost(session: AsyncSession, campaign_id: str) -> list[str]:
    """Носитель удалён (внешний ключ обнулил holder): привязка ``lost``, её не восстанавливают."""
    q = _of(campaign_id).where(
        PlotAnchorBinding.state.in_(("materialized", "revealed")), PlotAnchorBinding.holder_entity_id.is_(None)
    )
    lost = []
    for b in await session.scalars(q):
        b.state = "lost"
        lost.append(b.anchor_id)
    if lost:
        await session.flush()
    return lost


def _of(campaign_id: str):
    return (
        select(PlotAnchorBinding)
        .where(PlotAnchorBinding.campaign_id == campaign_id)
        .order_by(PlotAnchorBinding.anchor_id)
    )


async def reserved_for(session: AsyncSession, campaign_id: str, location_id: str) -> list[PlotAnchorBinding]:
    """Зацепки, которые ждут места. Участок комплекса получает и зацепки корня, отданные ему blueprint; корень с
    blueprint их уже не держит (спецификация 2026-10-12, §3.1)."""
    from app.core.layout import store

    base = _of(campaign_id).where(PlotAnchorBinding.state == "reserved", PlotAnchorBinding.holder_entity_id.is_(None))
    place = await session.get(Entity, location_id)
    cx = store.complex_of(place)
    if cx is not None:
        bp = store.blueprint_of(await session.get(Entity, cx["root_id"]))
        mine = {a for a, ref in (bp.anchors if bp else {}).items() if ref == cx["area_ref"]}
        q = base.where(PlotAnchorBinding.target_location_id.in_((location_id, cx["root_id"])))
        return [b for b in await session.scalars(q) if b.target_location_id == location_id or b.anchor_id in mine]
    found = list(await session.scalars(base.where(PlotAnchorBinding.target_location_id == location_id)))
    bp = store.blueprint_of(place)
    return [b for b in found if b.anchor_id not in bp.anchors] if bp is not None else found


async def routed(session: AsyncSession, campaign_id: str) -> set[str]:
    """Носители, отданные в резерв ещё не исследованного контейнера: их создаст исследование, а не вход."""
    q = select(WorldGenerationState).where(
        WorldGenerationState.campaign_id == campaign_id,
        WorldGenerationState.phase == "container_contents",
        WorldGenerationState.status != "ready",
    )
    out: set[str] = set()
    for row in await session.scalars(q):
        out |= {a["anchor_id"] for a in (row.reservation or {}).get("anchors") or []}
    return out


def anchor_reserve(binding: PlotAnchorBinding) -> dict[str, Any]:
    """Носитель в резерве места: что положить, без стоимости (её считает policy по профилю)."""
    vessel = dict((binding.source_snapshot or {}).get("carrier") or {})
    return {
        "anchor_id": binding.anchor_id,
        "binding_id": binding.id,
        "name": vessel.get("name") or "Записка",
        "description": vessel.get("description") or "",
        "template_id": vessel.get("template_id") or NOTE,
        "hidden": bool(vessel.get("hidden")),
    }


async def place(ctx, binding: PlotAnchorBinding, *, place_id: str, parent: str | None, zone: str, ref: str) -> Entity:
    """Создать носитель уникальным предметом по текущему снимку привязки и закрепить его за ней."""
    from app.tools.master.items import _put_in_scene

    vessel = anchor_reserve(binding)
    rec = ctx.world.catalog.find(vessel["template_id"], "item_template")
    template = rec.id if rec is not None else NOTE
    shown = None if rec is not None and rec.name == vessel["name"] else vessel["name"]
    en, _ = await _put_in_scene(
        ctx,
        template,
        shown,
        1,
        zone,
        vessel["description"],
        place=place_id,
        container_id=parent,
        force_new=True,
        force_unique=True,
        generation_ref=ref,
    )
    en.state = {**(en.state or {}), "plot_anchor": binding.anchor_id}
    binding.holder_entity_id = en.id
    binding.state = "materialized"

    used_refs = (binding.source_snapshot or {}).get("used_fact_refs") or []
    if used_refs:
        to_seal = [r for r in used_refs if r]
        if to_seal:
            from app.core.narrative.contracts import SnapshotRef
            from app.tools.narrative.commitments import record_commitments

            await record_commitments(
                ctx,
                tuple(to_seal),
                reason="plot_anchor_materialized",
                snapshot_ref=SnapshotRef(
                    kind="event",
                    source_id=ref,
                    typed_address=f"plot_anchor:{binding.anchor_id}",
                ),
            )

    return en


async def materialize_late(ctx, location: Entity, ref: str) -> list[str]:
    """Привязка появилась, когда место уже подготовлено: носитель кладётся на виду при входе героев."""
    skip = await routed(ctx.session, ctx.campaign.id)
    made = []
    for b in await reserved_for(ctx.session, ctx.campaign.id, location.id):
        if b.anchor_id in skip:
            continue
        en = await place(ctx, b, place_id=location.id, parent=None, zone="near", ref=ref)
        made.append(en.id)
    return made
