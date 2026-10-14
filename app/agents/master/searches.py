"""Require a persisted discovery for a successful search before narration."""

from typing import Any

from app.core.object_policy import concealed
from app.core.world import is_scene_item
from app.tools.registry import ToolContext

SEARCH_STATS = frozenset({"perception", "investigation", "search"})


def legacy_unresolved_searches(ctx: ToolContext) -> list[str]:
    pending = set()
    for index, check in enumerate(ctx.events):
        if (
            check.tool != "roll_check"
            or check.actor_id not in ctx.world.characters
            or check.payload.get("kind") != "check"
            or not check.payload.get("success")
            or check.payload.get("stat") not in SEARCH_STATS
        ):
            continue
        actor = check.actor_id
        confirmed = False
        for event in ctx.events[index + 1 :]:
            if event.tool == "learn_fact" and event.actor_id == actor:
                confirmed = check.target_id is None or event.target_id == check.target_id
            elif event.tool == "reveal_knowledge" and event.actor_id == actor:
                gained = any(
                    delta.get("table") == "knowledge"
                    and (
                        delta.get("field") == "level"
                        and event.payload.get("level", 0) > (delta.get("before") or 0)
                        or delta.get("field") == "revealed_at"
                        and delta.get("before") is None
                    )
                    for delta in event.inverse or []
                )
                confirmed = (check.target_id is None or event.target_id == check.target_id) and gained
            elif event.tool == "place_item":
                item = ctx.world.entities.get(event.target_id)
                confirmed = bool(
                    item
                    and is_scene_item(item)
                    and event.payload.get("discovery_check_event_id") == check.id
                    and item.location_id == ctx.world.place_of(ctx.world.characters[actor])
                    and (not concealed(item, ctx.world.entities) or item.id in ctx.world.revealed.get(actor, set()))
                )
            if confirmed:
                break
        if not confirmed:
            pending.add(actor)
    return sorted(pending)


def unresolved_searches(ctx: ToolContext) -> list[Any]:
    if getattr(ctx, "required_actions", None):
        from app.agents.master.action_progress import unresolved_searches as multipart_searches

        return multipart_searches(ctx)
    return legacy_unresolved_searches(ctx)

