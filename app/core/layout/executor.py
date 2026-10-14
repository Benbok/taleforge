"""Исполнители фаз ``location_layout`` и ``location_geometry`` (спецификация 2026-10-12, §3.2, §3.3, §8).

Структура: provider предлагает blueprint из замысла резерва — сначала обычный, затем упрощённый fallback; ни тот, ни
другой не выполнили обязательств — ``blocked``, несогласованный результат не публикуется. Публикация — одна
``world_write``: участки с реальными id, blueprint, живые проходы и резервы геометрии всех участков (не запрошенные).
Геометрия: эскиз участка строится кодом из зафиксированного blueprint; ручной эскиз мастера остаётся.
"""

from __future__ import annotations

import logging
from dataclasses import asdict, replace
from typing import Any

from pydantic import ValidationError
from sqlalchemy import func, select

from app.core.layout import geometry, store
from app.core.layout.contracts import Blueprint, LayoutError
from app.core.layout.intent import LayoutIntent
from app.core.world_generation import storage
from app.core.world_generation.contracts import Blocked
from app.core.world_generation.storage import Claim
from app.db.models import Campaign, Entity, LlmCall, WorldGenerationState

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
    """Замысел резерва → blueprint. Ручной замысел ведущего — как в поставке 1. Мандат каркаса — сначала модель
    (если включена и расходы позволяют), затем лестница детерминированных замыслов. Ни один не лёг — ``blocked``."""
    from app.core import plot_anchors
    from app.core.layout import spatial
    from app.core.world_generation.service import _model_of

    async with maker() as s:
        row = await s.get(WorldGenerationState, claim.ref)
        res = dict(row.reservation or {})
        waiting = [b.anchor_id for b in await plot_anchors.reserved_for(s, claim.campaign_id, row.target_entity_id)]
        campaign = await s.get(Campaign, claim.campaign_id)
        wants = llm is not None and "mandate" in res and bool((campaign.settings or {}).get("location_layouts_llm"))
        model = await _model_of(s, campaign) if wants else None
        over = wants and await _over_spend(s, campaign)
    kw = {"seed": int(res["seed"]), "root_id": res["root_id"], "plot_id": res.get("plot_id")}
    notes: list[str] = []
    diagnostics: list[str] = []
    try:
        mandate = spatial.Mandate.model_validate(res["mandate"]) if "mandate" in res else None
        intent0 = None if mandate is not None else LayoutIntent.model_validate(res["intent"])
    except (KeyError, ValidationError) as e:
        raise Blocked("unsupported_source", str(e)[:500]) from e
    if mandate is not None:
        selection = res.get("template_selection")
        if isinstance(selection, dict) and selection.get("outcome") == "selected":
            try:
                if selection.get("schema_version") != 1:
                    raise ValueError("unsupported template snapshot")
                template_intent = LayoutIntent.model_validate(selection["intent"])
                if spatial.obligations(template_intent, mandate):
                    raise ValueError("template violates mandate")
                blueprint = provider.propose(template_intent, **kw)
            except (KeyError, ValueError, ValidationError, LayoutError):
                log.info("layout %s: template snapshot rejected", claim.ref)
                diagnostics.append("template_rejected:snapshot_invalid")
            else:
                return _with_anchors(blueprint, waiting), "normal", [
                    f"source:template:{selection.get('id')}:{selection.get('version')}"
                ], claim
        elif isinstance(selection, dict):
            diagnostics.append(f"template_rejected:{selection.get('reason', 'no_candidate')}")
        if over:
            notes.append("fallback:spend_limit")
        elif model is not None:
            intent, reason, claim = await _ask_model(maker, claim, llm, model, mandate, provider, kw)
            if intent is not None:
                return _with_anchors(provider.propose(intent, **kw), waiting), "normal", notes + diagnostics, claim
            notes.append(f"fallback:{reason}")
        candidates = spatial.intent_candidates(mandate)
    else:
        candidates = [intent0]
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
            if i > 0 or fallback:
                notes.append("fallback:layout")
            return _with_anchors(bp, waiting), quality, notes + diagnostics, claim
    raise Blocked("layout_unsatisfiable", "; ".join(errors[:6]))


async def _over_spend(s, campaign) -> bool:
    limit = (campaign.settings or {}).get("spend_limit_usd")
    if limit is None:
        return False
    spent = await s.scalar(select(func.sum(LlmCall.cost)).where(LlmCall.campaign_id == campaign.id))
    return float(spent or 0.0) >= float(limit)


async def _ask_model(maker, claim, llm, model, mandate, provider, kw) -> tuple[LayoutIntent | None, str, Claim]:
    """Замысел модели в пределах лимита фазы (``LLM_LIMIT``); вызов занимается до сетевого запроса, учёт —
    в ``LlmCall`` с ``generation_id``. Возвращает (замысел или None, причина fallback, обновлённый claim)."""
    from app.agents import layout_model
    from app.core.world_generation.service import LLM_LIMIT

    name, api_base, seat_id = model
    if layout_model.brief(mandate) is None:
        return None, "context_budget", claim
    msgs: list = []
    calls: list[LlmCall] = []
    reason = "llm_failed"

    def check(intent: LayoutIntent) -> None:
        provider.propose(intent, **kw)

    try:
        while True:
            if msgs and layout_model.input_estimate(mandate, msgs) > layout_model.MAX_IN:
                reason = "context_budget"
                break  # не занимаем попытку и не пишем LlmCall без сетевого вызова
            held = await storage.reserve_llm_call(maker, claim, LLM_LIMIT)
            if held is None:
                reason = reason if calls else "llm_limit"
                break
            claim = held
            got, attempt, retry = await layout_model.ask(
                llm, mandate, model=name, api_base=api_base, msgs=msgs, check=check
            )
            calls.append(
                LlmCall(
                    campaign_id=claim.campaign_id,
                    seat_id=seat_id,
                    turn_id=None,
                    purpose=layout_model.PURPOSE,
                    model=attempt.model,
                    tokens_in=attempt.tokens_in,
                    tokens_out=attempt.tokens_out,
                    tokens_reasoning=attempt.tokens_reasoning,
                    cost=attempt.cost,
                    latency_ms=attempt.latency_ms,
                    error=attempt.error,
                    generation_id=claim.ref,
                )
            )
            if got is not None:
                return got, "", claim
            if retry is None:
                break  # сбой модели, а не ошибка ответа: корректировать нечего
            reason = "invalid_proposal"
    finally:
        if calls:
            async with maker() as s:
                s.add_all(calls)
                await s.commit()
    log.info("структура %s: fallback (%s)", claim.ref, reason)
    return None, reason, claim


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
        state: dict[str, Any] = {"complex": {"root_id": root.id, "area_ref": area.area_ref}, "role": area.role}
        if area.scene_profile is not None:
            state["scene_profile"] = area.scene_profile
        if area.object_slots:
            state["object_slots"] = [dict(asdict(slot), feature_id=f"sf_{area.area_ref}_{slot.detail_ref}"[:32]
                                         if slot.detail_ref else None) for slot in area.object_slots]
        if area.secret:
            state["secret"] = True
        en = Entity(campaign_id=ctx.campaign.id, kind="location", name=area.public_name,
                    description=area.description, location_id=root.id, state=state)  # fmt: skip
        ctx.session.add(en)
        await ctx.session.flush()
        ctx.world.entities[en.id] = en
        ids[area.area_ref] = en.id
    residents: list[str] = []
    for key, ref in bp.anchors.items():
        if not key.startswith("npc:"):
            continue
        for en in list(ctx.world.entities.values()):
            if en.kind == "creature" and en.location_id == root.id and (en.state or {}).get("plot_id") == key[4:]:
                en.location_id = ids[ref]  # житель каркаса переходит в свой участок вместе с публикацией
                residents.append(en.id)
    passages = {p.passage_ref: {"state": p.state, "hidden": p.hidden} for p in bp.passages}
    root.state = {**(root.state or {}), "blueprint": bp.to_json(), "areas": ids, "passages": passages}
    from app.core.world_generation.storage import reserve_complex

    await reserve_complex(ctx, root, bp)
    rows_ = {}
    for area in bp.areas:
        g = await store.reserve_geometry(ctx.session, ctx.campaign.id, root, ctx.world.entities[ids[area.area_ref]], bp)
        rows_[area.area_ref] = g.id
    await ctx.record("prepare_layout", target_id=root.id, payload={"generation_id": row.id, "areas": len(ids)},
                     hidden=True)  # fmt: skip
    if notes is None:
        notes = [] if quality == "normal" else ["fallback:layout"]
    return {
        "schema_version": 1,
        "phase": "location_layout",
        "areas": ids,
        "geometry": rows_,
        "residents": residents,
        "notes": [n for n in notes if not n.startswith(("source:template:", "template_rejected:"))],
        "source": next((n for n in notes if n.startswith("source:template:")), "generated"),
        "template_fallback": next((n.removeprefix("template_rejected:") for n in notes
                                   if n.startswith("template_rejected:")), None),
    }


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
