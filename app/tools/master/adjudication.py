"""Native noncombat fallback, authorized exclusively by server attempts."""

from app.core.resolution.contracts import ActionProgress, ActionRef, Admission, Contract, ResolutionResult
from app.tools.registry import ToolContext, ToolError, tool
from app.tools.resolution.capabilities import CAPABILITIES
from app.tools.resolution.executor import execute_resolution
from app.tools.resolution.operations import ResolutionProposal
from app.tools.resolution.requests import (
    action_key,
    eligible_adjudications,
    record_attempt,
    resolution_receipt,
    set_action_progress,
)


class AdjudicationArgs(Contract):
    proposal: ResolutionProposal


async def _completed_result(ctx: ToolContext, ref: ActionRef, result: ResolutionResult) -> dict:
    if result.execution in {"applied", "repeated"} and ref.part in result.completed_parts:
        await set_action_progress(ctx, ref, ActionProgress(status="completed", result=result))
    return result.model_dump()


@tool(
    "adjudicate_action",
    "Внебоевое решение: fallback по допуску сервера, creative в проверенном свободном месте. Бой запрещён.",
    AdjudicationArgs,
    mutating=False,
    closes=False,
)
async def adjudicate_action(ctx: ToolContext, args: AdjudicationArgs) -> dict:
    proposal = args.proposal
    if (
        proposal.ref.campaign_id != ctx.campaign.id
        or proposal.ref.actor_id not in ctx.world.characters
        or (ctx.world.crew and proposal.ref.actor_id not in ctx.world.crew)
    ):
        raise ToolError("чужая заявка", code="invalid_source", category="rule_denial")
    receipt = await resolution_receipt(ctx, proposal.ref)
    if receipt is not None:
        from app.tools.resolution.context import refresh_world

        await refresh_world(ctx)
        # Restore completion from the receipt without admitting new world effects.
        result = ResolutionResult.model_validate(receipt.payload["resolution"]).model_copy(
            update={"execution": "repeated"}
        )
        return await _completed_result(ctx, proposal.ref, result)
    if proposal.origin == "normal" and proposal.ref.source_kind == "standing_response":
        from app.tools.resolution.standing import validate_standing_proposal

        admission = await validate_standing_proposal(ctx, proposal)
        if admission.route != "ordinary":
            raise ToolError("ответ мира недопустим", code=admission.reason_code, category="rule_denial")
        if max(1, len(proposal.operations)) > ctx.remaining_resolution_calls:
            raise ToolError("недостаточно бюджета вызовов", code="resolution_budget_exceeded", category="rule_denial")
        return await _completed_result(ctx, proposal.ref, await execute_resolution(ctx, proposal, admission))
    if proposal.origin == "creative":
        from app.tools.resolution.creative import validate_creative_proposal

        admission = await validate_creative_proposal(ctx, proposal)
        if admission.route != "ordinary":
            raise ToolError("творческое решение недопустимо", code=admission.reason_code, category="rule_denial")
        if max(1, len(proposal.operations)) > ctx.remaining_resolution_calls:
            raise ToolError("недостаточно бюджета вызовов", code="resolution_budget_exceeded", category="rule_denial")
        closed_before = set(ctx.closed)
        result = await execute_resolution(ctx, proposal, admission)
        if result.execution in {"applied", "repeated"}:
            ctx.closed = closed_before
            await _completed_result(ctx, proposal.ref, result)
        await record_attempt(ctx, proposal.ref, "creative.neutral_npc", result)
        return result.model_dump()
    grant = next(
        (
            g
            for g in await eligible_adjudications(ctx)
            if g["attempt_id"] == proposal.attempt_id
            and action_key(proposal.ref) == action_key(type(proposal.ref).model_validate(g["ref"]))
        ),
        None,
    )
    if proposal.origin != "fallback" or grant is None:
        raise ToolError("нет допуска к внебоевому решению", code="adjudication_not_admitted", category="rule_denial")
    capability = CAPABILITIES[grant["capability_id"]]
    if any(op.kind not in capability.operations for op in proposal.operations):
        raise ToolError("последствие недоступно", code="operation_not_admitted", category="rule_denial")
    if max(1, len(proposal.operations)) > ctx.remaining_resolution_calls:
        raise ToolError("недостаточно бюджета вызовов", code="resolution_budget_exceeded", category="rule_denial")
    closed_before = set(ctx.closed)
    result = await execute_resolution(ctx, proposal, Admission("fallback", "server_attempt"))
    if result.execution in {"applied", "repeated"}:
        ctx.closed = closed_before
        await _completed_result(ctx, proposal.ref, result)
    # Record even a failed group; its unknown/denied result revokes the old grant.
    await record_attempt(ctx, proposal.ref, grant["capability_id"], result)
    return result.model_dump()
