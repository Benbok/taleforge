"""Server-owned narrative adaptation slots for turn context (Task 10)."""

from __future__ import annotations

from app.core.narrative.contracts import NarrativeSource
from app.db.models import MasterTurn
from app.tools.registry import ToolContext


async def bind_scene_sources(ctx: ToolContext) -> tuple[NarrativeSource, ...]:
    """Bind 3 stable server-owned adaptation slots (stable_part=0..2) on current turn.

    Slots are persisted in MasterTurn.trace['narrative_slots'] and not reset on retry.
    """
    turn = await ctx.session.get(MasterTurn, ctx.turn_id) if ctx.turn_id else None
    if turn is not None and (turn.trace or {}).get("narrative_slots"):
        raw_slots = turn.trace["narrative_slots"]
        return tuple(NarrativeSource.model_validate(s) for s in raw_slots)

    slots = tuple(
        NarrativeSource(
            campaign_id=ctx.campaign.id,
            scope="scene",
            source_kind="turn",
            source_id=ctx.turn_id or "turn-0",
            stable_part=i,
        )
        for i in range(3)
    )
    if turn is not None:
        turn.trace = {**(turn.trace or {}), "narrative_slots": [s.model_dump() for s in slots]}
        ctx.turn_diagnostics["narrative_slots"] = [s.model_dump() for s in slots]
    return slots
