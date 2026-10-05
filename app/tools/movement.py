"""Шаг героя по клетке, которую игрок нажал на схеме (app/core/steps.py). Не инструмент мастера: зовёт его шлюз
по событию ``map.step`` от игрока, а мастер видит новую клетку героя в таблице сцены и в журнале."""

from __future__ import annotations

import copy
from typing import Any

from app.core import combat, steps
from app.core import positions as grid
from app.rules.dnd5e import modifiers as mod
from app.tools.registry import ToolContext, ToolError, execute


def _used(ctx: ToolContext, hero_id: str) -> int:
    """Сколько футов герой уже прошёл за этот ход боя."""
    st = (ctx.world.scene.state or {}).get("moved") or {}
    mine = st.get(hero_id) or {}
    return int(mine.get("ft") or 0) if mine.get("turn") == combat.turn_marker(ctx.world.scene) else 0


def _melee_key(act) -> str | None:
    return next((x["key"] for x in act.attacks if x["kind"] == "melee"), None)


async def hero_step(
    ctx: ToolContext,
    hero_id: str,
    goal: tuple[int, int] | None,
    confirm: bool = False,
    near: list[tuple[int, int]] | None = None,
) -> dict[str, Any]:
    """Ведёт героя на клетку ``goal`` (от строя отряда) или, с ``near``, к ближайшей свободной клетке рядом с этими
    клетками (подойти к предмету, существу, выходу). Без ``confirm`` рывок и атаки по возможности только
    предупреждают: ответ с ``confirm_needed`` — ничего не сделано."""
    w = ctx.world
    hero = w.actor(hero_id)
    if not hero.alive or hero.hp.current <= 0:
        raise ToolError(f"{hero.name} без сознания и не может идти")
    blocked = mod.can_act(hero.modifiers)
    if blocked:
        raise ToolError(f"{hero.name} не может двигаться: {blocked}")
    place = w.actor_place(hero_id)
    fighting = combat.in_combat(ctx) and combat.fights(w.scene, w.characters, w.entities, hero_id)
    if fighting and combat.current_id(ctx) != hero_id:
        raise ToolError("в бою ходят по очереди: дождись своего хода")
    start = steps.cell_of(w, hero_id)
    speed = int(hero.speed or 0)
    used = _used(ctx, hero_id) if fighting else 0
    left = max(0, 2 * speed - used) // 5 if fighting else None
    if near:
        route = steps.beside(w, place, start, near, hero_id, left)
        if route is None:
            within = " в пределах хода" if fighting else ""
            raise ToolError(f"подойти не получится: рядом нет свободной клетки{within}")
    elif goal is None:
        raise ToolError("куда идти: нужна клетка")
    else:
        route = steps.path(w, place, start, goal, hero_id, left)
    if route is None:
        problem = grid.cell_problem(w, place, goal, hero_id)
        if problem:
            raise ToolError(problem)
        if fighting:
            raise ToolError(f"не дойти: за этот ход осталось {max(0, 2 * speed - used)} футов с рывком")
        raise ToolError("туда не пройти: путь закрыт")
    if not route:
        return {"who": hero.name, "moved_ft": 0}
    ft = len(route) * 5
    warn: list[str] = []
    dash = fighting and used <= speed < used + ft
    if dash:
        warn.append(f"рывок: дальше {speed} футов за ход — потратит действие")
    foes = steps.provokers(w, place, start, route) if fighting else []
    foes = [e for e in foes if combat.reaction_available(ctx, e.id) and _melee_key(w.actor(e.id))]
    if foes:
        warn.append("уход провоцирует атаку по возможности: " + ", ".join(e.name for e in foes))
    if warn and not confirm:
        return {"who": hero.name, "confirm_needed": True, "warnings": warn, "moved_ft": ft}

    sc = w.scene
    inverse = [{"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(sc.state)}]
    notes: list[str] = []
    for e in foes:  # атаки по возможности — до шага из досягаемости
        atk = w.actor(e.id)
        if not atk.alive or mod.can_act(atk.modifiers):
            continue
        combat.use_reaction(ctx, e.id)
        r = await execute(
            ctx,
            "resolve_attack",
            {"attacker_id": e.id, "target_id": hero_id, "attack": _melee_key(atk)},
            key=f"oa:{e.id}:{sc.round}",
        )
        if r.get("ok"):
            notes.append(f"{e.name} бьёт вдогонку (атака по возможности): " + combat._attack_note("", "", r["result"]))
        if w.actor(hero_id).hp.current <= 0:
            notes.append(f"{hero.name} падает и не доходит")
            break
    else:
        grid.set_cell(w, hero_id, route[-1])
        if fighting:
            moved = dict((sc.state or {}).get("moved") or {})
            moved[hero_id] = {"turn": combat.turn_marker(sc), "ft": used + ft}
            sc.state = {**(sc.state or {}), "moved": moved}
    ctx.changed.add(hero_id)
    dest = grid.to_master(w, place, route[-1])
    out: dict[str, Any] = {"who": hero.name, "moved_ft": ft, "cell": list(dest)}
    if dash:
        out["dash"] = True
    if notes:
        out["notes"] = notes
        ctx.outbox.append({"kind": "system", "content": "; ".join(notes)})
    if fighting:
        out["left_ft"] = (speed if used + ft <= speed else 2 * speed) - used - ft
    await ctx.record("step", actor_id=hero_id, target_id=hero_id, payload=out, inverse=inverse)
    return out
