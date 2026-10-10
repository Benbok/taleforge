"""Atomic consequence groups; outer turn still owns commit and publication."""

import hashlib

from app.core.resolution.contracts import Admission, ResolutionResult, normalize_result
from app.core.world import load_world
from app.tools.registry import ToolContext, execute
from app.tools.resolution.context import restore_context, snapshot_context
from app.tools.resolution.operations import OPERATION_TOOLS, ResolutionProposal
from app.tools.resolution.requests import action_key, load_action_context, lock_resolution_source, resolution_receipt


async def execute_resolution(ctx: ToolContext, proposal: ResolutionProposal, admission: Admission) -> ResolutionResult:
    if admission.route not in {"ordinary", "fallback"}:
        return ResolutionResult(execution="denied")
    await lock_resolution_source(ctx, proposal.ref)
    receipt = await resolution_receipt(ctx, proposal.ref)
    if receipt is not None:
        return ResolutionResult.model_validate(receipt.payload["resolution"]).model_copy(
            update={"execution": "repeated"}
        )
    await load_action_context(ctx, proposal.ref)
    snapshot = snapshot_context(ctx)
    nested = await ctx.session.begin_nested()
    event_ids = []
    try:
        for index, operation in enumerate(proposal.operations):
            name, _ = OPERATION_TOOLS[operation.kind]
            raw = await execute(ctx, name, operation.args.model_dump(), key=f"{action_key(proposal.ref)[:48]}:{index}")
            if not raw["ok"]:
                await nested.rollback()
                await ctx.session.refresh(ctx.campaign)
                ctx.world = await load_world(ctx.session, ctx.campaign, ctx.world.catalog)
                restore_context(ctx, snapshot)
                return normalize_result(raw, attempt_id=proposal.attempt_id or "")
            if raw.get("event_id"):
                event_ids.append(raw["event_id"])
        result = ResolutionResult(
            execution="applied",
            game_outcome=proposal.outcome,
            event_ids=event_ids,
            completed_parts=[proposal.ref.part],
        )
        ctx.call_key, ctx._first_event = action_key(proposal.ref), None
        receipt = await ctx.record(
            "resolve_action",
            actor_id=proposal.ref.actor_id,
            hidden=True,
            payload={
                "schema_version": 1,
                "fingerprint": hashlib.sha256(proposal.model_dump_json().encode()).hexdigest(),
                "ref": proposal.ref.model_dump(),
                "origin": proposal.origin,
                "outcome": proposal.outcome,
                "reason": proposal.reason,
                "attempt_id": proposal.attempt_id,
                "resolution": result.model_dump(),
            },
        )
        await nested.commit()
    except Exception:
        await nested.rollback()
        await ctx.session.refresh(ctx.campaign)
        ctx.world = await load_world(ctx.session, ctx.campaign, ctx.world.catalog)
        restore_context(ctx, snapshot)
        raise  # Unknown and database errors must never become safe fallback grants.
    ctx.call_key, ctx._first_event = snapshot.call_key, snapshot.first_event
    return result
