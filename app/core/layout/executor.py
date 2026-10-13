"""Исполнители фаз ``location_layout`` и ``location_geometry`` (спецификация 2026-10-12, §3.2, §3.3, §8).

Структура: provider предлагает blueprint из замысла резерва — сначала обычный, затем упрощённый fallback; ни тот, ни
другой не выполнили обязательств — ``blocked``, несогласованный результат не публикуется. Публикация — одна
``world_write``: участки с реальными id, blueprint, живые проходы и резервы геометрии всех участков (не запрошенные).
Геометрия: эскиз участка строится кодом из зафиксированного blueprint; ручной эскиз мастера остаётся.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from typing import Any

from pydantic import ValidationError

from app.core.layout import geometry, store
from app.core.layout.contracts import Blueprint, LayoutError
from app.core.layout.intent import LayoutIntent
from app.core.world_generation import storage
from app.core.world_generation.contracts import Blocked
from app.db.models import Entity, WorldGenerationState

log = logging.getLogger(__name__)

PHASES = ("location_layout", "location_geometry")


async def run(maker, dice_factory, claim: storage.Claim, phase: str, provider, llm=None) -> dict[str, Any]:
    if phase == "location_layout":
        bp, quality, notes, claim = await _draft(maker, claim, provider, llm)

        async def publish(ctx, row):
            return await _publish_layout(ctx, row, bp, quality, notes)

        return await storage.commit_with(maker, dice_factory, claim, publish, quality=quality)
    return await storage.commit_with(maker, dice_factory, claim, _publish_geometry)


async def _draft(maker, claim: storage.Claim, provider, llm=None) -> tuple[Blueprint, str, list[str], storage.Claim]:
    """Замысел резерва → blueprint. Ручной замысел ведущего — как в поставке 1; мандат каркаса — лестница
    детерминированных замыслов (модель добавляется в поставке 3, Task 6). Ни один не лёг — ``blocked``."""
    from app.core import plot_anchors
    from app.core.layout import spatial

    async with maker() as s:
        row = await s.get(WorldGenerationState, claim.ref)
        res = dict(row.reservation or {})
        waiting = [b.anchor_id for b in await plot_anchors.reserved_for(s, claim.campaign_id, row.target_entity_id)]
    kw = {"seed": int(res["seed"]), "root_id": res["root_id"], "plot_id": res.get("plot_id")}
    notes: list[str] = []
    try:
        if "mandate" in res:
            candidates = spatial.intent_candidates(spatial.Mandate.model_validate(res["mandate"]))
        else:
            candidates = [LayoutIntent.model_validate(res["intent"])]
    except (KeyError, ValidationError) as e:
        raise Blocked("unsupported_source", str(e)[:500]) from e
    errors: list[str] = []
    for i, intent in enumerate(candidates):
        for fallback in (False, True):
            try:
                bp = provider.propose(intent, fallback=fallback, **kw)
            except LayoutError as e:
                errors += e.errors[:3]
                log.info(
                    "структура %s: замысел %d%s не прошёл (%s)",
                    claim.ref,
                    i,
                    " fallback" if fallback else "",
                    "; ".join(e.errors[:3]),
                )
                continue
            quality = "normal" if i == 0 and not fallback and not notes else "fallback"
            if quality == "fallback":
                notes.append("fallback:layout")
            return _with_anchors(bp, waiting), quality, notes, claim
    raise Blocked("layout_unsatisfiable", "; ".join(errors[:6]))


def _with_anchors(bp: Blueprint, waiting: list[str]) -> Blueprint:
    """Зацепка корня без места в замысле не теряется: её получает входной участок."""
    extra = {a: bp.entry for a in waiting if a not in bp.anchors}
    return replace(bp, anchors={**bp.anchors, **extra}) if extra else bp


async def _publish_layout(
    ctx, row: WorldGenerationState, bp: Blueprint, quality: str, notes: list[str] | None = None
) -> dict[str, Any]:
    root = ctx.world.entities.get(row.target_entity_id)
    if root is None or root.kind != "location":
        raise Blocked("target_missing", "корневого места больше нет")
    if (root.state or {}).get("blueprint"):
        raise Blocked("already_built", "у места уже есть blueprint")
    ids: dict[str, str] = {}
    for area in bp.areas:
        state: dict[str, Any] = {"complex": {"root_id": root.id, "area_ref": area.area_ref}}
        if area.secret:
            state["secret"] = True
        en = Entity(campaign_id=ctx.campaign.id, kind="location", name=area.public_name,
                    description=area.description, location_id=root.id, state=state)  # fmt: skip
        ctx.session.add(en)
        await ctx.session.flush()
        ctx.world.entities[en.id] = en
        ids[area.area_ref] = en.id
    passages = {p.passage_ref: {"state": p.state, "hidden": p.hidden} for p in bp.passages}
    root.state = {**(root.state or {}), "blueprint": bp.to_json(), "areas": ids, "passages": passages}
    rows_ = {}
    for area in bp.areas:
        g = await store.reserve_geometry(ctx.session, ctx.campaign.id, root, ctx.world.entities[ids[area.area_ref]], bp)
        rows_[area.area_ref] = g.id
    await ctx.record("prepare_layout", target_id=root.id, payload={"generation_id": row.id, "areas": len(ids)},
                     hidden=True)  # fmt: skip
    if notes is None:
        notes = [] if quality == "normal" else ["fallback:layout"]
    return {"schema_version": 1, "phase": "location_layout", "areas": ids, "geometry": rows_, "notes": notes}


async def _publish_geometry(ctx, row: WorldGenerationState) -> dict[str, Any]:
    res = dict(row.reservation or {})
    area = ctx.world.entities.get(row.target_entity_id)
    root = ctx.world.entities.get(res.get("root_id") or "")
    if area is None or root is None:
        raise Blocked("target_missing", "участка или комплекса больше нет")
    bp = store.blueprint_of(root)
    if bp is None or bp.revision != int(res.get("blueprint_rev") or 0):
        raise Blocked("stale_blueprint", "blueprint изменился после резерва")
    spec = bp.area(res.get("area_ref"))
    if spec is None:
        raise Blocked("target_missing", f"в blueprint нет участка {res.get('area_ref')}")
    current = (area.state or {}).get("sketch")
    if isinstance(current, dict) and current.get("cols") and not current.get("blueprint") and not current.get("auto"):
        return {"schema_version": 1, "phase": "location_geometry", "area_ref": spec.area_ref,
                "notes": ["manual_preserved"]}  # fmt: skip
    try:
        sk = geometry.build_area(bp, spec, root_id=root.id, ids=store.area_ids(root))
    except geometry.GeometryError as e:
        raise Blocked("geometry_invalid", "; ".join(e.errors[:6])) from e
    edit_rev = int((current or {}).get("edit_rev") or 0) + 1
    area.state = {**(area.state or {}), "sketch": {**sk, "auto": True, "edit_rev": edit_rev}}
    await ctx.record("prepare_geometry", target_id=area.id,
                     payload={"generation_id": row.id, "area_ref": spec.area_ref}, hidden=True)  # fmt: skip
    return {"schema_version": 1, "phase": "location_geometry", "area_ref": spec.area_ref, "notes": []}
