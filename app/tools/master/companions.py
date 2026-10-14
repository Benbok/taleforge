"""Master tools for attaching a creature to a hero and ending that bond."""

from __future__ import annotations

import copy

from pydantic import BaseModel, Field

from app.core.companions import companion_record
from app.core.world import PLAYABLE
from app.tools.registry import AFTER_CALL, ToolContext, ToolError, tool


def _entity(ctx: ToolContext, entity_id: str):
    entity = ctx.world.entities.get(entity_id)
    if entity is None or entity.kind != "creature":
        raise ToolError("спутником может быть только существо текущей кампании")
    return entity


def _hero(ctx: ToolContext, hero_id: str):
    hero = ctx.world.characters.get(hero_id)
    if hero is None or hero.status not in PLAYABLE:
        raise ToolError("герой не участвует в игре")
    return hero


def _basis(ctx: ToolContext, entity_id: str, hero_id: str, event_id: str):
    event = next((event for event in ctx.events if event.id == event_id), None)
    if event is None or event.turn_id != ctx.turn_id or event.actor_id != hero_id or event.target_id != entity_id:
        raise ToolError("основание спутника должно быть событием этого хода от этого героя для этого NPC")
    if event.tool == "roll_check":
        payload = event.payload or {}
        if payload.get("kind") == "check" and payload.get("stat") in {
            "persuasion",
            "deception",
            "intimidation",
            "performance",
        } and payload.get("success"):
            return event
    if event.tool == "pass_item" and not event.hidden:
        return event
    raise ToolError("основанием спутника может быть только успешная социальная проверка или передача вещи")


class JoinPartyArgs(BaseModel):
    entity_id: str
    hero_id: str
    basis_event_id: str = Field(min_length=1)
    reason: str = Field(min_length=1, max_length=500)


@tool(
    "join_party",
    "Связывает NPC со своим героем. Требует basis_event_id события этого хода: "
    "успешной социальной проверки или передачи вещи.",
    JoinPartyArgs,
    ids={"entity_id": "entities", "hero_id": "characters"},
    closes=False,
)
async def join_party(ctx: ToolContext, a: JoinPartyArgs) -> dict:
    entity = _entity(ctx, a.entity_id)
    hero = _hero(ctx, a.hero_id)
    state = dict(entity.state or {})
    if companion_record(entity) is not None:
        raise ToolError("этот NPC уже идёт с первым договорившимся героем")
    if state.get("dead") or state.get("fled"):
        raise ToolError("мёртвый или сбежавший NPC спутником не становится")
    if state.get("attitude", "hostile") == "hostile":
        raise ToolError("враждебного NPC нельзя взять в спутники")
    basis = _basis(ctx, entity.id, hero.id, a.basis_event_id)
    inverse = [
        {"table": "entities", "id": entity.id, "field": "state", "before": copy.deepcopy(entity.state)},
    ]
    state["companion"] = {"of": hero.id, "since_event": basis.id, "reason": a.reason}
    state["attitude"] = "friendly"
    entity.state = state
    ctx.world.invalidate(entity.id)
    ctx.changed.add(entity.id)
    ctx.changed.add(hero.id)
    result = {
        "entity_id": entity.id,
        "entity": entity.name,
        "hero_id": hero.id,
        "hero": hero.name,
        "since_event": basis.id,
        "reason": a.reason,
    }
    await ctx.record("join_party", actor_id=hero.id, target_id=entity.id, payload=result, inverse=inverse)
    ctx.outbox.append({"kind": "system", "content": f"{entity.name} теперь идёт с {hero.name}."})
    return result


class LeavePartyArgs(BaseModel):
    entity_id: str
    reason: str = Field(min_length=1, max_length=500)
    turn_hostile: bool = False
    plot_id: str | None = None
    betrayal_note: str | None = Field(None, max_length=500)


@tool(
    "leave_party",
    "Снимает связь NPC со спутником. Для предательства turn_hostile=true нужна "
    "ссылка на plot_id NPC или betrayal_note.",
    LeavePartyArgs,
    ids={"entity_id": "entities"},
    closes=False,
)
async def leave_party(ctx: ToolContext, a: LeavePartyArgs) -> dict:
    entity = _entity(ctx, a.entity_id)
    record = companion_record(entity)
    if record is None:
        raise ToolError("у этого NPC нет связи со спутником")
    if a.turn_hostile:
        expected_plot = (entity.state or {}).get("plot_id")
        if not a.betrayal_note and (not a.plot_id or a.plot_id != expected_plot):
            raise ToolError("для предательства нужна ссылка на plot_id NPC или betrayal_note")
    inverse = [
        {"table": "entities", "id": entity.id, "field": "state", "before": copy.deepcopy(entity.state)},
    ]
    state = dict(entity.state or {})
    state.pop("companion", None)
    if a.turn_hostile:
        state["attitude"] = "hostile"
    entity.state = state
    ctx.world.invalidate(entity.id)
    ctx.changed.add(entity.id)
    ctx.changed.add(record["of"])
    result = {
        "entity_id": entity.id,
        "entity": entity.name,
        "hero_id": record["of"],
        "reason": a.reason,
        "turn_hostile": a.turn_hostile,
    }
    if a.turn_hostile:
        result["betrayal"] = True
    await ctx.record("leave_party", target_id=entity.id, payload=result, inverse=inverse)
    ctx.outbox.append({"kind": "system", "content": f"{entity.name} отстал."})
    if a.turn_hostile:
        from app.core import combat
        from app.tools.master.checks import roll_initiative

        if combat.in_combat(ctx) and entity.id not in {x["id"] for x in ctx.world.scene.turn_order}:
            entries, dice = roll_initiative(ctx, [entity.id])
            if entries:
                combat.insert(ctx, entries)
                result["initiative"] = entries[0]["initiative"]
                event = next(
                    (e for e in reversed(ctx.events) if e.tool == "leave_party" and e.target_id == entity.id),
                    None,
                )
                if event is not None:
                    event.dice = dice
                ctx.world.invalidate(entity.id)
    return result


async def reconcile_companions(ctx: ToolContext, result: dict) -> None:
    """Break links invalidated by ordinary state updates or owner elimination."""
    for entity in list(ctx.world.entities.values()):
        record = companion_record(entity)
        if record is None:
            continue
        owner = ctx.world.characters.get(record["of"])
        state = entity.state or {}
        reason = None
        if state.get("dead"):
            reason = "погиб"
        elif state.get("fled"):
            reason = "бежал"
        elif state.get("attitude", "hostile") == "hostile":
            reason = "стал враждебным"
        elif owner is None or owner.status not in PLAYABLE:
            reason = "герой выбыл"
        if reason is None:
            continue
        before = copy.deepcopy(entity.state)
        new_state = dict(entity.state or {})
        new_state.pop("companion", None)
        entity.state = new_state
        ctx.world.invalidate(entity.id)
        ctx.changed.add(entity.id)
        if owner is not None:
            ctx.changed.add(owner.id)
        payload = {"entity_id": entity.id, "entity": entity.name, "hero_id": record["of"], "reason": reason}
        await ctx.record(
            "companion_break",
            target_id=entity.id,
            payload=payload,
            inverse=[{"table": "entities", "id": entity.id, "field": "state", "before": before}],
        )
        ctx.outbox.append({"kind": "system", "content": f"{entity.name} отстал: {reason}."})


AFTER_CALL.append(reconcile_companions)
