"""Atomic consequence groups; outer turn still owns commit and publication."""

from app.core.resolution.contracts import Admission, ResolutionResult, normalize_result
from app.core.world import load_world
from app.tools.registry import ToolContext, execute
from app.tools.resolution.context import restore_context, snapshot_context
from app.tools.resolution.operations import OPERATION_TOOLS, ResolutionProposal


async def execute_resolution(ctx: ToolContext, proposal: ResolutionProposal, admission: Admission) -> ResolutionResult:
    if admission.route not in {"ordinary", "fallback"}:
        return ResolutionResult(execution="denied")
    snapshot = snapshot_context(ctx)
    nested = await ctx.session.begin_nested()
    event_ids = []
    try:
        for operation in proposal.operations:
            name, _ = OPERATION_TOOLS[operation.kind]
            raw = await execute(ctx, name, operation.args.model_dump())
            if not raw["ok"]:
                await nested.rollback()
                await ctx.session.refresh(ctx.campaign)
                ctx.world = await load_world(ctx.session, ctx.campaign, ctx.world.catalog)
                restore_context(ctx, snapshot)
                return normalize_result(raw, attempt_id=proposal.attempt_id or "")
            if raw.get("event_id"):
                event_ids.append(raw["event_id"])
        await nested.commit()
    except Exception:
        await nested.rollback()
        await ctx.session.refresh(ctx.campaign)
        ctx.world = await load_world(ctx.session, ctx.campaign, ctx.world.catalog)
        restore_context(ctx, snapshot)
        raise  # Unknown and database errors must never become safe fallback grants.
    ctx.call_key, ctx._first_event = snapshot.call_key, snapshot.first_event
    return ResolutionResult(
        execution="applied", game_outcome=proposal.outcome, event_ids=event_ids, completed_parts=[proposal.ref.part]
    )
