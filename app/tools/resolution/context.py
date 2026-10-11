"""Snapshot transient channels without copying SQLAlchemy-managed objects."""

import copy
from dataclasses import dataclass

from app.core.world import load_world
from app.tools.registry import ToolContext

CHANNELS = ("changed", "closed", "signals", "carded", "outbox", "audio", "sfx_requests", "notices", "resolved_actions")


async def refresh_world(ctx: ToolContext) -> None:
    """Refresh after serialization without losing the current audience."""
    focus, crew = ctx.world.focus, set(ctx.world.crew)
    await ctx.session.flush()
    await ctx.session.refresh(ctx.campaign)
    ctx.world = await load_world(ctx.session, ctx.campaign, ctx.world.catalog, refresh=True)
    ctx.world.focus, ctx.world.crew = focus, crew


@dataclass
class ContextSnapshot:
    channels: dict
    events: list
    call_key: str | None
    first_event: object
    focus: str | None
    crew: set[str]


def snapshot_context(ctx: ToolContext) -> ContextSnapshot:
    return ContextSnapshot(
        {name: copy.deepcopy(getattr(ctx, name)) for name in CHANNELS},
        list(ctx.events),
        ctx.call_key,
        ctx._first_event,
        ctx.world.focus,
        set(ctx.world.crew),
    )


def restore_context(ctx: ToolContext, snapshot: ContextSnapshot) -> None:
    for name, value in snapshot.channels.items():
        setattr(ctx, name, copy.deepcopy(value))
    ctx.events = list(snapshot.events)
    ctx.call_key, ctx._first_event = snapshot.call_key, snapshot.first_event
    ctx.world.focus, ctx.world.crew = snapshot.focus, set(snapshot.crew)
