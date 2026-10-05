"""Отдых отряда по SRD 5.1 (просьба Arty 2026-10-04).

Отдых — решение всей группы, которая стоит на одном месте: один герой не спит, пока другие идут дальше. Кто угодно
(игрок словами, мастер инструментом ``rest``) предлагает короткий или продолжительный отдых — сервер открывает
голосование для героев этого места. Если место ненадёжное или опасное, предупреждение и места поспокойнее видны
сразу на карточке голосования, а в ненадёжном месте каждый выбирает, спит он или стоит на страже. Один «против» —
отдыха нет. Не ответил до конца срока — отдыхает вместе со всеми.

Итог считает сервер: засаду (проверки по расписанию места на d6, в безопасном месте — никогда), кто застигнут
врасплох (никто, если хоть кто-то стоял на страже), и что вернул отдых тем, кто спал: хиты, кости хитов, ячейки
заклинаний, умения с перезарядкой. Стража не отдыхает. Все на страже — отдых никому не засчитан, а засада всё равно
возможна. Засада обрывает отдых: существа из таблицы встреч места выходят в сцену, и начинается бой.

Умения с ограниченным числом использований (ярость, второе дыхание, ци, божественный канал…) тратит ``use_feature``.
"""

from __future__ import annotations

import copy
import time
import uuid
from math import ceil
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.content.catalog import CatalogError
from app.core import chat, economy
from app.core import features as feats
from app.core.world import PLAYABLE, WorldError, format_time
from app.db.models import Character
from app.rules.dnd5e import rest as rules
from app.tools import effects as fx
from app.tools import fortune
from app.tools.master import (
    SceneModeArgs,
    SpawnArgs,
    encounter_budget,
    engine,
    expire_effects,
    set_scene_mode,
    snapshot,
    spawn_entity,
)
from app.tools.registry import ToolContext, ToolError, dice_json, tool

VOTE_SEC = 120.0  # сколько ждать голосов; кто не ответил — отдыхает со всеми
HOURS = {"short": 1, "long": 8}
KIND_RU = {"short": "короткий отдых (1 час)", "long": "продолжительный отдых (8 часов)"}
CHOICE_RU = {"sleep": "отдыхает", "watch": "на страже", "no": "против"}
DAY = 24 * 3600


# --- место ---


def _chain(ctx: ToolContext, place: str | None) -> list:
    loc = ctx.world.entities.get(place or "")
    out, rid = [], loc.template_id if loc else None
    while rid and len(out) < 4:
        rec = ctx.world.catalog.find(rid, "location_template")
        if rec is None or rec in out:
            break
        out.append(rec)
        rid = rec.data.get("parent_ref")
    return out


def place_safety(ctx: ToolContext, place: str | None) -> str:
    """Насколько место годится для ночлега: отметка мастера, данные пакета, теги места."""
    loc = ctx.world.entities.get(place or "")
    chain = _chain(ctx, place)
    explicit = (loc.state or {}).get("rest_safety") if loc else None
    explicit = explicit or next((r.data["rest_safety"] for r in chain if r.data.get("rest_safety")), None)
    watch = next((r.data["encounter_check"] for r in chain if isinstance(r.data.get("encounter_check"), dict)), None)
    return rules.place_safety(explicit, fortune._words(chain), watch)


def _place_name(ctx: ToolContext, place: str | None) -> str:
    loc = ctx.world.entities.get(place or "")
    return loc.name if loc else "здесь"


def _safer(ctx: ToolContext, place: str | None) -> list[str]:
    """Известные отряду места, где ночевать спокойно."""
    return [
        e.name
        for e in ctx.world.entities.values()
        if e.kind == "location" and e.id != place and place_safety(ctx, e.id) == rules.SAFE
    ][:3]


def _hostiles(ctx: ToolContext, place: str | None) -> list[str]:
    out = []
    for e in ctx.world.in_scene_entities(place):
        st = e.state or {}
        if e.kind == "creature" and not st.get("dead") and not st.get("fled") and st.get("attitude") == "hostile":
            out.append(e.name)
    return out


def _group(ctx: ToolContext, ids: list[str]) -> tuple[str | None, list[Character]]:
    groups = ctx.world.groups()
    if ids:
        ch = ctx.world.characters.get(ids[0])
        if ch is None or ch.status not in PLAYABLE:
            raise ToolError(f"нет героя в игре {ids[0]}")
        place = ctx.world.place_of(ch)
        return place, groups.get(place, [ch])
    if not groups:
        raise ToolError("в игре нет героев")
    if len(groups) > 1:
        raise ToolError("отряд разделён: назовите героя (character_ids), чья группа отдыхает")
    return next(iter(groups.items()))


def _warning(safety: str, safer: list[str]) -> str | None:
    if safety == rules.SAFE:
        return None
    head = (
        "Место опасное: засада здесь вероятна."
        if safety == rules.DANGEROUS
        else "Место ненадёжное: во время отдыха возможна засада."
    )
    move = f" Спокойнее отдохнуть: {', '.join(safer)}." if safer else " Лучше поискать место понадёжнее."
    return head + move + " Если всё же остаётесь, решите, кто спит, а кто стоит на страже."


# --- голосование ---


def _votes(ctx: ToolContext) -> dict[str, dict]:
    return copy.deepcopy(dict((ctx.world.scene.state or {}).get("rest_votes") or {}))


def _store(ctx: ToolContext, votes: dict[str, dict]) -> None:
    st = {k: v for k, v in (ctx.world.scene.state or {}).items() if k != "rest_votes"}
    if votes:
        st["rest_votes"] = votes
    ctx.world.scene.state = st


def public(ctx: ToolContext, v: dict) -> dict[str, Any]:
    """Карточка голосования для игроков места: кто решает, кто уже выбрал и что."""
    heroes = []
    for hid in v["heroes"]:
        ch = ctx.world.characters.get(hid)
        if ch is None:
            continue
        res = ch.resources or {}
        heroes.append(
            {
                "id": hid,
                "name": ch.name,
                "seat_id": ch.seat_id,
                "voter": hid in v["voters"],
                "choice": (v["ballots"].get(hid) or {}).get("choice"),
                "hit_dice": (v["ballots"].get(hid) or {}).get("hit_dice"),
                "hit_dice_left": int(res.get("hit_dice", (ch.sheet or {}).get("level", 1))),
            }
        )
    return {
        "vote_id": v["id"],
        "kind": v["kind"],
        "kind_ru": KIND_RU[v["kind"]],
        "place": v["place"],
        "place_name": v["place_name"],
        "safety": v["safety"],
        "safety_ru": rules.SAFETY_RU[v["safety"]],
        "warning": v.get("warning"),
        "safer": v.get("safer") or [],
        "proposer": v.get("proposer"),
        "heroes": heroes,
        "choices": ["sleep", "no"] if v["safety"] == rules.SAFE else ["sleep", "watch", "no"],
        "deadline": v["deadline"],
    }


def _audience(ctx: ToolContext, v: dict) -> list[str]:
    heroes = [ctx.world.characters[h] for h in v["heroes"] if h in ctx.world.characters]
    return chat.audience(ctx.campaign, heroes)


def _announce(ctx: ToolContext, v: dict) -> None:
    ctx.notices.append(("rest.vote", public(ctx, v), _audience(ctx, v)))


def _say(ctx: ToolContext, v: dict, text: str) -> None:
    ctx.outbox.append({"kind": "system", "content": text, "visible_to": _audience(ctx, v)})


def _ai_ballots(ctx: ToolContext, v: dict, heroes: list[Character]) -> None:
    """Героев ИИ-игроков сервер не ждёт: они согласны отдыхать. В ненадёжном месте самый зоркий из них (пассивная
    Внимательность) встаёт на стражу, остальные спят."""
    agents = {s.id for s in ctx.campaign.seats if s.occupant_type == "agent"}
    ai = [h for h in heroes if h.id in v["voters"] and h.seat_id in agents]
    if not ai:
        return
    watcher = None
    if v["safety"] != rules.SAFE:
        watcher = max(ai, key=lambda h: ctx.world.actor(h.id).ability_check_bonus("perception")[0]).id
    for h in ai:
        v["ballots"][h.id] = {"choice": "watch" if h.id == watcher else "sleep", "hit_dice": None}


async def propose(ctx: ToolContext, kind: str, ids: list[str], proposer: str | None = None) -> dict:
    w = ctx.world
    place, heroes = _group(ctx, ids)
    if any(w.in_fight(h.id) for h in heroes):
        raise ToolError("в бою не отдыхают: сначала закончите бой")
    votes = _votes(ctx)
    if any(x["place"] == place for x in votes.values()):
        raise ToolError("отряд здесь уже решает, отдыхать ли: дождитесь итога голосования")
    near = _hostiles(ctx, place)
    if near:
        raise ToolError(f"рядом враги ({', '.join(near[:4])}): при них не отдохнуть, сначала разберитесь с ними")
    alive = [h for h in heroes if w.actor(h.id).alive]
    voters = [h.id for h in alive if w.actor(h.id).conscious]
    if not voters:
        raise ToolError("в группе нет героев в сознании: решать некому")
    if kind == "long":
        now = w.scene.game_time
        fresh = [h for h in alive if now - int((h.resources or {}).get("last_long_rest", -DAY)) < DAY]
        if len(fresh) == len(alive):
            raise ToolError("продолжительный отдых — не чаще раза в 24 часа игрового времени: все уже отдыхали")
    safety = place_safety(ctx, place)
    safer = _safer(ctx, place) if safety != rules.SAFE else []
    wait = float((ctx.campaign.settings or {}).get("rest_vote_sec") or VOTE_SEC)
    v = {
        "id": uuid.uuid4().hex[:12],
        "kind": kind,
        "place": place,
        "place_name": _place_name(ctx, place),
        "heroes": [h.id for h in alive],
        "voters": voters,
        "ballots": {},
        "safety": safety,
        "warning": _warning(safety, safer),
        "safer": safer,
        "proposer": proposer,
        "deadline": time.time() + wait,
    }
    _ai_ballots(ctx, v, alive)
    before = copy.deepcopy(w.scene.state)
    votes[v["id"]] = v
    _store(ctx, votes)
    await ctx.record(
        "rest_vote",
        payload={"vote_id": v["id"], "kind": kind, "place": place, "safety": safety, "heroes": v["heroes"]},
        inverse=[{"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": before}],
    )
    who = f"{proposer} предлагает" if proposer else "Отряд решает:"
    names = ", ".join(w.characters[h].name for h in voters)
    _say(ctx, v, f"{who} {KIND_RU[kind]}. Решают все: {names}." + (f" {v['warning']}" if v["warning"] else ""))
    out = {
        "vote_id": v["id"],
        "kind": kind,
        "place": v["place_name"],
        "safety": rules.SAFETY_RU[safety],
        "voters": names,
        "note": "Отдых начнётся, когда решат все герои этого места: не описывай его как состоявшийся. "
        + ("Предупреди отряд об опасности места своими словами." if v["warning"] else ""),
    }
    if v["warning"]:
        out["warning"] = v["warning"]
    if len(v["ballots"]) == len(voters):
        out["outcome"] = await _finish(ctx, v, timeout=False)
    else:
        _announce(ctx, v)
    return out


async def ballot(ctx: ToolContext, vote_id: str, hero_id: str, choice: str, hit_dice: int | None) -> dict:
    votes = _votes(ctx)
    v = votes.get(vote_id)
    if v is None:
        raise ToolError("голосование за отдых уже закончилось")
    if hero_id not in v["voters"]:
        raise ToolError("этот герой в голосовании не участвует: решают герои в сознании на этом месте")
    if choice not in CHOICE_RU:
        raise ToolError(f"нет варианта {choice}: можно sleep, watch или no")
    if choice == "watch" and v["safety"] == rules.SAFE:
        raise ToolError("место безопасное: стража не нужна, выберите «отдыхаю» или «против»")
    v["ballots"][hero_id] = {"choice": choice, "hit_dice": hit_dice}
    if len(v["ballots"]) >= len(v["voters"]):
        return {"outcome": await _finish(ctx, v, timeout=False)}
    votes[vote_id] = v
    _store(ctx, votes)
    _announce(ctx, v)
    return {"voted": choice}


async def expire(ctx: ToolContext, vote_id: str) -> dict | None:
    """Срок голосования вышел: кто не ответил, отдыхает со всеми."""
    v = _votes(ctx).get(vote_id)
    if v is None or v["deadline"] > time.time():
        return None
    return await _finish(ctx, v, timeout=True)


async def _finish(ctx: ToolContext, v: dict, *, timeout: bool) -> dict:
    w = ctx.world
    votes = _votes(ctx)
    votes.pop(v["id"], None)
    inverse: list = [
        {"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(w.scene.state)},
        {"table": "scenes", "id": ctx.campaign.id, "field": "game_time", "before": w.scene.game_time},
    ]
    _store(ctx, votes)
    ctx.notices.append(("rest.ended", {"vote_id": v["id"]}, _audience(ctx, v)))
    for h in v["voters"]:
        v["ballots"].setdefault(h, {"choice": "sleep", "hit_dice": None})
    name = {h: w.characters[h].name for h in v["heroes"] if h in w.characters}
    against = [name[h] for h, b in v["ballots"].items() if b["choice"] == "no" and h in name]
    if against:
        await ctx.record("rest", payload={"kind": v["kind"], "declined": against}, inverse=inverse[:1])
        _say(ctx, v, f"Отдыха не будет: против {', '.join(against)}.")
        return {"declined": against}

    watchers = [h for h, b in v["ballots"].items() if b["choice"] == "watch" and h in name]
    sleepers = [h for h in v["heroes"] if h in name and h not in watchers]
    hours = HOURS[v["kind"]]
    dice: list = []
    ambush_at, ambush = None, None
    rolls_n, hits = rules.ambush_rolls(v["safety"], hours, _watch_rule(ctx, v["place"]))
    for i in range(rolls_n):
        d = ctx.dice.die(6)
        dice.append({"expr": "1d6", "rolls": [[6, d]], "total": d, "why": "засада"})
        if d in hits:
            ambush_at = max(1, ceil((i + 1) * hours / rolls_n))
            break
    if ambush_at is not None:
        ambush = await _ambush_party(ctx, v)
        if not ambush:
            ambush_at = None  # нападать некому: ночь прошла спокойно
    elapsed = (ambush_at or hours) * 3600
    results: list[dict] = []
    if ambush_at is None and sleepers:
        results = await _apply(ctx, sleepers, v["kind"], v["ballots"], inverse, dice, end=w.scene.game_time + elapsed)
    w = ctx.world
    w.scene.game_time += elapsed
    st = dict(w.scene.state or {})
    st["fortune"] = {**dict(st.get("fortune") or {}), "checked_at": w.scene.game_time}  # время отдыха уже проверено
    w.scene.state = st
    expired = await expire_effects(ctx, inverse)
    payload: dict[str, Any] = {
        "kind": v["kind"],
        "place": v["place_name"],
        "sleepers": [name[h] for h in sleepers],
        "watchers": [name[h] for h in watchers],
        "results": results,
        "expired": expired,
        "timeout": timeout,
    }
    if not sleepers:
        payload["no_rest"] = "все стояли на страже: отдых никому не засчитан"
    if ambush:
        payload["ambush"] = {**ambush, "hour": ambush_at, "surprised": not watchers}
    await ctx.record("rest", payload=payload, dice=dice, inverse=inverse)
    _say(ctx, v, _summary(payload))
    if ambush:
        await _start_fight(ctx, v, ambush, surprised=not watchers)
    return {**payload, "time": format_time(ctx.world.scene.game_time)}


def _watch_rule(ctx: ToolContext, place: str | None) -> dict:
    w = ctx.world
    focus, crew = w.focus, w.crew
    w.focus, w.crew = place, {c.id for c in w.groups().get(place, [])}
    try:
        return fortune._watch_rule(ctx)
    finally:
        w.focus, w.crew = focus, crew


def _summary(p: dict) -> str:
    kind = KIND_RU[p["kind"]]
    if p.get("ambush"):
        a = p["ambush"]
        who = ", ".join(f"{c['name']} ×{c['count']}" for c in a["creatures"])
        how = "Отряд застигнут врасплох." if a["surprised"] else "Стража подняла тревогу: врасплох никого не застали."
        return f"Засада на {a['hour']}-м часу отдыха: {who}. Отдых прерван и не засчитан. {how}"
    parts = [f"{kind.capitalize()} позади."]
    if p.get("watchers"):
        parts.append(f"На страже: {', '.join(p['watchers'])} (без отдыха).")
    if p.get("no_rest"):
        parts.append("Все стояли на страже: отдых никому не засчитан.")
    for r in p.get("results") or []:
        parts.append(f"{r['character']}: {r['note']}.")
    return " ".join(parts)


async def _apply(
    ctx: ToolContext, ids: list[str], kind: str, ballots: dict, inverse: list, dice: list, end: int
) -> list[dict]:
    """Что отдых вернул каждому, кто спал (SRD 5.1)."""
    w = ctx.world
    out = []
    song = 0
    if kind == "short":  # «Песнь отдыха»: бард в сознании среди отдыхающих
        for hid in ids:
            ch = w.characters[hid]
            cls = w.catalog.find((ch.sheet or {}).get("class_id") or "", "class")
            row = rules._row(cls.data, int((ch.sheet or {}).get("level", 1))) if cls else {}
            if w.actor(hid).conscious and int(row.get("song_of_rest_die") or 0) > song:
                song = int(row["song_of_rest_die"])
    for hid in ids:
        ch = w.characters[hid]
        act = w.actor(hid)
        if not act.alive:
            continue
        inverse.append(snapshot(act))
        res = dict(ch.resources or {})
        level = int((ch.sheet or {}).get("level", 1))
        hd_left = int(res.get("hit_dice", level))
        pools = feats.pools_for(ch, w.catalog, act.mods, act.pb)
        notes: list[str] = []
        if kind == "long":
            if act.hp.current == 0:
                act.hp.current = 1
                act.save_hp()
                out.append({"character": ch.name, "note": "пришёл в себя с 1 хитом, отдых не засчитан"})
                w.invalidate(hid)
                continue
            last = int(res.get("last_long_rest", -DAY))
            if w.scene.game_time - last < DAY:
                out.append({"character": ch.name, "note": "с прошлого продолжительного отдыха не прошло суток"})
                continue
            act.hp.current, act.hp.temp = act.hp.maximum, 0
            act.hp.death_saves = type(act.hp.death_saves)()
            hd_left = rules.hit_dice_back(level, hd_left)
            act.save_hp()
            drop = ("slots_used", "pact_used", "concentration", "uses_spent")
            base = {k: v for k, v in ch.resources.items() if k not in drop}
            ch.resources = {**base, "hit_dice": hd_left, "can_prepare": True, "last_long_rest": end}
            notes.append(f"хиты {act.hp.current}/{act.hp.maximum}, ячейки и умения восстановлены")
            exh = next((e for e, r in act.effects if r.id == "condition.exhaustion"), None)
            if exh is not None:
                inverse.append({"table": "active_effects", "op": "restore", "row": _effect_row(exh)})
                await fx.remove_effect(ctx, act, exh.id)
                notes.append("истощение на уровень меньше")
            out.append({"character": ch.name, "hp": act.hp.current, "hit_dice": hd_left, "note": ", ".join(notes)})
            w.invalidate(hid)
            continue
        if act.hp.current == 0:
            out.append({"character": ch.name, "note": "без сознания: короткий отдых не помог"})
            continue
        cls = w.catalog.find((ch.sheet or {}).get("class_id", ""), "class")
        die = int(str((cls.data if cls else {}).get("hit_die", "d8")).lstrip("d"))
        want = (ballots.get(hid) or {}).get("hit_dice")
        healed = spent = 0
        while hd_left > 0 and act.hp.current < act.hp.maximum and (want is None or spent < int(want)):
            r = ctx.dice.roll(f"1d{die}")
            dice.append({"who": hid, **dice_json(r)})
            gain = max(0, r.total + act.mods["con"])
            engine.heal(act.hp, gain)
            healed += gain
            hd_left -= 1
            spent += 1
        if healed and song:
            r = ctx.dice.roll(f"1d{song}")
            dice.append({"who": hid, **dice_json(r), "why": "песнь отдыха"})
            engine.heal(act.hp, r.total)
            healed += r.total
        act.save_hp()
        spent_uses = rules.restore(feats.spent_of(ch), pools, "short")
        upd = {k: v for k, v in ch.resources.items() if k not in ("pact_used", "uses_spent")}
        upd["hit_dice"] = hd_left
        if spent_uses:
            upd["uses_spent"] = spent_uses
        if healed:
            notes.append(f"+{healed} хитов ({spent} к. хитов), хиты {act.hp.current}/{act.hp.maximum}")
        if any(p.per == rules.SHORT for p in pools) or (ch.resources or {}).get("pact_used"):
            notes.append("умения до короткого отдыха восстановлены")
        ar = next((p for p in pools if p.key == "arcane_recovery"), None)
        if ar is not None and not spent_uses.get("arcane_recovery") and upd.get("slots_used"):
            from app.core.spells import caster_for

            c = caster_for(ch.sheet or {}, w.catalog)
            used, back = rules.arcane_recovery(c.slots if c else [], upd["slots_used"], level)
            if back:
                upd["slots_used"] = used
                upd["uses_spent"] = {**spent_uses, "arcane_recovery": 1}
                notes.append("магическое восстановление: ячейки " + ", ".join(f"{x}-го круга" for x in back))
        ch.resources = upd
        out.append({"character": ch.name, "healed": healed, "hp": act.hp.current, "hit_dice": hd_left,
                    "note": ", ".join(notes) or "без изменений"})  # fmt: skip
        w.invalidate(hid)
        ctx.changed.add(hid)
    for hid in ids:
        ctx.changed.add(hid)
    return out


def _effect_row(e) -> dict:
    return {
        "id": e.id,
        "effect_template_id": e.effect_template_id,
        "stacks": e.stacks,
        "expires_at": e.expires_at,
        "target_id": e.target_id,
    }


# --- засада ---


async def _ambush_party(ctx: ToolContext, v: dict) -> dict | None:
    """Кто нападает: строка таблицы встреч места (враждебные существа) или, если таблиц нет, существа мира в пределах
    бюджета встречи отряда. Существа сразу выходят в сцену."""
    w = ctx.world
    place = v["place"]
    focus, crew = w.focus, w.crew
    w.focus, w.crew = place, set(v["heroes"])
    try:
        try:
            rec = fortune.pick_table(ctx, "encounter", None)
            n, row = fortune._roll_row(ctx, rec)
            found, _ = fortune._creatures(ctx, row, True, _book(ctx))
            plan = [(c["template"], c["count"]) for c in found if c.get("attitude") == "hostile"]
            source = rec.name
        except ToolError:
            plan, source = _from_bestiary(ctx, place), "существа мира"
    finally:
        w = ctx.world
        w.focus, w.crew = focus, crew
    spawned = []
    for tpl, count in plan:
        rec = ctx.world.catalog.find(tpl, "creature_template")
        for n in range(min(count, 12), 0, -1):
            args = SpawnArgs(creature_template_id=tpl, name=rec.name if rec else tpl, count=n, location_id=place)
            try:  # бюджет и блок статов проверяются до того, как существо создано
                r = await spawn_entity(ctx, args)
            except (ToolError, WorldError, CatalogError):
                continue
            spawned.append({"name": rec.name if rec else tpl, "count": n, "ids": [x["id"] for x in r["spawned"]]})
            break
    if not spawned:
        return None
    return {"source": source, "creatures": [{"name": s["name"], "count": s["count"]} for s in spawned],
            "ids": [i for s in spawned for i in s["ids"]]}  # fmt: skip


def _book(ctx: ToolContext) -> dict:
    from app.core import standing as sd

    return sd.book(ctx.world.scene.state)


def _from_bestiary(ctx: ToolContext, place: str | None) -> list[tuple[str, int]]:
    """Таблиц встреч в мире нет: кубик выбирает существо из бестиария мира, которое по опыту укладывается в бюджет
    встречи отряда (от трети до всего бюджета на одно существо)."""
    cap = encounter_budget(ctx, [], place).get("cap") or 0
    pool = [
        r
        for r in ctx.world.catalog.by_kind("creature_template")
        if r.data.get("hp")
        and cap / 8 <= int(r.data.get("xp") or 0) <= cap / 2
        and "npc" not in (r.data.get("tags") or [])
    ]
    if not pool:
        return []
    pick = pool[ctx.dice.die(len(pool)) - 1]
    return [(pick.id, 3)]


async def _start_fight(ctx: ToolContext, v: dict, ambush: dict, *, surprised: bool) -> None:
    w = ctx.world
    if surprised:
        rec = w.catalog.condition("surprised")
        for hid in v["heroes"]:
            if hid in w.characters:
                await fx.add_effect(ctx, w.actor(hid), rec, fx.UNIT_SECONDS["round"])
                ctx.changed.add(hid)
    # бой другой группы уже идёт — засада встаёт в ту же очередь
    await set_scene_mode(ctx, SceneModeArgs(mode="combat", participants=[*v["heroes"], *ambush["ids"]]))
    ctx.signals.add("combat_started")


# --- инструменты ---


class RestArgs(BaseModel):
    kind: Literal["short", "long"] = Field(description="short — час, long — 8 часов")
    character_ids: list[str] = Field(
        default_factory=list, description="кто предложил отдых или чья группа отдыхает (достаточно одного героя)"
    )


@tool(
    "rest",
    "Предложить отряду короткий (1 час) или продолжительный (8 часов) отдых. Отдыхает только вся группа на месте "
    "сразу: сервер открывает голосование героев этого места, в ненадёжном месте — с выбором, кто спит, а кто на "
    "страже, и сам считает засаду, хиты, кости хитов, ячейки и умения. Итог придёт сообщением после голосования.",
    RestArgs,
    ids={"character_ids": "characters"},
)
async def rest(ctx: ToolContext, a: RestArgs) -> dict:
    proposer = None
    if a.character_ids and a.character_ids[0] in ctx.world.characters:
        proposer = ctx.world.characters[a.character_ids[0]].name
    return await propose(ctx, a.kind, a.character_ids, proposer)


class UseFeatureArgs(BaseModel):
    character_id: str
    feature: str = Field(description="ключ или название умения: rage, second_wind, ki, channel_divinity…")
    amount: int = Field(1, ge=1, le=100, description="сколько тратит: у запасов (ци, наложение рук) — сколько очков")


@tool(
    "use_feature",
    "Герой применяет умение с ограниченным числом использований (ярость, второе дыхание, всплеск действий, ци, "
    "божественный канал, вдохновение барда…): сервер списывает использование или отказывает, если они кончились до "
    "отдыха. Что умение даёт, опиши по его тексту; числа бросков — через обычные инструменты.",
    UseFeatureArgs,
    ids={"character_id": "characters"},
)
async def use_feature(ctx: ToolContext, a: UseFeatureArgs) -> dict:
    ch = ctx.world.characters.get(a.character_id)
    if ch is None or ch.status not in PLAYABLE:
        raise ToolError(f"нет героя в игре {a.character_id}")
    act = ctx.world.actor(ch.id)
    pools = feats.pools_for(ch, ctx.world.catalog, act.mods, act.pb)
    want = a.feature.strip().lower()
    pool = next((p for p in pools if p.key == want or p.name.lower() == want), None)
    if pool is None:
        have = ", ".join(f"{p.key} ({p.name})" for p in pools) or "нет"
        raise ToolError(f"у {ch.name} нет умения «{a.feature}» с ограниченным числом использований; есть: {have}")
    try:
        spent = rules.use(pool, feats.spent_of(ch), a.amount)
    except rules.RestError as e:
        raise ToolError(f"{ch.name}: {e}") from e
    inverse = [snapshot(act)]
    if pool.key == "action_surge":
        inverse += economy.surge(ctx, ch.id)
    ch.resources = {**(ch.resources or {}), "uses_spent": spent}
    ctx.world.invalidate(ch.id)
    left = pool.max - spent[pool.key]
    out = {"character": ch.name, "feature": pool.name, "spent": a.amount, "left": left, "max": pool.max,
           "returns": rules.PER_RU[pool.per]}  # fmt: skip
    await ctx.record("use_feature", actor_id=ch.id, payload=out, inverse=inverse)
    return out


class RestPlaceArgs(BaseModel):
    safety: Literal["safe", "risky", "dangerous"] = Field(
        description="safe — заперта комната в таверне, свой лагерь под охраной; risky — дикая местность; "
        "dangerous — логово, гнездо, рядом рыщут враги"
    )
    location_id: str | None = Field(None, description="место; по умолчанию — место сцены")
    reason: str = Field(min_length=3, max_length=300)


@tool(
    "set_rest_place",
    "Отметить, насколько место годится для отдыха, когда это ясно из мира, а данные места молчат: от отметки "
    "зависят предупреждение отряду и шанс засады во время отдыха.",
    RestPlaceArgs,
    ids={"location_id": "places"},
    closes=False,
)
async def set_rest_place(ctx: ToolContext, a: RestPlaceArgs) -> dict:
    place = a.location_id or ctx.world.home()
    loc = ctx.world.entities.get(place or "")
    if loc is None or loc.kind != "location":
        raise ToolError("нет места в реестре: сначала создайте локацию")
    inverse = [{"table": "entities", "id": loc.id, "field": "state", "before": copy.deepcopy(loc.state)}]
    loc.state = {**(loc.state or {}), "rest_safety": a.safety}
    await ctx.record(
        "set_rest_place", target_id=loc.id, payload={"safety": a.safety, "reason": a.reason}, inverse=inverse
    )
    return {"place": loc.name, "safety": rules.SAFETY_RU[a.safety]}
