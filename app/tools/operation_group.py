"""Atomic runner for registered consequence and adaptation operation groups."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from app.core.world import load_world
from app.db.models import Event
from app.tools.registry import InternalGrant, ToolContext, ToolError, execute
from app.tools.resolution.context import restore_context, snapshot_context


@dataclass(frozen=True)
class CompiledCall:
    """Executable registered tool call with bindings and metadata."""

    tool: str
    args: dict[str, Any]
    call_key: str | None = None
    local_binding: str | None = None
    hidden: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class GroupResult:
    """Outcome of executing an atomic operation group within a savepoint."""

    ok: bool
    event_ids: tuple[str, ...] = ()
    diagnostics: tuple[dict[str, Any], ...] = ()
    error: ToolError | Exception | None = None
    raw_error: dict[str, Any] | None = None
    bindings: dict[str, Any] = field(default_factory=dict)


async def run_operation_group(
    ctx: ToolContext,
    calls: tuple[CompiledCall, ...],
    *,
    validate_step: Callable[[ToolContext, CompiledCall, dict[str, Any]], None] | None = None,
    annotate_event: Callable[[Event, CompiledCall], None] | None = None,
    grant: InternalGrant | None = None,
) -> GroupResult:
    """Execute a sequence of compiled tool calls atomically in a savepoint.

    - Catches failures and rolls back the savepoint, reloading world and restoring context.
    - Preserves world focus and crew upon rollback.
    - Tracks call budget in ctx.resolution_calls_used.
    - Resolves local bindings across calls.
    - Does NOT commit the outer transaction or publish to the event bus.
    """
    snapshot = snapshot_context(ctx)
    nested = await ctx.session.begin_nested()
    event_ids: list[str] = []
    diagnostics: list[dict[str, Any]] = []
    bindings: dict[str, Any] = {}

    try:
        for call in calls:
            if validate_step is not None:
                validate_step(ctx, call, bindings)

            ctx.resolution_calls_used += 1

            # Substitute local bindings if present in args
            actual_args = dict(call.args)
            for k, v in actual_args.items():
                if isinstance(v, str) and v in bindings:
                    actual_args[k] = bindings[v]

            key = call.call_key
            event_start = len(ctx.events)
            raw = await execute(ctx, call.tool, actual_args, key=key, grant=grant)

            if call.hidden:
                for event in ctx.events[event_start:]:
                    event.hidden = True

            diagnostics.append(
                {
                    "tool": call.tool,
                    "args": actual_args,
                    "result": raw,
                    "call_key": key,
                    "parent_call_key": snapshot.call_key,
                    **call.metadata,
                    "secret": bool(raw.get("result", {}).get("hidden"))
                    or any(event.hidden for event in ctx.events[event_start:]),
                }
            )

            if not raw["ok"]:
                await nested.rollback()
                await ctx.session.refresh(ctx.campaign)
                focus, crew = ctx.world.focus, set(ctx.world.crew)
                ctx.world = await load_world(ctx.session, ctx.campaign, ctx.world.catalog)
                ctx.world.focus, ctx.world.crew = focus, crew
                restore_context(ctx, snapshot)
                return GroupResult(
                    ok=False,
                    diagnostics=tuple(diagnostics),
                    raw_error=raw,
                    bindings=dict(bindings),
                )

            if raw.get("event_id"):
                event_ids.append(raw["event_id"])
            for event in ctx.events[event_start:]:
                event_ids.append(event.id)
                if annotate_event is not None:
                    annotate_event(event, call)

            # Record local binding from result if requested
            if call.local_binding:
                res_data = raw.get("result")
                if isinstance(res_data, dict):
                    inner_data = res_data.get("result") if isinstance(res_data.get("result"), dict) else res_data
                    if "entity_id" in inner_data:
                        bindings[call.local_binding] = inner_data["entity_id"]
                    elif "id" in inner_data:
                        bindings[call.local_binding] = inner_data["id"]
                    elif "spawned" in inner_data and isinstance(inner_data["spawned"], list) and inner_data["spawned"]:
                        bindings[call.local_binding] = inner_data["spawned"][0].get("id")

        await nested.commit()
        return GroupResult(
            ok=True,
            event_ids=tuple(dict.fromkeys(event_ids)),
            diagnostics=tuple(diagnostics),
            bindings=dict(bindings),
        )

    except Exception as error:
        await nested.rollback()
        await ctx.session.refresh(ctx.campaign)
        focus, crew = ctx.world.focus, set(ctx.world.crew)
        ctx.world = await load_world(ctx.session, ctx.campaign, ctx.world.catalog)
        ctx.world.focus, ctx.world.crew = focus, crew
        restore_context(ctx, snapshot)
        if isinstance(error, ToolError):
            return GroupResult(
                ok=False,
                diagnostics=tuple(diagnostics),
                error=error,
                bindings=dict(bindings),
            )
        raise
