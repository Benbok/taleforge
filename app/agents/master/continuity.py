"""Проверки согласованности именованных участников повествования с реестром сцены."""

from __future__ import annotations

import re

# Явно пронумерованные персонажи («Скелет 1», «Страж 2») — экземпляры,
# а не общие слова об атмосфере или слухах.
NUMBERED_NAME = re.compile(r"(?<!\w)([А-ЯЁA-Z][а-яёa-z-]+\s+[1-9]\d*)(?!\w)")
NON_ACTORS = frozenset(
    {
        "комната",
        "глава",
        "акт",
        "сцена",
        "раунд",
        "ход",
        "день",
        "уровень",
        "этаж",
        "зал",
        "этап",
        "часть",
        "пункт",
        "шаг",
        "клетка",
    }
)


def _stem_matches(stem: str, target: str) -> bool:
    """Проверяет совпадение основы слова с зарегистрированным именем с учётом склонения."""
    if stem == target:
        return True
    # Падежные окончания существительных мужского рода (скелет -> скелета, скелету, скелетом, скелете, скелетов)
    if stem.startswith(target) and len(stem) - len(target) <= 3:
        return True
    if target.startswith(stem) and len(target) - len(stem) <= 2:
        return True
    # Падежные окончания женского и среднего рода (крыса -> крысу, крысой; чудище -> чудища)
    if len(stem) >= 3 and len(target) >= 3:
        if stem[:-1] == target[:-1]:
            return True
        if len(stem) >= 4 and stem[:-2] == target[:-1]:
            return True
        if len(target) >= 4 and target[:-2] == stem[:-1]:
            return True
        if len(stem) >= 4 and len(target) >= 4 and stem[:-2] == target[:-2]:
            return True
    return False


def unregistered_named_actors(text: str, world) -> list[str]:
    """Имена новых пронумерованных участников, отсутствующих в текущей сцене.

    Не выводим сущности из текста и не раскрываем существ из других комнат.
    """
    active = {e.name.casefold() for e in world.in_scene_entities()}
    active.update(ch.name.casefold() for ch in world.characters.values())
    places = {e.name.casefold() for e in world.entities.values() if e.kind == "location"}
    known = active | places

    known_numbered: list[tuple[str, str]] = []
    for k in known:
        parts = k.rsplit(" ", 1)
        if len(parts) == 2 and parts[1].isdigit():
            known_numbered.append((parts[0], parts[1]))

    found = set()
    for match in NUMBERED_NAME.finditer(text):
        name = match.group(1)
        stem, num = name.rsplit(" ", 1)
        stem_cf = stem.casefold()
        if stem_cf in NON_ACTORS:
            continue
        if name.casefold() in known:
            continue
        if any(num == k_num and _stem_matches(stem_cf, k_stem) for k_stem, k_num in known_numbered):
            continue
        found.add(name)
    return sorted(found)
