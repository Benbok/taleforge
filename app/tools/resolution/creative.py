"""Verified creative opportunities and proposal admission; no LLM dependency."""

from dataclasses import dataclass

from app.core import adventure
from app.core.resolution.contracts import Admission, ResolutionResult
from app.core.resolution.policy import admit
from app.db.models import MasterTurn, Message
from app.tools.registry import ToolContext
from app.tools.resolution.capabilities import CAPABILITIES
from app.tools.resolution.requests import latest_attempt, load_action_context


@dataclass(frozen=True)
class CreativeOpportunity:
    place_id: str
    kind: str
    subject_id: str | None = None


def autonomous_neutral_spawn_allowed(ctx: ToolContext, args, place_id: str | None) -> bool:
    """Ordinary AI calls cannot bypass creative space admission."""
    if any(op.place_id == place_id and op.kind == "new_neutral" for op in creative_opportunities(ctx)):
        return True
    place = ctx.world.entities.get(place_id or "")
    module = adventure.module_place(place, ctx.world.catalog, ctx.world.entities)
    room_ref = adventure.room_of(place)
    room = adventure.find_room(module[1], room_ref["id"]) if module and room_ref else None
    if room:
        count = adventure.book_encounter(place, ctx.world.catalog, ctx.world.entities, args.creature_template_id)
        present = sum(
            1
            for entity in ctx.world.entities.values()
            if entity.location_id == place_id and entity.template_id == args.creature_template_id
        )
        return present + args.count <= count
    return False  # Existing plot sketches must use develop, not duplicate spawn.


def creative_opportunities(ctx: ToolContext) -> list[CreativeOpportunity]:
    world = ctx.world
    opportunities = []
    for place_id in world.scene_places():
        place = world.entities.get(place_id)
        if place is None or place.kind != "location":
            continue
        for actor in world.in_scene_entities(place_id):
            if actor.kind == "creature" and not (actor.state or {}).get("dead"):
                opportunities.append(CreativeOpportunity(place_id, "reuse_actor", actor.id))
        plot_id = (place.state or {}).get("plot_id")
        for npc in world.plot.get("npcs") or []:
            if plot_id and npc.get("location_id") == plot_id and not npc.get("entity_id"):
                opportunities.append(CreativeOpportunity(place_id, "reuse_sketch", npc["id"]))
        # Only procedural, untemplated places outside canonical plot/module
        # namespaces admit a new neutral NPC. Missing parents deny freedom.
        free = not adventure.is_module(ctx.campaign)
        current, visited = place, set()
        while current is not None and current.id not in visited:
            visited.add(current.id)
            if current.template_id or (current.state or {}).get("plot_id") or adventure.room_of(current):
                free = False
            parent_id = current.location_id
            current = world.entities.get(parent_id) if parent_id else None
            if parent_id and current is None:
                free = False
        if current is not None:  # cyclic ownership is not a verified free namespace
            free = False
        if free and not any(o.place_id == place_id and o.kind == "reuse_sketch" for o in opportunities):
            opportunities.append(CreativeOpportunity(place_id, "new_neutral"))
    return opportunities


async def validate_creative_proposal(ctx: ToolContext, proposal) -> Admission:
    context = await load_action_context(ctx, proposal.ref)
    capability = CAPABILITIES["creative.neutral_npc"]
    admission = admit(context, capability, None)
    if proposal.origin != "creative" or admission.route != "ordinary":
        return Admission("deny", "creative_not_admitted")
    message = await ctx.session.get(Message, proposal.ref.source_id)
    if message is None or message.turn_id != ctx.turn_id:
        return Admission("deny", "invalid_source")
    turn = await ctx.session.get(MasterTurn, ctx.turn_id)
    if turn and any(
        attempt["actor_id"] == proposal.ref.actor_id
        for attempt in (turn.trace or {}).get("resolution_unbound_attempts", [])
    ):
        return Admission("deny", "ambiguous_action_part")
    latest = await latest_attempt(ctx, proposal.ref)
    if latest and ResolutionResult.model_validate(latest["result"]).execution in {"denied", "failed"}:
        return Admission("deny", "failed_action_requires_fallback")
    completed = (message.data or {}).get("resolution_completed", {}).get(str(proposal.ref.part))
    if completed and ResolutionResult.model_validate(completed).game_outcome != proposal.outcome:
        return Admission("deny", "confirmed_outcome_is_immutable")
    free_places = {op.place_id for op in creative_opportunities(ctx) if op.kind == "new_neutral"}
    for operation in proposal.operations:
        if operation.kind not in capability.operations:
            return Admission("deny", "operation_not_admitted")
        if operation.kind == "neutral_npc":
            args = operation.args
            if args.location_id != context.place_id or args.location_id not in free_places or args.count != 1:
                return Admission("deny", "canon_not_free")
            if any(e.name.casefold() == args.name.casefold() for e in ctx.world.in_scene_entities(context.place_id)):
                return Admission("deny", "reuse_existing_actor")
    return admission
