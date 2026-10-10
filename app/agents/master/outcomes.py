"""Итоги попыток инструментов: отказ — не событие и не разрешение для зависимых действий."""

from __future__ import annotations

TRANSITION_TOOLS = frozenset({"enter_room", "move"})


def unresolved_transition(attempts: list[dict]) -> bool:
    """Последняя попытка перемещения отклонена и не была исправлена успешной."""
    pending = False
    for attempt in attempts:
        if attempt.get("tool") in TRANSITION_TOOLS:
            pending = not (attempt.get("result") or {}).get("ok", False)
    return pending


def attempt_note(attempts: list[dict]) -> str:
    """Мастеру — статус попытки. Не переносим аргументы/секреты в текст игрокам."""
    notes = []
    for attempt in attempts:
        if attempt.get("tool") not in TRANSITION_TOOLS:
            continue
        res = attempt.get("result") or {}
        if res.get("ok"):
            notes.append(f"- {attempt['tool']}: успешно; действует фактическое место после вызова.")
        elif res.get("skipped"):
            notes.append(f"- {attempt['tool']}: не исполнялся из-за предыдущей ошибки перехода.")
        else:
            notes.append(f"- {attempt['tool']}: отказано; переход НЕ произошёл.")
    return "\n".join(notes)


def safe_stay_message(ctx, hero_ids: set[str]) -> str:
    """Факт для игроков из текущего состояния их группы, без причин/тайн отказа."""
    places = set()
    for hid in hero_ids:
        hero = ctx.world.characters.get(hid)
        if hero is None:
            continue
        place_id = ctx.world.place_of(hero)
        if place_id:
            loc = ctx.world.entities.get(place_id)
            if loc is not None:
                places.add(loc.name)
    if len(places) == 1:
        return f"Переход не состоялся. Герои остались в локации «{next(iter(places))}»."
    return "Переход не состоялся. Герои остались в своих прежних местах."
