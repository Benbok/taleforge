"""Grounded creative guidance inside the existing decision/narration pipeline."""

import json
from dataclasses import asdict

from app.core import adventure
from app.core.resolution.contracts import ActionRef
from app.tools.registry import ToolContext
from app.tools.resolution.creative import creative_opportunities as creative_opportunities
from app.tools.resolution.creative import validate_creative_proposal as validate_creative_proposal


def creative_context(ctx: ToolContext, ref: ActionRef | None = None) -> dict:
    combat = ctx.world.in_fight(ref.actor_id if ref else None)
    return {
        "schema_version": 1,
        "mode": "combat" if combat else "noncombat",
        "module": adventure.is_module(ctx.campaign),
        "allowed": ["presentation"] if combat else ["supported_checks", "interpretation", "presentation"],
        "persona": "existing_system_persona",
        "opportunities": [] if combat else [asdict(op) for op in creative_opportunities(ctx)],
        "results": [
            {"tool": event.tool, "success": event.payload["result"].get("success")}
            for event in ctx.events
            if not event.hidden and isinstance(event.payload.get("result"), dict)
        ],
    }


def creative_note(context: dict) -> str:
    if context["mode"] == "combat":
        return "Творчество в бою — только подача: не меняй броски, дистанции, урон и экономику действий."
    return (
        "Принимай нестандартные идеи: выбери подходящую поддерживаемую проверку, а не требуй название кнопки. "
        "Не переигрывай результат. Провал может открыть другую возможность, но исходная цель остаётся невыполненной. "
        "Обычный успех не требует обязательного осложнения; не вводи цену задним числом. "
        "Не принимай решения за героя. Значимые последствия сохраняй инструментами, а не художественным текстом. "
        "Сохраняй выбранную персону и темп; эмоции не заменяют канон и факты. "
        + ("Книга модуля обязательна: пустая каноническая комната остаётся пустой. " if context["module"] else "")
        + "\nПроверенные возможности (reuse сначала, new_neutral только в этом месте): "
        + json.dumps(context["opportunities"], ensure_ascii=False)
    )
