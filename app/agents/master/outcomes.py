"""Только фактические результаты переходов, без интерпретации текста LLM.

История вызовов сохраняет последовательность: более поздний успешный переход
исправляет предыдущий отказ. Не копируем секретные аргументы и ошибки в
публичную фазу повествования.
"""

TRANSITIONS = frozenset({"move", "enter_room"})


def transition_outcome(attempts: list[dict] | None) -> str | None:
    """Последний результат перехода этого хода: success, failed или None."""
    latest = None
    for entry in attempts or []:
        if entry.get("tool") in TRANSITIONS:
            latest = "success" if (entry.get("result") or {}).get("ok") else "failed"
    return latest


def public_attempts(attempts: list[dict] | None) -> str:
    """Показываем модели факт попыток, но не секретные параметры и ToolError."""
    rows = []
    for entry in attempts or []:
        name = entry.get("tool")
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
