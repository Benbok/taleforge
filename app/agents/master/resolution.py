"""A small decision-phase adapter, not another turn coordinator."""

import json

from app.core.resolution.contracts import normalize_result
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


async def capture_attempt(ctx: ToolContext, actor_id: str | None, raw: dict) -> str | None:
    refs = [ref for ref in ctx.required_actions if ref.actor_id == actor_id]
    # An ambiguous multi-part request must not borrow another part's failure.
    if len(refs) != 1:
        if refs:
            ctx.closed.discard(actor_id)
            from app.db.models import MasterTurn

            turn = await ctx.session.get(MasterTurn, ctx.turn_id)
            entry = {"actor_id": actor_id, "result": normalize_result(raw, attempt_id="").model_dump()}
            attempts = [*(turn.trace or {}).get("resolution_unbound_attempts", []), entry]
            turn.trace = {**(turn.trace or {}), "resolution_unbound_attempts": attempts}
            ctx.turn_diagnostics["resolution_unbound_attempts"] = attempts
        return
    result = normalize_result(raw, attempt_id="")
    await record_attempt(ctx, refs[0], "noncombat.interaction", result)
    if result.execution in {"applied", "repeated"}:
        mark_resolved(ctx, refs[0])
    return action_key(refs[0])


async def permit_repair(ctx: ToolContext, actor_id: str | None) -> bool:
    from app.db.models import MasterTurn
    from app.tools.resolution.requests import latest_attempt

    refs = [ref for ref in ctx.required_actions if ref.actor_id == actor_id]
    if len(refs) != 1:
        return True
    previous = await latest_attempt(ctx, refs[0])
    if not previous or (previous["result"].get("failure") or {}).get("category") != "invalid_arguments":
        return True
    turn = await ctx.session.get(MasterTurn, ctx.turn_id)
    repaired = list((turn.trace or {}).get("resolution_repairs", []))
    key = action_key(refs[0])
    if key in repaired:
        return False
    turn.trace = {**(turn.trace or {}), "resolution_repairs": [*repaired, key]}
    return True
