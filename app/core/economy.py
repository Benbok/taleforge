"""Ход героя в бою по SRD (решение Arty 2026-10-05: сервер считает): передвижение, одно действие, одно бонусное
действие и реакция до следующего хода.

Учёт живёт в ``scenes.state.spent[герой]`` и привязан к метке хода (``combat.turn_marker``): новый ход — чистый лист.
Считается только в ход самого героя: атака по возможности на чужом ходу — реакция, её считает ``combat.use_reaction``.

- Действие «Атака» даёт столько ударов, сколько у героя атак за действие (Дополнительная атака класса); пока удары
  остались, следующий удар действие не тратит.
- Заклинание тратит то, за что творится: действие, бонусное действие или реакцию. Сотворив заклинание бонусным
  действием, основным в тот же ход можно творить только заговор (и наоборот).
- Рывок прибавляет к передвижению ещё одну скорость, Отход снимает атаки по возможности до конца хода.
- Всплеск действий даёт ещё одно действие.
"""

from __future__ import annotations

import copy
from typing import Any

from app.tools.registry import ToolContext, ToolError

ACTIONS_RU = {
    "attack": "атака",
    "cast": "заклинание",
    "dash": "рывок",
    "disengage": "отход",
    "dodge": "уклонение",
    "help": "помощь",
    "hide": "скрытность",
    "ready": "подготовка",
    "search": "поиск",
    "use_object": "предмет",
    "other": "другое",
}


def _marker(world) -> str | None:
    from app.core.combat import turn_marker

    return turn_marker(world.scene)


def active(world, hero_id: str) -> bool:
    """Сейчас ход этого героя в бою: учёт действий идёт."""
    from app.core import combat

    sc = world.scene
    if sc.mode != "combat" or not sc.turn_order or hero_id not in world.characters:
        return False
    i = int((sc.state or {}).get("turn", 0)) % len(sc.turn_order)
    return sc.turn_order[i]["id"] == hero_id and combat.fights(sc, world.characters, world.entities, hero_id)


def ledger(world, hero_id: str) -> dict[str, Any]:
    """Что герой потратил за этот ход (пустой лист, если ход новый)."""
    mine = ((world.scene.state or {}).get("spent") or {}).get(hero_id) or {}
    if mine.get("turn") != _marker(world):
        return {"turn": _marker(world), "actions": 0, "extra": 0, "attacks_left": 0, "bonus": False, "dash": 0,
                "disengage": False, "spells": []}  # fmt: skip
    return dict(mine)


def _save(world, hero_id: str, led: dict) -> None:
    spent = dict((world.scene.state or {}).get("spent") or {})
    spent[hero_id] = led
    world.scene.state = {**(world.scene.state or {}), "spent": spent}


def attacks_per_action(world, hero_id: str) -> int:
    """Удары за действие «Атака»: 1 плюс Дополнительные атаки класса до уровня героя."""
    sheet = world.characters[hero_id].sheet or {}
    cls = world.catalog.find(sheet.get("class_id") or "", "class")
    if cls is None:
        return 1
    level = int(sheet.get("level") or 1)
    n = 0
    for row in cls.data.get("levels") or []:
        if isinstance(row, dict) and int(row.get("level", 99)) <= level:
            n += sum(1 for f in row.get("features") or [] if "extra_attack" in str(f))
    return 1 + n


def view(world, hero_id: str) -> dict[str, Any] | None:
    """Остаток хода героя для экрана и для таблицы мастера; None — не его ход в бою."""
    if not active(world, hero_id):
        return None
    led = ledger(world, hero_id)
    speed = int(world.actor(hero_id).speed or 0)
    moved = moved_ft(world, hero_id)
    return {
        "action": led["actions"] < 1 + led["extra"],
        "attacks_left": led["attacks_left"],
        "bonus": not led["bonus"],
        "move_left_ft": max(0, speed * (1 + led["dash"]) - moved),
        "disengage": led["disengage"],
    }


def moved_ft(world, hero_id: str) -> int:
    st = (world.scene.state or {}).get("moved") or {}
    mine = st.get(hero_id) or {}
    return int(mine.get("ft") or 0) if mine.get("turn") == _marker(world) else 0


def line(world, hero_id: str) -> str:
    """Строка для таблицы сцены: что у героя осталось в этот ход."""
    v = view(world, hero_id)
    if v is None:
        return ""
    parts = [
        "действие свободно" if v["action"] else "действие потрачено",
        f"ударов в действии атаки ещё {v['attacks_left']}" if v["attacks_left"] else None,
        "бонусное действие свободно" if v["bonus"] else "бонусное действие потрачено",
        f"шагов ещё {v['move_left_ft']} фт",
        "отход: атак по возможности нет" if v["disengage"] else None,
    ]
    return "ход героя: " + ", ".join(p for p in parts if p)


def _snap(ctx: ToolContext) -> dict:
    return {"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(ctx.world.scene.state)}


def _need_action(world, hero_id: str, led: dict, what: str) -> None:
    if led["actions"] >= 1 + led["extra"]:
        name = world.characters[hero_id].name
        rest = "бонусное действие и шаги" if not led["bonus"] else "только шаги"
        raise ToolError(f"{name}: действие этого хода уже потрачено, на {what} его нет. Осталось: {rest}")
    led["actions"] += 1


def _need_bonus(world, hero_id: str, led: dict, what: str) -> None:
    if led["bonus"]:
        raise ToolError(f"{world.characters[hero_id].name}: бонусное действие этого хода уже потрачено ({what})")
    led["bonus"] = True


def charge_attack(ctx: ToolContext, hero_id: str, bonus: bool = False) -> list[dict]:
    """Удар героя в его ход: из действия «Атака» (или бонусным действием). Возвращает запись для отмены."""
    w = ctx.world
    if not active(w, hero_id):
        return []
    inv = [_snap(ctx)]
    led = ledger(w, hero_id)
    if bonus:
        _need_bonus(w, hero_id, led, "удар бонусным действием")
    elif led["attacks_left"] > 0:
        led["attacks_left"] -= 1
    else:
        _need_action(w, hero_id, led, "атаку")
        led["attacks_left"] = attacks_per_action(w, hero_id) - 1
    _save(w, hero_id, led)
    return inv


def charge_spell(ctx: ToolContext, hero_id: str, casting_time: str, level: int) -> list[dict]:
    """Заклинание в ход героя: действие, бонусное действие или реакция по времени сотворения."""
    from app.core import combat

    w = ctx.world
    if not active(w, hero_id):
        return []
    inv = [_snap(ctx)]
    led = ledger(w, hero_id)
    name = w.characters[hero_id].name
    spells = list(led.get("spells") or [])
    if casting_time == "1 bonus action":
        if any(s["time"] == "1 action" and s["level"] > 0 for s in spells):
            raise ToolError(f"{name}: в этот ход уже было заклинание действием — бонусным теперь нельзя (SRD)")
        _need_bonus(w, hero_id, led, "заклинание")
    elif casting_time == "1 reaction":
        if not combat.reaction_available(ctx, hero_id):
            raise ToolError(f"{name}: реакция этого раунда уже потрачена")
        combat.use_reaction(ctx, hero_id)
    else:
        if level > 0 and any(s["time"] == "1 bonus action" for s in spells):
            raise ToolError(
                f"{name}: в этот ход уже было заклинание бонусным действием — действием теперь можно только заговор"
            )
        _need_action(w, hero_id, led, "заклинание")
    spells.append({"time": casting_time, "level": level})
    led["spells"] = spells
    _save(w, hero_id, led)
    return inv


def charge(ctx: ToolContext, hero_id: str, kind: str, bonus: bool = False) -> list[dict]:
    """Прочие действия хода: рывок, отход, уклонение, помощь, засада, предмет… ``bonus`` — бонусным действием
    (Хитрое действие плута, особенности класса)."""
    w = ctx.world
    if not active(w, hero_id):
        return []
    inv = [_snap(ctx)]
    led = ledger(w, hero_id)
    what = ACTIONS_RU.get(kind, kind)
    if bonus:
        _need_bonus(w, hero_id, led, what)
    else:
        _need_action(w, hero_id, led, what)
    if kind == "dash":
        led["dash"] += 1
    elif kind == "disengage":
        led["disengage"] = True
    _save(w, hero_id, led)
    return inv


def surge(ctx: ToolContext, hero_id: str) -> list[dict]:
    """Всплеск действий: ещё одно действие в этот ход."""
    w = ctx.world
    if not active(w, hero_id):
        return []
    inv = [_snap(ctx)]
    led = ledger(w, hero_id)
    led["extra"] += 1
    _save(w, hero_id, led)
    return inv
