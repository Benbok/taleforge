"""Native noncombat fallback, authorized exclusively by server attempts."""

from app.core.resolution.contracts import Admission, Contract
from app.tools.registry import ToolContext, ToolError, tool
from app.tools.resolution.capabilities import CAPABILITIES
from app.tools.resolution.executor import execute_resolution
from app.tools.resolution.operations import ResolutionProposal
from app.tools.resolution.requests import action_key, eligible_adjudications, mark_resolved, record_attempt


class AdjudicationArgs(Contract):
    proposal: ResolutionProposal


@tool(
    "adjudicate_action",
    "Внебоевое решение: только по допуску сервера и указанной заявке; бой запрещён.",
    AdjudicationArgs,
    mutating=False,
    closes=False,
)
async def adjudicate_action(ctx: ToolContext, args: AdjudicationArgs) -> dict:
    proposal = args.proposal
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
        mark_resolved(ctx, proposal.ref)
    # Record even a failed group; its unknown/denied result revokes the old grant.
    await record_attempt(ctx, proposal.ref, grant["capability_id"], result)
    return result.model_dump()
