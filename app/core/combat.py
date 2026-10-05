"""Пошаговый режим (ТЗ, раздел 5): очередь инициативы, ход героя, ходы существ по профилю поведения, реакции.

Очередь хранится в сцене: ``turn_order`` — участники по инициативе, ``state.turn`` — чей ход, ``state.deadline`` —
когда истекает время хода героя, ``state.submitted`` — герой уже заявил действие, ``state.reactions`` — кто
потратил реакцию в каком раунде. Ходы существ проводит сервер без модели: цель, сближение, атаки и бегство
выбирает профиль поведения шаблона (``behavior.profile``, ``behavior.flee_threshold``). Мастер их только описывает.
"""

from __future__ import annotations

import copy
import time
from collections.abc import Awaitable, Callable
from typing import Any

from app.core import positions as grid
from app.core import steps
from app.core.world import PLAYABLE, Actor, WorldError
from app.db.models import Character
from app.rules.dnd5e import modifiers as mod
from app.tools.registry import ToolContext, execute

ROUND_SECONDS = 6
REACH_FT = 5  # досягаемость рукопашной: соседняя клетка
DEFAULT_TURN_SEC = 300
REACTION_SEC = 15
FLEE_DEFAULT = {"aggressive": 0.25, "cowardly": 0.5}

# (ctx, персонаж, существо) → герой потратил реакцию на атаку по возможности
ReactionAsk = Callable[[ToolContext, Character, Actor], Awaitable[bool]]


def state(ctx: ToolContext) -> dict[str, Any]:
    return dict(ctx.world.scene.state or {})


def _set(ctx: ToolContext, **kw: Any) -> None:
    ctx.world.scene.state = {**(ctx.world.scene.state or {}), **kw}


def in_combat(ctx: ToolContext) -> bool:
    return ctx.world.scene.mode == "combat" and bool(ctx.world.scene.turn_order)


def current_id(ctx: ToolContext) -> str | None:
    order = ctx.world.scene.turn_order or []
    if ctx.world.scene.mode != "combat" or not order:
        return None
    i = int(state(ctx).get("turn", 0)) % len(order)
    return order[i]["id"]


def current_character(ctx: ToolContext) -> Character | None:
    cid = current_id(ctx)
    return ctx.world.characters.get(cid) if cid else None


def turn_marker(scene) -> str | None:
    """Метка хода: таймер хода срабатывает, только если с его запуска ход не сменился."""
    if scene.mode != "combat" or not scene.turn_order:
        return None
    st = scene.state or {}
    return f"{scene.round}:{st.get('turn', 0)}:{st.get('actor')}"


def timeout_sec(ctx: ToolContext) -> int:
    return int((ctx.campaign.settings or {}).get("turn_timeout_sec") or DEFAULT_TURN_SEC)


def start_combat(ctx: ToolContext) -> None:
    """Вызывается после броска инициативы: первый в очереди получает ход."""
    _set(ctx, turn=0, submitted=False, reactions={}, deadline=None, actor=None)


def end_combat(ctx: ToolContext) -> None:
    st = state(ctx)
    for k in ("turn", "submitted", "reactions", "deadline", "actor"):
        st.pop(k, None)
    ctx.world.scene.state = st


def _begin_hero_turn(ctx: ToolContext, ch: Character) -> None:
    _set(ctx, submitted=False, actor=ch.id, deadline=time.time() + timeout_sec(ctx))


async def _next(ctx: ToolContext, notes: list[str]) -> None:
    """Передаёт ход следующему. Новый раунд — плюс 6 секунд игрового времени и снятие истёкших эффектов."""
    from app.tools.master.scene import expire_effects

    sc = ctx.world.scene
    i = int(state(ctx).get("turn", 0)) + 1
    if i >= len(sc.turn_order):
        i = 0
        sc.round += 1
        sc.game_time += ROUND_SECONDS
        gone = await expire_effects(ctx, [])
        if gone:
            notes.append("закончились эффекты: " + ", ".join(gone))
        notes.append(f"раунд {sc.round}")
    _set(ctx, turn=i, submitted=False, actor=None, deadline=None)


# --- бой по местам (разделение отряда, design/party-split.md) ---
# Очередь инициативы одна, но у каждого участника своё место. Существо бьёт только героев своего места, бой в месте
# заканчивается сам, когда там не осталось врагов или стоящих героев. Герои, которых нет в очереди, играют свободно.


def place_in(scene, characters: dict, entities: dict, actor_id: str) -> str | None:
    """Место участника боя; без своего места — место сцены."""
    ch = characters.get(actor_id)
    en = entities.get(actor_id)
    own = ch.location_id if ch is not None else en.location_id if en is not None else None
    return own or scene.location_id


def fronts_of(scene, characters: dict, entities: dict) -> set[str | None]:
    """Места, где идёт бой: места участников очереди инициативы."""
    if scene.mode != "combat":
        return set()
    return {place_in(scene, characters, entities, x["id"]) for x in scene.turn_order or []}


def fronts(world) -> set[str | None]:
    return fronts_of(world.scene, world.characters, world.entities)


def _at(ctx: ToolContext, actor_id: str) -> str | None:
    w = ctx.world
    return place_in(w.scene, w.characters, w.entities, actor_id)


def fights(scene, characters: dict, entities: dict, hero_id: str | None) -> bool:
    """Касается ли идущий бой героя. Пока отряд вместе (или герой не указан), бой касается всех; разделился — только
    тех, кто в очереди или стоит в месте боя."""
    from app.core.world import party_groups

    if scene.mode != "combat":
        return False
    if hero_id is None or not scene.turn_order or any(x["id"] == hero_id for x in scene.turn_order):
        return True
    if len(party_groups(characters.values(), scene)) <= 1:
        return True
    return place_in(scene, characters, entities, hero_id) in fronts_of(scene, characters, entities)


async def hero_fights(session, sc, ch: Character | None) -> bool:
    """То же по базе: для игроков и ИИ-игроков вне хода мастера."""
    from sqlalchemy import select

    if sc.mode != "combat":
        return False
    if ch is None or not sc.turn_order or any(x["id"] == ch.id for x in sc.turn_order):
        return True
    chars = (await session.scalars(select(Character).where(Character.campaign_id == sc.campaign_id))).all()
    from app.core.world import party_groups

    return len(party_groups(chars, sc)) <= 1


def drop(ctx: ToolContext, ids: set[str]) -> list[str]:
    """Убирает участников из очереди, не сбивая чужой ход. Ушёл тот, чей ход, — ход переходит к следующему."""
    sc = ctx.world.scene
    order = list(sc.turn_order or [])
    keep = [x for x in order if x["id"] not in ids]
    if len(keep) == len(order):
        return []
    gone = [x["id"] for x in order if x["id"] in ids]
    turn = int(state(ctx).get("turn", 0)) % len(order)
    cur = order[turn]["id"]
    sc.turn_order = keep
    if not keep:
        return gone
    if cur in ids:
        nxt = next(x["id"] for x in order[turn:] + order[:turn] if x["id"] not in ids)
        _set(ctx, turn=[x["id"] for x in keep].index(nxt), submitted=False, actor=None, deadline=None)
    else:
        _set(ctx, turn=[x["id"] for x in keep].index(cur))
    return gone


def insert(ctx: ToolContext, entries: list[dict]) -> None:
    """Опоздавшие встают в очередь по своей инициативе (5e), чей ход сейчас — не меняется."""
    sc = ctx.world.scene
    order = list(sc.turn_order or [])
    cur = order[int(state(ctx).get("turn", 0)) % len(order)]["id"] if order else None
    for e in entries:
        i = next((n for n, x in enumerate(order) if (x.get("initiative") or 0) < e["initiative"]), len(order))
        order.insert(i, e)
    sc.turn_order = order
    if cur is not None:
        _set(ctx, turn=[x["id"] for x in order].index(cur))


def _hostiles_left(ctx: ToolContext, place: Any = ...) -> bool:
    for entry in ctx.world.scene.turn_order:
        en = ctx.world.entities.get(entry["id"])
        if en is None or en.kind != "creature":
            continue
        if place is not ... and _at(ctx, en.id) != place:
            continue
        st = en.state or {}
        if not st.get("dead") and not st.get("fled") and st.get("attitude", "hostile") == "hostile":
            return True
    return False


def _heroes_standing(ctx: ToolContext, place: Any = ...) -> list[Actor]:
    """Стоящие на ногах герои в очереди; ``place`` — только в этом месте."""
    out = []
    for entry in ctx.world.scene.turn_order:
        ch = ctx.world.characters.get(entry["id"])
        if place is not ... and ch is not None and _at(ctx, ch.id) != place:
            continue
        if ch is not None and ch.status in PLAYABLE:
            a = ctx.world.actor(ch.id)
            if a.alive and a.hp.current > 0:
                out.append(a)
    return out


async def finish_turn(ctx: ToolContext, notes: list[str]) -> None:
    """Герой, чей был ход, закончил его (заявил действие или вышло время)."""
    if in_combat(ctx):
        await _next(ctx, notes)


async def run_until_hero(ctx: ToolContext, key: str, ask: ReactionAsk | None = None) -> list[str]:
    """Проигрывает ходы существ и героев без сознания до ближайшего героя, который может действовать.
    Возвращает заметки для повествования. Бой заканчивается сам, когда врагов или стоящих героев не осталось."""
    notes: list[str] = []
    if not in_combat(ctx):
        return notes
    limit = len(ctx.world.scene.turn_order) * 3 + 3
    for step in range(limit):
        if await close_fronts(ctx, notes):
            return notes
        cid = current_id(ctx)
        try:
            act = ctx.world.actor(cid)
        except WorldError:
            await _next(ctx, notes)
            continue
        if act.kind == "character":
            ch = ctx.world.characters[cid]
            if ch.status not in PLAYABLE or not act.alive:
                await _next(ctx, notes)
                continue
            if act.hp.current == 0:
                if act.hp.dying:
                    r = await execute(ctx, "death_save", {"character_id": cid}, key=f"{key}:ds:{cid}:{step}")
                    if r.get("ok"):
                        notes.append(_death_note(act.name, r["result"]))
                await _next(ctx, notes)
                continue
            blocked = mod.can_act(act.modifiers)
            if blocked:
                notes.append(f"{act.name} пропускает ход: {blocked}")
                await _next(ctx, notes)
                continue
            _begin_hero_turn(ctx, ch)
            return notes
        await creature_turn(ctx, act, f"{key}:{step}", notes, ask)
        await _next(ctx, notes)
    return notes


def _front_end(ctx: ToolContext, place: str | None) -> str | None:
    """Почему бой в этом месте окончен; None — бой там идёт."""
    if not _hostiles_left(ctx, place):
        return "врагов не осталось"
    if not _heroes_standing(ctx, place):
        here = [x["id"] for x in ctx.world.scene.turn_order if x["id"] in ctx.world.characters]
        if not any(_at(ctx, i) == place for i in here):
            return "герои ушли"
        return "все герои повержены"
    return None


def active_fronts(ctx: ToolContext) -> dict[str | None, str | None]:
    """Места боя и причина конца боя в каждом (None — бой там идёт)."""
    places = dict.fromkeys(_at(ctx, x["id"]) for x in ctx.world.scene.turn_order or [])
    return {p: _front_end(ctx, p) for p in places}


async def close_fronts(ctx: ToolContext, notes: list[str]) -> bool:
    """Закрывает бой там, где он кончился. True — бой окончен везде (сцена в свободном режиме)."""
    ends = active_fronts(ctx)
    done = {p: why for p, why in ends.items() if why}
    if not done:
        return False
    if len(done) == len(ends):
        await _stop(ctx, notes, "; ".join(dict.fromkeys(done.values())))
        return True
    sc = ctx.world.scene
    inverse = [
        {"table": "scenes", "id": ctx.campaign.id, "field": f, "before": copy.deepcopy(getattr(sc, f))}
        for f in ("turn_order", "state")
    ]
    for p, why in done.items():
        drop(ctx, {x["id"] for x in sc.turn_order if _at(ctx, x["id"]) == p})
        notes.append(f"бой в месте «{ctx.world._place_name(p)}» окончен: {why}")
    closed = {str(p): why for p, why in done.items()}
    await ctx.record("set_scene_mode", payload={"mode": "combat", "closed": closed}, inverse=inverse)
    return False


async def _stop(ctx: ToolContext, notes: list[str], why: str) -> None:
    r = await execute(ctx, "set_scene_mode", {"mode": "free"})
    if r.get("ok"):
        notes.append(f"бой окончен: {why}")


def _death_note(name: str, r: dict) -> str:
    if r.get("dead"):
        return f"{name}: третий провал спасброска от смерти — погиб"
    if r.get("regained_hp"):
        return f"{name}: натуральная 20 — приходит в себя с 1 хитом"
    if r.get("stable"):
        return f"{name}: стабилизировался"
    return f"{name}: спасбросок от смерти, успехи {r.get('successes')}, провалы {r.get('failures')}"


# --- ходы существ ---


def _behavior(ctx: ToolContext, act: Actor) -> dict[str, Any]:
    rec = ctx.world.catalog.find(act.obj.template_id or "")
    return dict((rec.data.get("behavior") if rec else None) or {})


def _multiattack(ctx: ToolContext, act: Actor) -> list[str]:
    """Ключи атак из «Мультиатаки» шаблона, если все они есть в листе существа."""
    rec = ctx.world.catalog.find(act.obj.template_id or "")
    have = {a["key"] for a in act.attacks}
    for a in (rec.data.get("actions") if rec else None) or []:
        if a.get("kind") == "multiattack" and a.get("multiattack"):
            keys = []
            for part in a["multiattack"]:
                keys += [part.get("action")] * int(part.get("count", 1))
            if keys and all(k in have for k in keys):
                return keys
    return []


def _pick_target(ctx: ToolContext, act: Actor) -> Actor | None:
    """Цель — стоящий на ногах герой с наименьшими хитами (добить слабого — поведение обоих профилей SRD-монстров).
    Только в месте существа: героев другой части отряда оно не достаёт."""
    heroes = _heroes_standing(ctx, _at(ctx, act.id))
    return min(heroes, key=lambda a: (a.hp.current, a.id)) if heroes else None


async def creature_turn(ctx: ToolContext, act: Actor, key: str, notes: list[str], ask: ReactionAsk | None) -> None:
    en = act.obj
    st = en.state or {}
    if not act.alive or st.get("fled"):
        return
    if st.get("attitude", "hostile") != "hostile":
        return
    blocked = mod.can_act(act.modifiers)
    if blocked:
        notes.append(f"{act.name} пропускает ход: {blocked}")
        return
    beh = _behavior(ctx, act)
    profile = str(beh.get("profile") or "aggressive")
    threshold = float(beh.get("flee_threshold", FLEE_DEFAULT.get(profile, 0.25)))
    if act.hp.maximum and act.hp.current / act.hp.maximum <= threshold:
        await _flee(ctx, act, key, notes, ask)
        return
    target = _pick_target(ctx, act)
    if target is None:
        return
    melee = [a for a in act.attacks if a["kind"] == "melee"]
    ranged = [a for a in act.attacks if a["kind"] == "ranged" or a.get("normal_ft")]
    if _on_grid(ctx, en.id):
        # бой на сетке: бьёт того, кто рядом; иначе идёт к соседней с целью клетке в пределах скорости
        near = [h for h in _heroes_standing(ctx, _at(ctx, en.id)) if ctx.world.distance_ft(act, h) <= REACH_FT]
        if near:
            target = min(near, key=lambda a: (a.hp.current, a.id))
        close = ctx.world.distance_ft(act, target) <= REACH_FT
        seen = not grid.wall_between(ctx.world, en.id, target.id)  # за стеной не выстрелить: сперва обойти
        if not close and ((melee and (not ranged or profile == "aggressive")) or not seen):
            route = steps.toward(ctx.world, _at(ctx, en.id), en.id, target.id, max(1, act.speed // 5))
            if route:
                cell = grid.to_master(ctx.world, _at(ctx, en.id), route[-1])
                r = await execute(ctx, "reposition", {"actor_id": en.id, "cell": list(cell)}, key=f"{key}:move")
                if r.get("ok"):
                    notes.append(f"{act.name} подходит к {target.name} ({len(route) * 5} фт)")
            act = ctx.world.actor(en.id)
            close = ctx.world.distance_ft(act, target) <= REACH_FT
            seen = not grid.wall_between(ctx.world, en.id, target.id)
            if not close and (not ranged or not seen):
                return
        if close and melee:
            keys = _multiattack(ctx, act) or [melee[0]["key"]]
            keys = [k for k in keys if any(a["key"] == k and a["kind"] == "melee" for a in act.attacks)] or [
                melee[0]["key"]
            ]
        elif ranged:
            keys = [ranged[0]["key"]]
        else:
            return
        await _strike(ctx, act, target, keys, key, notes)
        return
    if en.zone != "melee" and melee and (not ranged or profile == "aggressive"):
        before = en.zone
        new_zone = "melee" if en.zone == "near" else "near"
        r = await execute(ctx, "update_entity", {"entity_id": en.id, "zone": new_zone}, key=f"{key}:move")
        if r.get("ok"):
            notes.append(f"{act.name} сближается ({before} → {new_zone})")
        if new_zone != "melee":
            return
    if en.zone == "melee" and melee:
        keys = _multiattack(ctx, act) or [melee[0]["key"]]
        keys = [k for k in keys if any(a["key"] == k and a["kind"] == "melee" for a in act.attacks)] or [
            melee[0]["key"]
        ]
    elif ranged:
        keys = [ranged[0]["key"]]
    else:
        return
    await _strike(ctx, act, target, keys, key, notes)


def _on_grid(ctx: ToolContext, actor_id: str) -> bool:
    return grid.pos_of(ctx.world, actor_id).cell is not None


async def _strike(ctx: ToolContext, act: Actor, target: Actor, keys: list[str], key: str, notes: list[str]) -> None:
    en = act.obj
    for n, k in enumerate(keys):
        tgt = target if target.hp.current > 0 else _pick_target(ctx, act)
        if tgt is None:
            break
        r = await execute(
            ctx, "resolve_attack", {"attacker_id": en.id, "target_id": tgt.id, "attack": k}, key=f"{key}:atk{n}"
        )
        if not r.get("ok"):
            notes.append(f"{act.name} не смог атаковать: {r.get('error')}")
            break
        notes.append(_attack_note(act.name, tgt.name, r["result"]))
        target = ctx.world.actor(tgt.id)


async def _flee(ctx: ToolContext, act: Actor, key: str, notes: list[str], ask: ReactionAsk | None) -> None:
    en = act.obj
    grid_mode = _on_grid(ctx, en.id)
    if (grid_mode or en.zone == "melee") and ask is not None:
        for hero in _heroes_standing(ctx, _at(ctx, en.id)):
            if grid_mode and ctx.world.distance_ft(hero, act) > REACH_FT:
                continue  # на сетке бьёт вдогонку только тот, кто стоит рядом
            ch = ctx.world.characters[hero.id]
            if not reaction_available(ctx, ch.id) or not _melee_attack(hero):
                continue
            if mod.can_act(hero.modifiers):
                continue
            if await ask(ctx, ch, act):
                use_reaction(ctx, ch.id)
                r = await execute(
                    ctx,
                    "resolve_attack",
                    {"attacker_id": ch.id, "target_id": en.id, "attack": _melee_attack(hero)},
                    key=f"{key}:oa:{ch.id}",
                )
                if r.get("ok"):
                    notes.append(
                        f"{hero.name} бьёт вдогонку (атака по возможности): " + _attack_note("", "", r["result"])
                    )
            act = ctx.world.actor(en.id)
            if not act.alive:
                return
    r = await execute(ctx, "update_entity", {"entity_id": en.id, "fled": True}, key=f"{key}:flee")
    if r.get("ok"):
        notes.append(f"{act.name} бежит с поля боя")


def _attack_note(who: str, target: str, r: dict) -> str:
    head = f"{who} атакует {target}: " if who else ""
    if not r.get("hit"):
        return head + ("критический промах (натуральная 1)" if r.get("fumble") else "промах")
    out = head + ("критическое попадание" if r.get("critical") else "попадание") + f", {r.get('damage', 0)} урона"
    if r.get("target_status") in ("мёртв", "при смерти", "стабилен"):  # числа хитов существ игрокам не показываем
        out += f" ({r['target_status']})"
    return out


def _melee_attack(a: Actor) -> str | None:
    for x in a.attacks:
        if x["kind"] == "melee" and x.get("inventory_id"):
            return x["inventory_id"]
    for x in a.attacks:
        if x["kind"] == "melee":
            return x["key"]
    return None


def reaction_available(ctx: ToolContext, character_id: str) -> bool:
    used = (state(ctx).get("reactions") or {}).get(character_id)
    return used != ctx.world.scene.round


def use_reaction(ctx: ToolContext, character_id: str) -> None:
    r = dict(state(ctx).get("reactions") or {})
    r[character_id] = ctx.world.scene.round
    _set(ctx, reactions=r)


def reaction_options(hero: Actor, creature: Actor) -> list[dict[str, str]]:
    weapon = next((x for x in hero.attacks if x["kind"] == "melee"), None)
    label = f"Атака по возможности: {weapon['name'] if weapon else 'удар'} по «{creature.name}»"
    return [{"id": "opportunity_attack", "label": label}, {"id": "skip", "label": "Не реагировать"}]


def public_turn(world) -> dict[str, Any] | None:
    """Чей ход — для клиентов (событие turn.changed и снимок сцены)."""
    turn = public_turn_of(world.scene, world.characters, world.entities)
    if turn is not None:
        from app.core import economy

        left = economy.view(world, turn["actor_id"])
        if left is not None:
            turn["economy"] = left
    return turn


def public_turn_of(sc, characters: dict, entities: dict) -> dict[str, Any] | None:
    if sc.mode != "combat" or not sc.turn_order:
        return None
    st = dict(sc.state or {})
    cid = sc.turn_order[int(st.get("turn", 0)) % len(sc.turn_order)]["id"]
    ch = characters.get(cid)
    name = ch.name if ch else (entities[cid].name if cid in entities else "существо")
    return {
        "round": sc.round,
        "actor_id": cid,
        "name": name,
        "seat_id": ch.seat_id if ch else None,
        "deadline": st.get("deadline"),
        "submitted": bool(st.get("submitted")),
    }


def turn_views(world) -> list[tuple[list[str] | None, dict[str, Any] | None]]:
    """Кому какой ход показать. Отряд разделён и бой не везде — героям вне боя хода нет, они играют свободно."""
    turn = public_turn(world)
    groups = world.groups()
    if turn is None or len(groups) <= 1:
        return [(None, turn)]
    places = fronts(world)
    calm = [h.seat_id for p, hs in groups.items() if p not in places for h in hs if h.seat_id]
    if not calm:
        return [(None, turn)]
    rest = [x.id for x in world.campaign.seats if x.id not in calm]
    return [(calm, None), (rest, turn)]


def public_order(turn_order: list[dict], characters: dict[str, Character], entities: dict[str, Any]) -> list[dict]:
    """Полоса инициативы для игроков: имя, сторона и выбыл ли участник. Хиты существ не раскрываются."""
    out = []
    for entry in turn_order or []:
        i = entry["id"]
        item: dict[str, Any] = {"id": i, "initiative": entry.get("initiative")}
        ch = characters.get(i)
        en = entities.get(i)
        if ch is not None:
            res = ch.resources or {}
            item |= {"name": ch.name, "side": "hero", "seat_id": ch.seat_id}
            item["out"] = "пал" if res.get("dead") else "без сознания" if res.get("hp") == 0 else None
        elif en is not None:
            st = en.state or {}
            item |= {"name": en.name, "side": "enemy" if st.get("attitude", "hostile") == "hostile" else "ally"}
            item["out"] = "мёртв" if st.get("dead") else "бежал" if st.get("fled") else None
        else:
            item |= {"name": "существо", "side": "enemy", "out": "ушёл"}
        out.append(item)
    return out


async def gate_message(session, viewer, kind: str, *, mark: bool = True) -> str | None:
    """В бою пишет только игрок, чей ход (раздел 5). Вне игры (//) — всегда можно.
    Действие занимает ход: второе действие до ответа мастера не принимается. Вне боя при ИИ-мастере у игрока одна
    ожидающая реплика (действие, речь или шёпот). В бою это правило не действует: ход мастера там запускает
    только действие героя, и речь или шёпот до него иначе заперли бы действие. Возвращает причину отказа."""
    from app.core.chat import PENDING_KINDS, PENDING_REASON, pending_message
    from app.core.world import get_scene

    if not viewer.is_player:
        return None
    if (viewer.campaign.settings or {}).get("intro_generating") and kind != "ooc":
        return "Мастер готовит вступление к кампании…"
    sc = await get_scene(session, viewer.campaign.id)
    in_combat = sc.mode == "combat" and bool(sc.turn_order)
    if in_combat:  # отряд разделён: герой не в очереди — бой идёт в другом месте, он играет свободно
        in_combat = await hero_fights(session, sc, await seat_hero(session, viewer.campaign.id, viewer.seat.id))
    if (
        not in_combat
        and kind in PENDING_KINDS
        and await pending_message(session, viewer.campaign, viewer.seat.id) is not None
    ):
        return PENDING_REASON
    if kind not in ("action", "speech") or not in_combat:
        return None
    st = dict(sc.state or {})
    cid = sc.turn_order[int(st.get("turn", 0)) % len(sc.turn_order)]["id"]
    ch = await session.get(Character, cid)
    if ch is None or ch.seat_id != viewer.seat.id:
        who = ch.name if ch is not None else "существ"
        return f"Идёт бой, сейчас ход: {who}. Пока можно писать вне игры (//) или шёпотом мастеру."
    if kind == "action":
        if st.get("submitted"):
            return "Действие на этот ход уже заявлено: дождитесь ответа мастера."
        if mark:
            sc.state = {**st, "submitted": True}
    return None


async def seat_hero(session, campaign_id: str, seat_id: str) -> Character | None:
    from sqlalchemy import select

    q = select(Character).where(
        Character.campaign_id == campaign_id, Character.seat_id == seat_id, Character.status.in_(PLAYABLE)
    )
    return (await session.scalars(q)).first()


async def unsubmit(session, viewer) -> None:
    """Отменённое действие освобождает ход: заявку можно сделать заново."""
    from app.core.world import get_scene

    sc = await get_scene(session, viewer.campaign.id)
    st = dict(sc.state or {})
    if sc.mode != "combat" or not sc.turn_order or not st.get("submitted") or viewer.seat is None:
        return
    ch = await session.get(Character, sc.turn_order[int(st.get("turn", 0)) % len(sc.turn_order)]["id"])
    if ch is not None and ch.seat_id == viewer.seat.id:
        sc.state = {**st, "submitted": False}
