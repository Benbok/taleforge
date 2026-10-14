"""A small decision-phase adapter, not another turn coordinator."""

import json

from app.core.resolution.contracts import ActionRef, ToolActionBinding, normalize_result
from app.tools.registry import ToolContext
from app.tools.resolution.requests import action_key, eligible_adjudications, mark_resolved, record_attempt


async def resolution_prompt(ctx: ToolContext) -> str:
    from app.core.resolution.policy import admit
    from app.tools.resolution.capabilities import CAPABILITIES
    from app.tools.resolution.requests import load_action_context

    eligible = await eligible_adjudications(ctx)
    creative = []
    for ref in ctx.required_actions:
        context = await load_action_context(ctx, ref)
        from app.tools.resolution.requests import latest_attempt

        latest = await latest_attempt(ctx, ref)
        if admit(context, CAPABILITIES["creative.neutral_npc"], None).route == "ordinary" and not (
            latest and latest["result"]["execution"] in {"denied", "failed"}
        ):
            creative.append(ref.model_dump())
    from app.tools.registry import ToolError
    from app.tools.resolution.standing import standing_resolution

    standing = []
    for response in ((ctx.world.scene.state or {}).get("standing") or {}).get("responses") or []:
        if response.get("status") == "ready":
            try:
                standing.append(standing_resolution(ctx, response["id"], [], "ответ мира").ref.model_dump())
            except ToolError:
                pass
    if not eligible and not creative and not standing:
        return ""
    return (
        "\nДопуски к внебоевому решению (не переигрывают провал броска):\n"
        + json.dumps(eligible, ensure_ascii=False)
        + "\nСсылки для творческого предложения (origin=creative, не аварийный допуск):\n"
        + json.dumps(creative, ensure_ascii=False)
        + "\nГотовые ответы мира (origin=normal, эффект сначала, response последним в одной группе):\n"
        + json.dumps(standing, ensure_ascii=False)
        + "\nСам выбери соразмерный исход и последствия через adjudicate_action. "
        "Не описывай изменение мира до успешного инструмента. Боевые правила обходить нельзя."
    )


async def capture_attempt(ctx: ToolContext, binding: ToolActionBinding | str | None, raw: dict) -> str | None:
    if not isinstance(binding, ToolActionBinding):
        actor_id = binding
        refs = [ref for ref in ctx.required_actions if ref.actor_id == actor_id]
        if len(refs) != 1:
            if refs:
                ctx.closed.discard(actor_id)
                from app.db.models import MasterTurn

                turn = await ctx.session.get(MasterTurn, ctx.turn_id) if ctx.turn_id else None
                if turn:
                    entry = {"actor_id": actor_id, "result": normalize_result(raw, attempt_id="").model_dump()}
                    attempts = [*(turn.trace or {}).get("resolution_unbound_attempts", []), entry]
                    turn.trace = {**(turn.trace or {}), "resolution_unbound_attempts": attempts}
                    ctx.turn_diagnostics["resolution_unbound_attempts"] = attempts
            return None
        binding = ToolActionBinding(ref=refs[0], role="finish")

    ref = binding.ref
    result = normalize_result(raw, attempt_id="")
    await record_attempt(ctx, ref, "noncombat.interaction", result)
    if binding.role == "finish" and result.execution in {"applied", "repeated"}:
        mark_resolved(ctx, ref)
    return action_key(ref)


async def permit_repair(ctx: ToolContext, ref: ActionRef | str | None) -> bool:
    from app.db.models import MasterTurn
    from app.tools.resolution.requests import latest_attempt

    if isinstance(ref, str):
        refs = [r for r in ctx.required_actions if r.actor_id == ref]
        if len(refs) != 1:
            return True
        ref = refs[0]
    if ref is None:
        return True

    previous = await latest_attempt(ctx, ref)
    if not previous or (previous["result"].get("failure") or {}).get("category") != "invalid_arguments":
        return True
    turn = await ctx.session.get(MasterTurn, ctx.turn_id) if ctx.turn_id else None
    trace = dict(turn.trace or {}) if turn is not None else ctx.turn_diagnostics
    repaired = list(trace.get("resolution_repairs", []))
    key = action_key(ref)
    if key in repaired:
        return False
    trace["resolution_repairs"] = [*repaired, key]
    if turn is not None:
        turn.trace = trace
    return True
