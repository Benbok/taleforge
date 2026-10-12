"""Master agent narrative adaptation prompt and effect integration (Task 10)."""

from __future__ import annotations

from app.core.narrative.contracts import PublicEffect
from app.core.narrative.threads import is_thread_visible_to_audience
from app.db.narrative import ensure_state
from app.tools.narrative.executor import find_receipt
from app.tools.narrative.sources import bind_scene_sources
from app.tools.registry import ToolContext


async def adaptation_prompt(ctx: ToolContext) -> str:
    """Decision phase prompt for in-scene narrative adaptation."""
    state = await ensure_state(ctx.session, ctx.campaign.id)
    if state.mode != "adaptive":
        return ""

    if ctx.world.scene.mode == "combat":
        return ""

    slots = await bind_scene_sources(ctx)
    free_slots = []
    for s in slots:
        receipt = await find_receipt(ctx.session, s)
        if receipt is None:
            free_slots.append(s.stable_part)

    if not free_slots:
        return ""

    return (
        f"\nДоступна адаптация сюжета текущей сцены (adapt_story, свободные слоты: {free_slots}).\n"
        "Если реплики или действия игроков открыли неожиданный интерес, новую возможность или поворот — "
        "используй adapt_story со slot_ref из свободных слотов.\n"
        "Правила адаптации:\n"
        "- Провал броска НЕЛЬЗЯ отменять или компенсировать успехом; "
        "можно предложить альтернативную нить (upsert_thread со статусом offered).\n"
        '- Основание — реплика игрока этого хода: evidence_refs [{"kind": "message", "source_id": "current"}]; '
        "другие сообщения и события — только по их настоящему id.\n"
        "- Развитие роли существующего NPC: develop_actor_role.\n"
        "- Новый устойчивый факт: add_campaign_fact.\n"
        "- Новая цель или подозрение фракции: change_front_intent.\n"
        "- Не описывай факты и связи в тексте без предварительного вызова adapt_story."
    )


def public_adaptation_effects(ctx: ToolContext, audience: tuple[str, ...]) -> tuple[PublicEffect, ...]:
    """Extract confirmed public adaptation effects visible to the given audience."""
    effects: list[PublicEffect] = []
    for ev in ctx.events:
        if ev.tool != "adapt_story":
            continue
        adaptation = (ev.payload or {}).get("adaptation") or {}
        if adaptation.get("status") not in ("applied", "repeated"):
            continue

        raw_effects = adaptation.get("public_effects") or []
        for pe in raw_effects:
            pe_aud = tuple(pe.get("audience", ()))
            if is_thread_visible_to_audience(pe_aud, audience):
                effects.append(
                    PublicEffect(
                        kind=pe.get("kind", "narrative"),
                        description=pe.get("description", ""),
                        audience=pe_aud,
                    )
                )

    return tuple(effects)
