"""Durable identity of player requests; binding never reparses an existing source."""

import copy
import hashlib
import json

from sqlalchemy import select, update

from app.core import adventure
from app.core.resolution.contracts import ActionContext, ActionRef
from app.db.models import Event, Message, Scene
from app.tools.registry import ToolContext, ToolError


def action_key(ref: ActionRef) -> str:
    raw = json.dumps(ref.model_dump(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def bind_message_actions(message: Message, actor_id: str) -> list[ActionRef]:
    data = message.data or {}
    existing = data.get("resolution_actions")
    if existing is not None:
        refs = [ActionRef.model_validate(item["ref"]) for item in existing]
        if any(
            r.actor_id != actor_id or r.campaign_id != message.campaign_id or r.source_id != message.id for r in refs
        ):
            raise ValueError("resolution source identity mismatch")
        return refs
    actions = (message.intent or {}).get("actions") or []
    if not actions:
        return []
    refs = [
        ActionRef(
            campaign_id=message.campaign_id, source_kind="message", source_id=message.id, actor_id=actor_id, part=i
        )
        for i in range(len(actions))
    ]
    message.data = {
        **data,
        "resolution_actions": [
            {"ref": ref.model_dump(), "action": copy.deepcopy(action)}
            for ref, action in zip(refs, actions, strict=True)
        ],
    }
    return refs


def bind_world_action(campaign_id: str, response_id: str, actor_id: str) -> ActionRef:
    return ActionRef(
        campaign_id=campaign_id, source_kind="standing_response", source_id=response_id, actor_id=actor_id, part=0
    )


async def resolution_receipt(ctx: ToolContext, ref: ActionRef) -> Event | None:
    return await ctx.session.scalar(
        select(Event).where(
            Event.campaign_id == ref.campaign_id,
            Event.idempotency_key == action_key(ref),
            Event.tool == "resolve_action",
        )
    )


async def lock_resolution_source(ctx: ToolContext, ref: ActionRef) -> None:
    if ref.campaign_id != ctx.campaign.id:
        raise ToolError("чужая заявка", code="invalid_source", category="rule_denial")
    model = Message if ref.source_kind == "message" else Scene
    condition = (
        (Message.id == ref.source_id) & (Message.campaign_id == ref.campaign_id)
        if model is Message
        else (Scene.campaign_id == ref.campaign_id)
    )
    if ctx.session.get_bind().dialect.name == "sqlite":
        column = model.data if model is Message else model.state
        await ctx.session.execute(update(model).where(condition).values({column.key: column}))
    else:
        await ctx.session.execute(select(model).where(condition).with_for_update())


async def load_action_context(ctx: ToolContext, ref: ActionRef) -> ActionContext:
    """Only persisted, owned and still live sources can supply action facts."""

    def denied():
        return ToolError("заявка недоступна", code="invalid_source", category="rule_denial")

    if ref.campaign_id != ctx.campaign.id or ref.actor_id not in ctx.world.characters:
        raise denied()
    hero = ctx.world.characters[ref.actor_id]
    actions = []
    parsed = False
    if ref.source_kind == "message":
        message = await ctx.session.get(Message, ref.source_id)
        if (
            message is None
            or message.campaign_id != ref.campaign_id
            or message.kind != "action"
            or not hero.seat_id
            or message.seat_id != hero.seat_id
        ):
            raise denied()
        bound = (message.data or {}).get("resolution_actions") or []
        if ref.part >= len(bound) or ActionRef.model_validate(bound[ref.part]["ref"]) != ref:
            raise denied()
        actions = [item["action"] for item in bound]
        parsed = bool(actions) and (message.intent or {}).get("confidence", 1) >= 0.7
    elif ref.source_kind == "standing_response":
        responses = ((ctx.world.scene.state or {}).get("standing") or {}).get("responses", [])
        response = next((r for r in responses if r["id"] == ref.source_id), None)
        if response is None or response.get("status") != "ready" or ref.part != 0:
            raise denied()
        if response.get("targets") and ref.actor_id not in response["targets"]:
            raise denied()
        actions = [{"verb": "standing_response", "target_id": response.get("subject_id")}]
        parsed = True
    else:
        raise denied()  # Event sources need a verified adapter; no generic event authorization.
    verbs = tuple(a.get("verb", "") for a in actions)
    targets = tuple(dict.fromkeys(t for a in actions for t in [a.get("target_id"), *a.get("target_ids", [])] if t))
    combat_verbs = {"attack", "cast", "grapple", "shove", "dodge", "dash", "disengage"}
    place_id = ctx.world.place_of(hero)
    place = ctx.world.entities.get(place_id or "")
    module_known = not adventure.is_module(ctx.campaign)
    if not module_known and place is not None:
        module = adventure.module_place(place, ctx.world.catalog, ctx.world.entities)
        room = adventure.room_of(place)
        module_known = module is not None and (room is None or adventure.find_room(module[1], room["id"]) is not None)
    return ActionContext(
        ref=ref,
        verbs=verbs,
        target_ids=targets,
        place_id=place_id,
        parsed=parsed,
        affected_in_combat=ctx.world.in_fight(hero.id) or any(ctx.world.in_fight(t) for t in targets),
        combat_related=bool(set(verbs) & combat_verbs),
        completed_parts=(),
        module_data_known=module_known,
        canonical_denial=any(t not in ctx.world.characters and t not in ctx.world.entities for t in targets),
    )
