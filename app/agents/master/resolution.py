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
        if admit(context, CAPABILITIES["creative.neutral_npc"], None).route == "ordinary":
            creative.append(ref.model_dump())
    if not eligible and not creative:
        return ""
    return (
        "\nДопуски к внебоевому решению (не переигрывают провал броска):\n"
        + json.dumps(eligible, ensure_ascii=False)
        + "\nСсылки для творческого предложения (origin=creative, не аварийный допуск):\n"
        + json.dumps(creative, ensure_ascii=False)
        + "\nСам выбери соразмерный исход и последствия через adjudicate_action. "
        "Не описывай изменение мира до успешного инструмента. Боевые правила обходить нельзя."
    )


async def capture_attempt(ctx: ToolContext, actor_id: str | None, raw: dict) -> str | None:
    refs = [ref for ref in ctx.required_actions if ref.actor_id == actor_id]
    # An ambiguous multi-part request must not borrow another part's failure.
    if len(refs) != 1:
        return
    result = normalize_result(raw, attempt_id="")
    await record_attempt(ctx, refs[0], "noncombat.interaction", result)
    if result.execution in {"applied", "repeated"}:
        mark_resolved(ctx, refs[0])
    return action_key(refs[0])
