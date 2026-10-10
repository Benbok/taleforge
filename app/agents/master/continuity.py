"""Проверки согласованности именованных участников повествования с реестром сцены."""

from __future__ import annotations

import re

# Явно пронумерованные персонажи («Скелет 1», «Страж 2») — экземпляры,
# а не общие слова об атмосфере или слухах.
NUMBERED_NAME = re.compile(r"(?<!\w)([А-ЯЁA-Z][а-яёa-z-]+\s+[1-9]\d*)(?!\w)")
NON_ACTORS = frozenset({
    "комната", "глава", "акт", "сцена", "раунд", "ход", "день", "уровень",
    "этаж", "зал", "этап", "часть", "пункт", "шаг", "клетка",
})


def unregistered_named_actors(text: str, world) -> list[str]:
    """Имена новых пронумерованных участников, отсутствующих в текущей сцене.

    Не выводим сущности из текста и не раскрываем существ из других комнат.
    """
    active = {e.name.casefold() for e in world.in_scene_entities()}
    active.update(ch.name.casefold() for ch in world.characters.values())
    places = {e.name.casefold() for e in world.entities.values() if e.kind == "location"}
    found = set()
    for match in NUMBERED_NAME.finditer(text):
        name = match.group(1)
        stem = name.rsplit(" ", 1)[0].casefold()
        if stem not in NON_ACTORS and name.casefold() not in active and name.casefold() not in places:
            found.add(name)
    return sorted(found)
