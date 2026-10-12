"""Atomic consequence groups; outer turn still owns commit and publication."""

import hashlib

from app.core.resolution.contracts import Admission, FailureInfo, ResolutionResult, normalize_result
from app.core.resolution.policy import admit
from app.db.models import Event
from app.tools.operation_group import CompiledCall, run_operation_group
from app.tools.registry import ToolContext, ToolError
from app.tools.resolution.capabilities import CAPABILITIES
from app.tools.resolution.context import refresh_world
from app.tools.resolution.operations import OPERATION_TOOLS, ResolutionProposal
from app.tools.resolution.requests import (
    action_key,
    deed_key,
    load_action_context,
    lock_resolution_source,
    record_operations,
    resolution_receipt,
)


def _scope_failure(ctx: ToolContext, proposal: ResolutionProposal, operation) -> str | None:
    args = operation.args.model_dump()
    affected = [args.get(field) for field in ("character_id", "actor_id", "target_id", "entity_id")]
    affected.extend(args.get("character_ids") or [])
    source_place = ctx.world.place_of(ctx.world.characters[proposal.ref.actor_id])
    for actor in (actor for actor in affected if actor):
        if ctx.world.in_fight(actor):
            return "combat_consequence_denied"
        if actor in ctx.world.characters and (
            ctx.world.place_of(ctx.world.characters[actor]) != source_place
            or (ctx.world.crew and actor not in ctx.world.crew)
        ):
            return "different_group_consequence_denied"
        if (
            actor in ctx.world.entities
            and operation.kind in {"hazard", "effect", "reposition", "entity_update"}
            and (ctx.world.entities[actor].kind == "creature" and ctx.world.actor_place(actor) != source_place)
        ):
            return "nonlocal_consequence_denied"
    return None


async def execute_resolution(ctx: ToolContext, proposal: ResolutionProposal, admission: Admission) -> ResolutionResult:
    if admission.route not in {"ordinary", "fallback"}:
        return ResolutionResult(execution="denied")
    await lock_resolution_source(ctx, proposal.ref)
    await refresh_world(ctx)
    receipt = await resolution_receipt(ctx, proposal.ref)
    if receipt is not None:
        return ResolutionResult.model_validate(receipt.payload["resolution"]).model_copy(
            update={"execution": "repeated"}
        )
    context = await load_action_context(ctx, proposal.ref)
    if proposal.ref.source_kind == "standing_response":
        from app.tools.resolution.standing import validate_standing_proposal

        checked = await validate_standing_proposal(ctx, proposal)
        capability = CAPABILITIES["standing.response"]
    elif proposal.origin == "creative":
        from app.tools.resolution.creative import validate_creative_proposal

        checked = await validate_creative_proposal(ctx, proposal)
        capability = CAPABILITIES["creative.neutral_npc"]
    else:
        capability = CAPABILITIES["noncombat.interaction"]
        checked = admit(context, capability, None)
    if checked.route != "ordinary" or any(op.kind not in capability.operations for op in proposal.operations):
        return ResolutionResult(
            execution="denied",
            failure=FailureInfo(
                code=checked.reason_code,
                category="rule_denial",
                rolled_back=False,
                attempt_id=proposal.attempt_id or "",
            ),
        )
    for operation in proposal.operations:
        scope_failure = _scope_failure(ctx, proposal, operation)
        if scope_failure:
            return ResolutionResult(
                execution="denied",
                failure=FailureInfo(
                    code=scope_failure,
                    category="rule_denial",
                    rolled_back=False,
                    attempt_id=proposal.attempt_id or "",
                ),
            )

    calls = []
    for index, operation in enumerate(proposal.operations):
        name, _ = OPERATION_TOOLS[operation.kind]
        args = operation.args.model_dump()
        if operation.kind == "enter_room" and not args.get("character_ids"):
            args = {**args, "character_ids": [proposal.ref.actor_id]}
        key = (
            deed_key(proposal.ref, args["subject_id"])
            if operation.kind == "deed"
            else (f"{action_key(proposal.ref)[:48]}:{index}")
        )
        is_hidden = False
        if operation.kind in {"fact", "story_hook"}:
            audience = ctx.world.crew or set(ctx.world.characters)
            if not audience.issubset(set(args.get("character_ids") or [])):
                is_hidden = True
        calls.append(
            CompiledCall(
                tool=name,
                args=args,
                call_key=key,
                hidden=is_hidden,
                metadata={
                    "op_index": index,
                    "request_key": action_key(proposal.ref),
                    "resolution_origin": proposal.origin,
                },
            )
        )

    def validate_step(c_ctx: ToolContext, call: CompiledCall, bindings: dict) -> None:
        op = proposal.operations[call.metadata["op_index"]]
        scope_failure = _scope_failure(c_ctx, proposal, op)
        if scope_failure:
            raise ToolError("последствие вне допуска", code=scope_failure, category="rule_denial")

    def annotate_event(event: Event, call: CompiledCall) -> None:
        event.payload = {
            **event.payload,
            "request_ref": proposal.ref.model_dump(),
            "resolution_origin": proposal.origin,
        }
        if ctx.world.in_fight(proposal.ref.actor_id):
            raise ToolError("небоевое решение вступило в бой", code="combat_started", category="rule_denial")

    group_res = await run_operation_group(
        ctx,
        tuple(calls),
        validate_step=validate_step,
        annotate_event=annotate_event,
    )

    if not group_res.ok:
        await record_operations(ctx, list(group_res.diagnostics))
        if group_res.raw_error:
            return normalize_result(group_res.raw_error, attempt_id=proposal.attempt_id or "")
        if isinstance(group_res.error, ToolError):
            return ResolutionResult(
                execution="denied",
                failure=FailureInfo(
                    code=group_res.error.code,
                    category=group_res.error.category,
                    rolled_back=True,
                    attempt_id=proposal.attempt_id or "",
                ),
            )
        raise group_res.error

    if ctx.world.in_fight(proposal.ref.actor_id):
        await record_operations(ctx, list(group_res.diagnostics))
        return ResolutionResult(
            execution="denied",
            failure=FailureInfo(
                code="combat_started",
                category="rule_denial",
                rolled_back=True,
                attempt_id=proposal.attempt_id or "",
            ),
        )

    result = ResolutionResult(
        execution="applied",
        game_outcome=proposal.outcome,
        event_ids=list(dict.fromkeys(group_res.event_ids)),
        completed_parts=[proposal.ref.part],
    )
    orig_call_key, orig_first_event = ctx.call_key, ctx._first_event
    ctx.call_key, ctx._first_event = action_key(proposal.ref), None
    await ctx.record(
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
    ctx.call_key, ctx._first_event = orig_call_key, orig_first_event
    await record_operations(ctx, list(group_res.diagnostics))
    return result
