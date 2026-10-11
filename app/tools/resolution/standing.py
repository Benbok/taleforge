"""Existing standing responses as atomic, durable world actions."""

from app.core.resolution.contracts import Admission
from app.core.resolution.policy import admit
from app.tools.registry import ToolContext, ToolError
from app.tools.resolution.capabilities import CAPABILITIES
from app.tools.resolution.operations import ResolutionProposal
from app.tools.resolution.requests import bind_world_action, load_action_context


def standing_resolution(ctx: ToolContext, response_id: str, operations: list, reason: str) -> ResolutionProposal:
    responses = ((ctx.world.scene.state or {}).get("standing") or {}).get("responses") or []
    response = next((r for r in responses if r["id"] == response_id and r["status"] == "ready"), None)
    if response is None:
        raise ToolError("ответ ещё не готов", code="invalid_response", category="rule_denial")
    actors = [
        actor
        for actor in response.get("target_ids") or ctx.world.characters
        if actor in ctx.world.characters and (not ctx.world.crew or actor in ctx.world.crew)
    ]
    if not actors:
        raise ToolError("нет участника этой группы", code="invalid_response_actor", category="rule_denial")
    return ResolutionProposal(
        ref=bind_world_action(ctx.campaign.id, response_id, actors[0]),
        origin="normal",
        outcome="success",
        reason=reason,
        operations=[*operations, {"kind": "response", "args": {"response_id": response_id, "how": reason}}],
    )


async def validate_standing_proposal(ctx: ToolContext, proposal: ResolutionProposal) -> Admission:
    if proposal.origin != "normal" or proposal.ref.source_kind != "standing_response":
        return Admission("deny", "invalid_response_source")
    capability = CAPABILITIES["standing.response"]
    context = await load_action_context(ctx, proposal.ref)
    admission = admit(context, capability, None)
    if admission.route != "ordinary":
        return admission
    operations = proposal.operations
    if (
        len(operations) < 2
        or operations[-1].kind != "response"
        or (operations[-1].args.response_id != proposal.ref.source_id)
        or any(op.kind == "response" for op in operations[:-1])
    ):
        return Admission("deny", "response_requires_prior_effect")
    if any(op.kind not in capability.operations for op in operations):
        return Admission("deny", "operation_not_admitted")
    return admission
