"""Только фактические результаты переходов, без интерпретации текста LLM.

История вызовов сохраняет последовательность: более поздний успешный переход
исправляет предыдущий отказ. Не копируем секретные аргументы и ошибки в
публичную фазу повествования.
"""

import re

from app.core.resolution.contracts import ActionRef, ResolutionResult
from app.tools.resolution.requests import action_key

TRANSITIONS = frozenset({"move", "enter_room"})


def cancelled_actions(ctx) -> list[dict]:
    """Explicit and automatically recorded cancellations share one contract."""
    out = []
    for event in ctx.events:
        if event.tool != "cancel_action" or event.hidden:
            continue
        hero = ctx.world.characters.get(event.target_id)
        result = event.payload.get("result") or {}
        out.append(
            {
                "actor_id": event.target_id,
                "character": hero.name if hero else "Герой",
                "execution": "not_applied",
                "reason": event.payload.get("reason") or result.get("cancelled") or "Действие не выполнено.",
            }
        )
    return out


def acted(ctx, actor_id: str | None) -> bool:
    """У героя в этом ходе есть применённые публичные результаты. Сама отмена и бросок проверки — не результат:
    успешный поиск без находки не должен оставлять прозу о выдуманной находке."""
    return bool(actor_id) and any(
        e.actor_id == actor_id and not e.hidden and e.tool not in ("cancel_action", "roll_check") for e in ctx.events
    )


def public_factual_fallback(ctx, attempts=None, *, notice="", excluded_names=()) -> str:
    """Render committed public outcomes without copying errors or arbitrary prose.

    Event result fields are allowlisted by operation. Hidden events, plot data,
    internal receipts, IDs, reasons and book text never enter this fallback.
    """
    from app.agents import textcalls
    from app.tools import plot
    from app.tools.audio import AUDIO_TOOLS

    def words(value, default="Герой"):
        if not isinstance(value, str):
            return default
        value = re.sub(r"\[\[[^|\]]+\|([^\]]+)\]\]", r"\1", value)
        value = textcalls.clean(value)
        value = re.sub(r"\b(?:ch|en|inv|ra|op|t)_[A-Za-z0-9_]+\b", "", value)
        if any(name.casefold() in value.casefold() for name in excluded_names):
            return default
        return " ".join(value.split()) or default

    lines = [notice] if notice else []
    crew = getattr(ctx.world, "crew", None) or set(ctx.world.characters)
    viewers = getattr(ctx, "narration_viewer_ids", None)
    if viewers is None:
        viewers = crew
    learned_by = {}
    for event in ctx.events:
        if event.tool == "learn_fact" and not event.hidden:
            fact = (event.payload or {}).get("fact") or ((event.payload or {}).get("result") or {}).get("fact")
            if isinstance(fact, str):
                learned_by.setdefault(fact, set()).add(event.actor_id)
    for event in ctx.events:
        if event.hidden or event.tool in AUDIO_TOOLS or event.tool in plot.PLOT_TOOLS:
            continue
        if event.tool in {"resolve_action", "threat_clock", "cancel_action"}:
            continue
        payload = event.payload or {}
        result = payload.get("result", payload)
        if not isinstance(result, dict):
            result = {}
        who = words(result.get("character") or result.get("who") or result.get("attacker"))
        if event.tool in {"give_item", "keep_found_item", "pick_up_item"}:
            line = f"{who} получает предмет «{words(result.get('item'), 'предмет')}»."
        elif event.tool == "take_item":
            line = f"{who}: предмет «{words(result.get('item'), 'предмет')}» изъят из инвентаря."
        elif event.tool in {"pass_item", "give_item_to_npc", "transfer_item"}:
            line = f"Передан предмет «{words(result.get('item'), 'предмет')}»."
        elif event.tool == "use_item":
            line = (
                f"{words(result.get('user'))} использует «{words(result.get('item'), 'предмет')}» "
                f"для {words(result.get('target'), 'цели')}."
            )
            if result.get("remaining_qty") is not None:
                line += f" В инвентаре осталось: {int(result['remaining_qty'])}."
        elif event.tool in {"drop_item", "place_item"}:
            line = f"Размещён предмет «{words(result.get('item') or result.get('name'), 'предмет')}»."
        elif event.tool in TRANSITIONS:
            destination = payload.get("location") or result.get("location") or result.get("to")
            line = f"Состоялся переход: {words(destination, 'новое место')}."
        elif event.tool == "roll_check":
            outcome = "успех" if result.get("success") else "неудача"
            line = f"{who}: результат проверки — {outcome}."
        elif event.tool == "resolve_attack":
            hit = "попадание" if result.get("hit") else "промах"
            damage = result.get("damage")
            line = f"{who}: {hit}."
            if isinstance(damage, (int, float)) and not isinstance(damage, bool):
                line += f" Нанесено урона: {damage}."
        elif event.tool == "cast_spell":
            line = f"{words(result.get('caster'))} творит «{words(result.get('spell'), 'заклинание')}»."
            if result.get("created_qty"):
                line += f" Создано ягод: {int(result['created_qty'])}; они находятся в инвентаре и действуют 24 часа."
        elif event.tool in {"apply_effect", "remove_effect"}:
            verb = "Наложен" if event.tool == "apply_effect" else "Снят"
            line = f"{verb} эффект «{words(result.get('effect'), 'эффект')}»."
        elif event.tool == "auto_success":
            line = f"{who}: действие выполнено."
        elif event.tool == "join_party":
            line = f"{words(result.get('entity'), 'NPC')} теперь идёт с {words(result.get('hero'), 'героем')}."
        elif event.tool == "leave_party":
            line = f"{words(result.get('entity'), 'NPC')} отстал от отряда."
        elif event.tool == "companion_break":
            line = f"{words(result.get('entity'), 'NPC')} больше не идёт с отрядом."
        elif event.tool == "set_scene_mode":
            line = "Начался бой." if result.get("mode") == "combat" else "Сцена перешла в свободный режим."
        elif event.tool in {"learn_fact", "discover_fact"}:
            if event.actor_id not in crew:
                continue
            fact = payload.get("fact") or result.get("fact")
            line = "Получены новые сведения."
            if isinstance(fact, str) and viewers <= learned_by.get(fact, set()):
                line = words(fact, line)
        elif event.tool == "reveal_knowledge":
            if event.actor_id not in crew:
                continue
            line = "Получены сведения о зарегистрированном объекте мира."
        elif event.tool == "reveal":
            line = "В сцене обнаружен ранее скрытый объект."
        else:
            line = "Подтверждённое изменение мира сохранено."
        lines.append(line)
    for cancelled in cancelled_actions(ctx):
        lines.append(f"{words(cancelled['character'])}: действие не выполнено.")
    if transition_outcome(attempts) == "failed":
        lines.append("Переход не состоялся.")
    if failed_attack(attempts):
        lines.append("Атака не состоялась: сервер отклонил действие.")
    return " ".join(dict.fromkeys(lines)) or "Подтверждённых изменений в этом ходе нет."


def transition_outcome(attempts: list[dict] | None) -> str | None:
    """Последний результат перехода этого хода: success, failed или None."""
    latest = None
    scoped = {}
    for entry in attempts or []:
        if entry.get("tool") in TRANSITIONS:
            latest = "success" if (entry.get("result") or {}).get("ok") else "failed"
            if entry.get("request_key"):
                scoped[entry["request_key"]] = latest
    if "failed" in scoped.values():
        return "failed"
    return latest


def public_attempts(attempts: list[dict] | None) -> str:
    """Показываем модели факт попыток, но не секретные параметры и ToolError."""
    rows = []
    for entry in attempts or []:
        name = entry.get("tool")
        if name == "adjudicate_action":
            result = (entry.get("result") or {}).get("result") or {}
            executed = result.get("execution") in {"applied", "repeated"}
            outcome = (
                {"success": "успех", "partial": "частичный исход", "failure": "игровая неудача"}.get(
                    result.get("game_outcome")
                )
                if executed
                else None
            )
            rows.append(
                f"- adjudicate_action: {'выполнен' if executed else 'не выполнен'}"
                + (f"; {outcome}" if outcome else "")
            )
            continue
        if name not in TRANSITIONS and name != "resolve_attack":
            continue
        outcome = "выполнен" if (entry.get("result") or {}).get("ok") else "не выполнен"
        rows.append(f"- {name}: {outcome}")
    return "\n".join(rows) or "попыток перехода или атаки нет"


def failed_attack(attempts: list[dict] | None) -> bool:
    """Атака считается несостоявшейся только если последняя её попытка отклонена."""
    latest = None
    for entry in attempts or []:
        if entry.get("tool") == "resolve_attack":
            latest = bool((entry.get("result") or {}).get("ok"))
    return latest is False


def failed_item_action(attempts: list[dict] | None) -> bool:
    """An unresolved inventory failure cannot be narrated as a successful transfer or use."""
    latest = {}
    for entry in attempts or []:
        tool = entry.get("tool")
        if tool not in {"give_item", "pass_item", "pick_up_item", "drop_item", "use_item"}:
            continue
        args = entry.get("args") or {}
        key = (
            tool,
            args.get("character_id"),
            args.get("inventory_id") or args.get("item_template_id") or args.get("entity_id"),
            args.get("to_entity_id") or args.get("to_character_id") or args.get("target_id"),
        )
        latest[key] = bool((entry.get("result") or {}).get("ok"))
    return any(not success for success in latest.values())


def resolved_action_outcomes(ctx) -> dict[str, ResolutionResult]:
    return {
        action_key(ActionRef.model_validate(event.payload["ref"])): ResolutionResult.model_validate(
            event.payload["resolution"]
        )
        for event in ctx.events
        if event.tool == "resolve_action"
    }


def public_resolution(ctx, result: ResolutionResult, viewer_ids: set[str]) -> dict:
    crew = ctx.world.crew or set(ctx.world.characters)
    if not crew.intersection(viewer_ids):
        return {}
    return {"execution": result.execution, "game_outcome": result.game_outcome}
