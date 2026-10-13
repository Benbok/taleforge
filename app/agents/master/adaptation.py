"""Master agent narrative adaptation prompt and effect integration (Task 10)."""

from __future__ import annotations

import json

from app.core.narrative.contracts import PublicEffect
from app.core.narrative.threads import is_thread_visible_to_audience
from app.db.narrative import ensure_state
from app.tools.narrative.executor import find_receipt
from app.tools.narrative.sources import bind_scene_sources
from app.tools.registry import ToolContext

# Минимальные образцы аргументов adapt_story по видам операций. Модель видит точный формат, сервер его же и
# проверяет; тест сверяет каждый образец с контрактами, чтобы подсказка не разошлась с кодом.
OPERATION_EXAMPLES: dict[str, dict] = {
    "develop_actor_role": {
        "kind": "develop_actor_role",
        "entity_id": "<id NPC>",
        "new_role": "проводник отряда",
        "new_motivation": "тайно ищет брата",
    },
    "add_campaign_fact": {
        "kind": "add_campaign_fact",
        "fact": {
            "ref": {
                "campaign_id": "{campaign_id}",
                "namespace": "campaign",
                "subject_id": "<id>",
                "key": "relationship",
                "snapshot_ref": {
                    "kind": "event",
                    "source_id": "current",
                    "typed_address": "campaign:<id>:relationship",
                },
            },
            "kind": "truth",
            "temporal_semantics": "current_state",
            "freedom": "draft",
            "value": "староста должен отряду услугу",
            "audience": ["party"],
        },
    },
    "upsert_thread": {
        "kind": "upsert_thread",
        "thread": {"id": "th-<кратко>", "status": "offered", "audience": ["party"], "subject_refs": ["<id>"]},
    },
    "transition_thread": {"kind": "transition_thread", "thread_id": "th-<кратко>", "target_status": "dormant"},
    "change_front_intent": {
        "kind": "change_front_intent",
        "front_ref": {"campaign_id": "{campaign_id}", "source_kind": "antagonist", "source_id": "<id антагониста>"},
        "new_intent": "выжидает и шлёт разведчиков",
    },
    "revise_future_situation": {
        "kind": "revise_future_situation",
        "patch": {
            "edits": [
                {
                    "kind": "update_open_node",
                    "act_id": "<id акта>",
                    "node_id": "<id открытого узла>",
                    "fields": {"title": "…", "summary": "…"},
                }
            ]
        },
    },
}
GROUND_EXAMPLE = {
    "kind": "divergence",
    "evidence_refs": [{"kind": "message", "source_id": "current"}],
    "confidence": "explicit",
}


def operation_examples(campaign_id: str) -> str:
    return "\n".join(
        f"  {kind}: " + json.dumps(example, ensure_ascii=False).replace("{campaign_id}", campaign_id)
        for kind, example in OPERATION_EXAMPLES.items()
    )


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
        "- Не описывай факты и связи в тексте без предварительного вызова adapt_story.\n"
        f"Формат: grounds [{json.dumps(GROUND_EXAMPLE, ensure_ascii=False)}]; operations — список объектов:\n"
        + operation_examples(ctx.campaign.id)
        + "\nЗначения в угловых скобках замени настоящими id из сцены и get_plot; future-правки — slot 2."
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
