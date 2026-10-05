"""Общее для инструментов мастера: подсказки схем, движок правил и помощники."""

from __future__ import annotations

import copy
from typing import Annotated, Literal

from pydantic import Field

from app.core.world import PLAYABLE, Actor
from app.db.models import Character
from app.rules.dnd5e.engine import Dnd5eEngine
from app.tools.registry import ToolContext, ToolError

engine = Dnd5eEngine()
Zone = Literal["melee", "near", "far"]
Bearing = Literal["n", "ne", "e", "se", "s", "sw", "w", "nw"]
BEARING_HINT = "в какой стороне от отряда на схеме места: n — север (вверх), e — восток и т. д."
PLACE_HINT = "место, где стоят герои; нужно, только если отряд разделён (по умолчанию — место сцены)"
CELL_HINT = (
    "клетка 5×5 футов [столбец, строка]: в месте с эскизом — от его северо-западного угла, как в эскизе; без эскиза — "
    "от строя отряда (0, 0), восток и юг положительные. С клеткой зона и сторона выводятся сами"
)
Cell = Annotated[list[int], Field(min_length=2, max_length=2)]
Elevation = Literal["low", "ground", "high"]
ELEVATION_HINT = "высота: low — внизу (яма, трюм), ground — на земле, high — на возвышении (балкон, гребень)"
Cover = Literal["none", "half", "three_quarters", "total"]
COVER_HINT = "укрытие по SRD: half +2 к КД, three_quarters +5, total — цель нельзя атаковать напрямую"
Edge = Literal["none", "advantage", "disadvantage"]
EDGE_HINT = (
    "преимущество или помеха по обстоятельствам (SRD, решение мастера): advantage — замысел логичен и хорошо "
    "подготовлен, выгодная позиция, помощь союзника; disadvantage — спешка, темнота, неудобная поза, действие на "
    "грани возможного. Эффекты сервер учтёт сам, здесь только обстоятельства"
)
HIDDEN_SKILLS_DEFAULT = ("perception", "insight", "stealth")
MAX_LEVEL_DEFAULT = 20
# Находка без шаблона в пакете (камень, шляпа прохожего): вещь без механики, имя даёт мастер.
# Такого шаблона нет в каталоге намеренно: листу героя он ничего не прибавляет.
FOUND_ITEM = "item.found"
IMPROVISED_WEAPON = "item.improvised_weapon"  # SRD 5.1: импровизированное оружие, 1d4


# --- помощники ---


def snapshot(a: Actor) -> dict:
    if isinstance(a.obj, Character):
        return {"table": "characters", "id": a.id, "field": "resources", "before": copy.deepcopy(a.obj.resources)}
    return {"table": "entities", "id": a.id, "field": "state", "before": copy.deepcopy(a.obj.state)}


def _character(ctx: ToolContext, cid: str) -> Character:
    ch = ctx.world.characters.get(cid)
    if ch is None or ch.status not in PLAYABLE:
        raise ToolError(f"нет персонажа в игре {cid}")
    return ch


def _alive(a: Actor, role: str) -> None:
    if not a.alive:
        raise ToolError(f"{role} {a.name} мёртв: мёртвые не действуют и не могут быть целью атаки (осмотр — можно)")


def _hidden_skills(ctx: ToolContext) -> set[str]:
    rec = ctx.world.catalog.find("skill_map.hidden")
    if rec is not None and isinstance(rec.data.get("skills"), list):
        return set(rec.data["skills"])
    return set(HIDDEN_SKILLS_DEFAULT)
