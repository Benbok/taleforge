"""Durable identity of player requests; binding never reparses an existing source."""

import copy
import hashlib
import json

from sqlalchemy import select, update

from app.core import adventure
from app.core.resolution.contracts import ActionContext, ActionRef, ResolutionResult
from app.db.models import Event, MasterTurn, Message, Scene, new_id
from app.tools.registry import ToolContext, ToolError


def action_key(ref: ActionRef) -> str:
    raw = json.dumps(ref.model_dump(), sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def deed_key(ref: ActionRef, subject_id: str) -> str:
    return hashlib.sha256(f"deed:{action_key(ref)}:{subject_id}".encode()).hexdigest()


def bound_tool_key(ctx: ToolContext, name: str, args: dict, default: str) -> str:
    if name == "roll_check":
        refs = [ref for ref in ctx.required_actions if ref.actor_id == args.get("character_id")]
        if refs:
            source = ":".join(sorted(action_key(ref) for ref in refs))
            return hashlib.sha256(f"primary_check:{source}".encode()).hexdigest()
    if name != "record_deed":
        return default
    actors = set(args.get("character_ids") or [])
    refs = [ref for ref in ctx.required_actions if ref.actor_id in actors]
    if len(refs) != 1 or not args.get("subject_id"):
        return default
    return deed_key(refs[0], args["subject_id"])


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
    completed_parts = ()
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
        completed_parts = tuple(int(part) for part in (message.data or {}).get("resolution_completed", {}))
        parsed = bool(actions) and (message.intent or {}).get("confidence", 1) >= 0.7
    elif ref.source_kind == "standing_response":
        responses = ((ctx.world.scene.state or {}).get("standing") or {}).get("responses", [])
        response = next((r for r in responses if r["id"] == ref.source_id), None)
        if response is None or response.get("status") != "ready" or ref.part != 0:
            raise denied()
        if response.get("target_ids") and ref.actor_id not in response["target_ids"]:
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
        completed_parts=completed_parts,
        module_data_known=module_known,
        canonical_denial=any(
            t not in ctx.world.characters
            and t not in ctx.world.entities
            and not (ref.source_kind == "standing_response" and ctx.world.catalog.find(t, "faction"))
            for t in targets
        ),
    )


async def record_attempt(ctx: ToolContext, ref: ActionRef, capability_id: str, result: ResolutionResult) -> str:
    await load_action_context(ctx, ref)
    turn = await ctx.session.get(MasterTurn, ctx.turn_id) if ctx.turn_id else None
    message = await ctx.session.get(Message, ref.source_id) if ref.source_kind == "message" else None
    if (
        turn is None
        or turn.campaign_id != ref.campaign_id
        or turn.status != "running"
        or (message is not None and message.turn_id != ctx.turn_id)
    ):
        raise ToolError("попытка другого хода", code="invalid_attempt", category="rule_denial")
    attempt_id = new_id("ra")
    result = result.model_copy(deep=True)
    if result.failure:
        result.failure.attempt_id = attempt_id
    attempts = list((turn.trace or {}).get("resolution_attempts") or [])
    attempts.append(
        {
            "schema_version": 1,
            "id": attempt_id,
            "ref": ref.model_dump(),
            "capability_id": capability_id,
            "result": result.model_dump(),
        }
    )
    turn.trace = {**(turn.trace or {}), "resolution_attempts": attempts}
    ctx.turn_diagnostics["resolution_attempts"] = copy.deepcopy(attempts)
    if message is not None and result.execution in {"applied", "repeated"}:
        completed = dict((message.data or {}).get("resolution_completed") or {})
        completed.setdefault(str(ref.part), result.model_dump())
        message.data = {**(message.data or {}), "resolution_completed": completed}
    return attempt_id


async def eligible_adjudications(ctx: ToolContext) -> list[dict]:
    from app.core.resolution.policy import admit
    from app.tools.resolution.capabilities import CAPABILITIES

    turn = await ctx.session.get(MasterTurn, ctx.turn_id) if ctx.turn_id else None
    if turn is None or turn.campaign_id != ctx.campaign.id or turn.status != "running":
        return []
    latest = {}
    for attempt in (turn.trace or {}).get("resolution_attempts") or []:
        ref = ActionRef.model_validate(attempt["ref"])
        latest[action_key(ref)] = attempt
    eligible = []
    for attempt in latest.values():
        ref = ActionRef.model_validate(attempt["ref"])
        if await resolution_receipt(ctx, ref) is not None:
            continue
        result = ResolutionResult.model_validate(attempt["result"])
        capability = CAPABILITIES.get(attempt["capability_id"])
        if capability is None or result.failure is None:
            continue
        try:
            context = await load_action_context(ctx, ref)
        except ToolError:
            continue
        if ref.source_kind == "message":
            message = await ctx.session.get(Message, ref.source_id)
            if message.turn_id != ctx.turn_id:
                continue
        admission = admit(context, capability, result.failure)
        if admission.route == "fallback" and ref.part not in context.completed_parts:
            eligible.append(
                {
                    "ref": ref.model_dump(),
                    "attempt_id": attempt["id"],
                    "capability_id": capability.id,
                    "failure_code": result.failure.code,
                }
            )
    return eligible


def mark_resolved(ctx: ToolContext, ref: ActionRef) -> None:
    ctx.resolved_actions.add(action_key(ref))
    required = [r for r in ctx.required_actions if r.actor_id == ref.actor_id]
    if required and all(action_key(r) in ctx.resolved_actions for r in required):
        ctx.closed.add(ref.actor_id)
    elif required:
        ctx.closed.discard(ref.actor_id)


async def record_operations(ctx: ToolContext, operations: list[dict]) -> None:
    """Keep child diagnostics even when the consequence savepoint was rolled back."""
    turn = await ctx.session.get(MasterTurn, ctx.turn_id) if ctx.turn_id else None
    if turn is not None and turn.campaign_id == ctx.campaign.id:
        turn.trace = {
            **(turn.trace or {}),
            "resolution_operations": [*(turn.trace or {}).get("resolution_operations", []), *operations],
        }
        ctx.turn_diagnostics["resolution_operations"] = copy.deepcopy(turn.trace["resolution_operations"])


async def latest_attempt(ctx: ToolContext, ref: ActionRef) -> dict | None:
    turn = await ctx.session.get(MasterTurn, ctx.turn_id) if ctx.turn_id else None
    return (
        next(
            (
                a
                for a in reversed((turn.trace or {}).get("resolution_attempts", []))
                if action_key(ActionRef.model_validate(a["ref"])) == action_key(ref)
            ),
            None,
        )
        if turn
        else None
    )
