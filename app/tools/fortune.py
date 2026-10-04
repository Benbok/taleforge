"""Случайности мира (просьба Arty 2026-09-29): встречи, события и находки по таблицам пакета.

Мастер бросает сам (``roll_fortune``), когда отряд идёт, ищет, отдыхает или ждёт, а сервер, пока идёт игровое время,
проверяет случайности по расписанию места (``run_watch``: раз в несколько часов, шанс из данных места или таблицы).
Исход — строка таблицы, а не выдумка: таблицы встреч (encounter_table), событий (event_table) и добычи
(loot_table). Исход бывает и плохим: враждебные встречи, беды в таблицах событий и подвох у находки
(таблица событий с ролью find_catch). Находки сервер сразу кладёт в сцену, остальное мастер вводит своими
инструментами по подсказке ``next``: существа — spawn_entity (с бюджетом встречи), проверки — roll_check.
"""

from __future__ import annotations

import copy
import re
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core import standing as sd
from app.core.world import PLAYABLE
from app.rules.dice import DiceError
from app.tools.master import _put_in_scene
from app.tools.registry import ToolContext, ToolError, tool

FORTUNE_TOOLS = ("roll_fortune",)
KINDS = ("encounter", "event", "find")
KIND_RU = {"encounter": "встреча", "event": "событие", "find": "находка"}
TONE_RU = {"boon": "удача", "bane": "беда", "twist": "поворот"}
WATCH_DEFAULT = {"every_hours": 4, "on_d6": [1]}  # как у опорных туш пакета: раз в 4 часа, 1 на d6
WATCH_MAX_CHECKS = 6  # за один ход сервер проверяет не больше суток пути
LOOT_TIERS = ((1, 4, "1-4"), (5, 10, "5-10"), (11, 20, "11-15"))
HOUR = 3600


def random_events(campaign) -> str:
    """Настройка кампании: auto — сервер сам проверяет случайности по игровому времени; manual — только мастер."""
    mode = (campaign.settings or {}).get("random_events")
    return mode if mode in ("auto", "manual") else "auto"


# --- таблицы ---


def _chain(ctx: ToolContext) -> list:
    """Шаблоны текущей локации и её родителей (район → туша → пояс): по ним выбираются таблицы."""
    loc = ctx.world.entities.get(ctx.world.home() or "")
    out, rid = [], loc.template_id if loc else None
    while rid and len(out) < 4:
        rec = ctx.world.catalog.find(rid, "location_template")
        if rec is None or rec in out:
            break
        out.append(rec)
        rid = rec.data.get("parent_ref")
    return out


def _words(chain: list) -> set[str]:
    words: set[str] = set()
    for rec in chain:
        words |= set(rec.data.get("tags") or [])
        for k in ("belt", "location_type"):
            if rec.data.get(k):
                words.add(str(rec.data[k]))
        if rec.data.get("location_type") in ("hulk", "district"):
            words.add("carcass")
    return words


def _belt(chain: list) -> str | None:
    return next((rec.data["belt"] for rec in chain if rec.data.get("belt")), None)


def _candidates(ctx: ToolContext, kind: str) -> list:
    cat = ctx.world.catalog
    if kind == "encounter":
        return [r for r in cat.by_kind("encounter_table") if not r.data.get("wave")]
    if kind == "event":
        return [r for r in cat.by_kind("event_table") if r.data.get("role") != "find_catch"]
    tables = [r for r in cat.by_kind("loot_table") if r.data.get("rows") and _is_dice(r.data.get("dice"))]
    lvl = _party_level(ctx)
    tier = next((t for lo, hi, t in LOOT_TIERS if lo <= lvl <= hi), None)
    same = [r for r in tables if r.data.get("tier") in (None, tier)]
    return same or tables


def _is_dice(v: Any) -> bool:
    return isinstance(v, str) and bool(re.fullmatch(r"\d*d\d+", v.strip()))


def _party_level(ctx: ToolContext) -> int:
    lv = [int((c.sheet or {}).get("level", 1)) for c in ctx.world.characters.values() if c.status in PLAYABLE]
    return round(sum(lv) / len(lv)) if lv else 1


def pick_table(ctx: ToolContext, kind: str, table_id: str | None):
    """Таблица по id или по месту сцены: своя таблица места, затем таблица его пояса, затем общая."""
    tables = _candidates(ctx, kind)
    if table_id:
        rec = next((r for r in tables if r.id == table_id), None)
        if rec is None:
            listed = ", ".join(r.id for r in tables[:20]) or "нет"
            raise ToolError(f"нет таблицы {table_id} для вида «{KIND_RU[kind]}»; есть: {listed}")
        return rec
    if not tables:
        raise ToolError(f"в мире кампании нет таблиц для вида «{KIND_RU[kind]}»")
    chain = _chain(ctx)
    ids = [r.id for r in chain]
    for rid in ids:  # своя таблица места или ближайшего родителя
        rec = next((r for r in tables if r.data.get("location_ref") == rid), None)
        if rec is not None:
            return rec
    belt = _belt(chain)
    if kind == "find":
        words = _words(chain)
        scored = sorted(((len(words & set(r.data.get("tags") or [])), r) for r in tables), key=lambda x: -x[0])
        if scored and scored[0][0] > 0 and (len(scored) == 1 or scored[1][0] < scored[0][0]):
            return scored[0][1]
    else:
        by_belt = [r for r in tables if belt and r.data.get("belt") == belt and not r.data.get("location_ref")]
        if by_belt:
            return by_belt[0]
        general = [r for r in tables if r.data.get("belt") in (None, "any") and not r.data.get("location_ref")]
        if len(general) == 1 or (general and kind == "event"):
            return general[0]
    listed = ", ".join(f"{r.id} ({r.name})" for r in tables[:20])
    raise ToolError(f"по месту сцены таблицу не выбрать: укажите table_id — {listed}")


def _in_range(spec: Any, n: int) -> bool:
    s = str(spec).strip()
    if "-" in s:
        lo, hi = s.split("-", 1)
        return int(lo) <= n <= int(hi)
    return s.isdigit() and int(s) == n


def _roll_row(ctx: ToolContext, rec) -> tuple[int, dict]:
    expr = str(rec.data.get("dice")).strip()
    expr = "1" + expr if expr.startswith("d") else expr
    n = ctx.dice.roll(expr).total
    rows = [r for r in rec.data.get("rows") or [] if isinstance(r, dict) and "roll" in r and not r.get("when")]
    row = next((r for r in rows if _in_range(r["roll"], n)), None)
    if row is None:
        raise ToolError(f"в таблице {rec.id} нет строки для броска {n}")
    return n, row


def _amount(ctx: ToolContext, v: Any) -> int | str:
    """Число из данных: 3, «1d4», «3d6*5»; диапазон «50-200» остаётся текстом для мастера."""
    if isinstance(v, int):
        return v
    s = str(v).replace(" ", "")
    m = re.fullmatch(r"(.+)\*(\d+)", s)
    try:
        if m:
            return ctx.dice.roll(m.group(1)).total * int(m.group(2))
        return ctx.dice.roll(s).total
    except DiceError:
        return str(v)


def _counts(ctx: ToolContext, refs: list[str], count: Any) -> list[int]:
    """«1d6 + 1» у двух шаблонов — по слагаемому на шаблон; у одного — сумма."""
    terms = [t.strip() for t in str(count or "1").split("+")]
    if len(refs) > 1 and len(terms) == len(refs):
        return [max(1, int(_amount(ctx, t) or 1)) for t in terms]
    total = _amount(ctx, str(count or "1"))
    total = total if isinstance(total, int) else 1
    return [max(1, total)] + [1] * (len(refs) - 1) if refs else []


# --- исходы ---


def _creatures(ctx: ToolContext, row: dict, hostile_default: bool, b: dict) -> tuple[list[dict], list[str]]:
    cat = ctx.world.catalog
    refs = [r for r in row.get("creature_refs") or [] if isinstance(r, str)]
    out, nxt = [], []
    for ref, n in zip(refs, _counts(ctx, refs, row.get("count")), strict=False):
        rec = cat.find(ref, "creature_template")
        if rec is None:
            continue
        hostile = bool(row.get("hostile", hostile_default))
        item: dict[str, Any] = {"template": rec.id, "name": rec.name, "count": n}
        attitude = "hostile" if hostile else "neutral"
        fid = rec.data.get("faction_ref")
        if fid:
            t = sd.tier_of(sd.points_of(b, fid))
            fac = cat.find(fid, "faction")
            item["faction"] = fac.name if fac else fid
            item["party_standing"] = sd.tier_label(t)
            if t >= 2 and hostile:
                attitude = "neutral"  # свои не нападают на союзников отряда без приказа
            elif t <= -2 and not hostile:
                attitude = "hostile" if t == -3 else "neutral"
            ready = [r for r in b["responses"] if r["subject_id"] == fid and r["status"] == "ready"]
            if ready:
                item["response"] = f"{ready[0]['id']}: {sd.MOOD_RU[ready[0]['mood']]} — это может быть их ответ"
        item["attitude"] = attitude
        out.append(item)
        nxt.append(f"spawn_entity creature_template_id={rec.id} count={n} attitude={attitude}")
    for ref in row.get("npc_refs") or []:
        rec = cat.find(ref, "creature_template")
        if rec is not None:
            out.append({"template": rec.id, "name": rec.name, "count": 1, "attitude": "neutral", "npc": True})
            nxt.append(f"spawn_entity creature_template_id={rec.id} attitude=neutral")
    for name in row.get("srd_monsters") or []:
        rec = cat.find(f"creature.{str(name).lower().replace(' ', '_')}", "creature_template")
        n = _counts(ctx, ["x"], row.get("count"))[0]
        att = "hostile" if row.get("hostile", hostile_default) else "neutral"
        if rec is not None:
            out.append({"template": rec.id, "name": rec.name, "count": n, "attitude": att})
            nxt.append(f"spawn_entity creature_template_id={rec.id} count={n} attitude={att}")
    return out, nxt


async def _place(ctx: ToolContext, row: dict, inverse: list) -> tuple[list[dict], list[str]]:
    """Предметы строки ложатся в сцену: герои подберут их сами (pick_up_item)."""
    cat = ctx.world.catalog
    refs = [r for r in row.get("item_refs") or [] if isinstance(r, str)]
    qtys = list(row.get("qty") or [])
    pairs = list(zip(refs, qtys + [1] * (len(refs) - len(qtys)), strict=False))
    if row.get("choose") == "one" and pairs:
        pairs = [pairs[ctx.dice.die(len(pairs)) - 1]]
    placed, notes = [], []
    if row.get("by_scenario"):
        return [], ["редкая вещь — только если сценарий разрешает; иначе строка пуста"]
    for ref, q in pairs:
        rec = cat.find(ref, "item_template")
        if rec is None:
            notes.append(f"{ref}: такого предмета нет в мире кампании")
            continue
        qty = _amount(ctx, q)
        qty = qty if isinstance(qty, int) and qty > 0 else 1
        en, inv = await _put_in_scene(ctx, rec.id, None, qty, "near")
        inverse.extend(inv)
        placed.append({"entity_id": en.id, "item": rec.name, "qty": qty})
    return placed, notes


def _check(row: dict) -> tuple[dict | None, list[str]]:
    c = row.get("check")
    if not isinstance(c, dict):
        return None, []
    out = {k: c[k] for k in ("stat", "kind", "dc_ref", "success", "failure") if c.get(k) is not None}
    kind = c.get("kind") or "check"
    return out, [f"roll_check stat={c.get('stat')} kind={kind} difficulty={c.get('dc_ref')}"]


async def _outcome(ctx: ToolContext, kind: str, rec, b: dict, inverse: list, top: bool = True) -> dict:
    n, row = _roll_row(ctx, rec)
    res: dict[str, Any] = {"kind": KIND_RU[kind], "table": rec.name, "roll": n}
    nxt: list[str] = []
    text = row.get("text") or row.get("note")
    if row.get("name"):
        res["name"] = row["name"]
    if text:
        res["text"] = text
    tone = row.get("tone")
    if kind == "encounter" and not tone:
        tone = "bane" if row.get("hostile", True) else "twist"
    if tone:
        res["tone"] = TONE_RU.get(tone, tone)
    creatures, spawn = _creatures(ctx, row, kind == "encounter", b)
    if creatures:
        res["creatures"] = creatures
        nxt += spawn
    placed, notes = await _place(ctx, row, inverse)
    if placed:
        res["placed_in_scene"] = placed
    if row.get("fk") is not None:
        res["fk"] = _amount(ctx, row["fk"])
    check, how = _check(row)
    if check:
        res["check"] = check
        nxt += how
    for key, tool_name in (("hazard_ref", "apply_hazard"), ("effect_ref", "apply_effect")):
        if row.get(key):
            res[key.removesuffix("_ref")] = row[key]
            nxt.append(f"{tool_name} {row[key]}" + (" (если проверка провалена)" if check else ""))
    loot = row.get("loot_ref")
    if loot:
        lrec = ctx.world.catalog.find(loot, "loot_table")
        if lrec is not None:
            res["find"] = await _outcome(ctx, "find", lrec, b, inverse, top=False)
    if kind == "find" and top:
        catch = next((r for r in ctx.world.catalog.by_kind("event_table") if r.data.get("role") == "find_catch"), None)
        if catch is not None:
            res["catch"] = await _outcome(ctx, "event", catch, b, inverse, top=False)
    for k in ("reveal_knowledge", "lead_item_ref", "npc"):
        if row.get(k):
            notes.append(f"{k}: {row[k]}")
    if notes:
        res["notes"] = notes
    if nxt:
        res["next"] = nxt
    return res


def _pick_kind(ctx: ToolContext, kind: str) -> str:
    if kind != "any":
        return kind
    d = ctx.dice.die(6)
    order = ["encounter", "event", "find"] if d <= 3 else ["event", "encounter", "find"] if d <= 5 else ["find"]
    for k in [*order, *KINDS]:
        if _candidates(ctx, k):
            return k
    raise ToolError("в мире кампании нет таблиц случайностей")


async def roll(ctx: ToolContext, kind: str, table_id: str | None, reason: str, tool_name: str) -> dict:
    kind = _pick_kind(ctx, kind)
    rec = pick_table(ctx, kind, table_id)
    b = sd.book(ctx.world.scene.state)
    inverse: list = []
    res = await _outcome(ctx, kind, rec, b, inverse)
    await ctx.record(tool_name, payload={**res, "reason": reason, "table_id": rec.id}, inverse=inverse, hidden=True)
    return res


class FortuneArgs(BaseModel):
    kind: Literal["encounter", "event", "find", "any"] = Field(
        description="encounter — кто-то появляется; event — что-то случается; find — находка при обыске; "
        "any — пусть решит кубик"
    )
    table_id: str | None = Field(None, description="таблица пакета; по умолчанию — таблица места сцены")
    reason: str = Field(min_length=3, max_length=300, description="что делают герои: идут, обыскивают, ночуют")


@tool(
    "roll_fortune",
    "Случайность по таблицам мира: встреча, событие или находка. Исход бывает любым, и плохим тоже: враги, беда, "
    "подвох у находки. Бросай, когда отряд идёт, ищет, отдыхает или медлит в опасном месте, а не на каждом шагу. "
    "Находки сервер кладёт в сцену сам; существ, проверки и опасности введи по списку next.",
    FortuneArgs,
    closes=False,
)
async def roll_fortune(ctx: ToolContext, a: FortuneArgs) -> dict:
    return await roll(ctx, a.kind, a.table_id, a.reason, "roll_fortune")


# --- расписание ---


def _watch_rule(ctx: ToolContext) -> dict:
    for rec in _chain(ctx):
        if isinstance(rec.data.get("encounter_check"), dict):
            return rec.data["encounter_check"]
    try:
        t = pick_table(ctx, "encounter", None)
    except ToolError:
        return WATCH_DEFAULT
    return t.data.get("check") if isinstance(t.data.get("check"), dict) else WATCH_DEFAULT


def summary(res: dict) -> str:
    parts = [f"{res['kind']} ({res.get('tone', '—')}), бросок {res['roll']} по таблице «{res['table']}»"]
    if res.get("name"):
        parts.append(str(res["name"]))
    if res.get("text"):
        parts.append(str(res["text"]))
    if res.get("creatures"):
        parts.append("кто: " + ", ".join(f"{c['name']} ×{c['count']} ({c['attitude']})" for c in res["creatures"]))
    if res.get("placed_in_scene"):
        parts.append("в сцене: " + ", ".join(f"{p['item']} ×{p['qty']}" for p in res["placed_in_scene"]))
    if res.get("catch"):
        parts.append("подвох: " + summary(res["catch"]))
    if res.get("next"):
        parts.append("сделай: " + "; ".join(res["next"]))
    return ". ".join(parts)


async def run_watch(ctx: ToolContext) -> str:
    """Пока шло игровое время, мир не стоял: раз в несколько часов сервер проверяет случайность по правилу места.
    Не больше одной случайности за ход, в бою — никогда. Возвращает подсказку мастеру для фазы решения."""
    if random_events(ctx.campaign) != "auto" or ctx.world.in_fight():
        return ""
    if not (_candidates(ctx, "encounter") or _candidates(ctx, "event")):
        return ""
    sc = ctx.world.scene
    now = int(sc.game_time)
    st = dict(sc.state or {})
    fs = dict(st.get("fortune") or {})
    if "checked_at" not in fs:
        sc.state = {**st, "fortune": {**fs, "checked_at": now}}
        return ""
    rule = _watch_rule(ctx)
    every = max(1, int(rule.get("every_hours") or WATCH_DEFAULT["every_hours"])) * HOUR
    hits = [int(x) for x in rule.get("on_d6") or WATCH_DEFAULT["on_d6"]]
    periods = (now - int(fs["checked_at"])) // every
    if periods <= 0:
        return ""
    before = copy.deepcopy(sc.state)
    fs["checked_at"] = int(fs["checked_at"]) + periods * every
    sc.state = {**st, "fortune": fs}
    if not any(ctx.dice.die(6) in hits for _ in range(min(periods, WATCH_MAX_CHECKS))):
        return ""
    try:
        res = await roll(ctx, "any", None, "время шло: случайность по расписанию места", "fortune_watch")
    except ToolError:
        sc.state = {**(sc.state or {}), "fortune": fs}
        return ""
    ctx.events[-1].inverse = [
        {"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": before},
        *ctx.events[-1].inverse,
    ]
    return (
        "Случайность (сервер бросил по расписанию места, пока шло время): " + summary(res) + ". Введи её в сцену "
        "в этом ходу, если это правдоподобно, или сразу после действий игроков.\n\n"
    )
