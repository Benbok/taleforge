"""Только фактические результаты переходов, без интерпретации текста LLM.

История вызовов сохраняет последовательность: более поздний успешный переход
исправляет предыдущий отказ. Не копируем секретные аргументы и ошибки в
публичную фазу повествования.
"""

from app.core.resolution.contracts import ActionRef, ResolutionResult
from app.tools.resolution.requests import action_key

TRANSITIONS = frozenset({"move", "enter_room"})


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
