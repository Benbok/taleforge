"""Рост героев: опыт и уровни (SRD 5.1, «Advancement»). Числа считает сервер, мастер выбирает только повод.

Кампания растёт одним из двух способов (настройка ``leveling``):
- ``xp`` (по умолчанию) — опыт за побеждённых врагов, задачи и квесты. Опыт делится поровну между живыми героями
  отряда (ИИ-игроки — такие же герои), остаток от деления копится в сцене и уходит в следующую выдачу. Уровень
  растёт сам, как только опыт доходит до порога таблицы SRD.
- ``milestone`` — уровни по вехам сюжета через ``grant_level``, опыт не начисляется.

За убитого врага опыт начисляется сам после любого вызова, который его убил. Сколько давать за задачу и квест,
решает таблица порогов сложности встреч SRD: задача — порог выбранной сложности на каждого героя, квест — вдвое больше.
"""

from __future__ import annotations

import copy
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core.world import PLAYABLE
from app.db.models import Character, ContentPack
from app.rules.dnd5e.advancement import XP_FOR_LEVEL, level_of, next_level_xp, progress_view, xp_of
from app.tools.master import ENCOUNTER_XP, MAX_LEVEL_DEFAULT, _character, engine, snapshot
from app.tools.registry import AFTER_CALL, ToolContext, ToolError, tool

LEVELING = ("xp", "milestone")
DIFFICULTY = {"easy": 0, "medium": 1, "hard": 2, "deadly": 3}  # столбец ENCOUNTER_XP
QUEST_FACTOR = 2  # квест — большая цель; задача — поручение, шаг сюжета
SOURCE_RU = {"defeat": "победа над врагами", "task": "задача", "quest": "квест"}


def leveling(campaign) -> str:
    mode = (campaign.settings or {}).get("leveling")
    return mode if mode in LEVELING else "xp"


async def level_cap(ctx: ToolContext) -> int:
    cap = MAX_LEVEL_DEFAULT
    for pid, ver in ctx.campaign.content_chain or []:
        p = await ctx.session.get(ContentPack, (pid, ver))
        if p and p.manifest.get("level_cap"):
            cap = min(cap, int(p.manifest["level_cap"]))
    return cap


def party(ctx: ToolContext) -> list[Character]:
    """Кто делит опыт: герои в игре, живые (при смерти, но не погибшие — тоже). Павшие опыт не получают."""
    out = []
    for c in ctx.world.characters.values():
        if c.status in PLAYABLE and not ctx.world.actor(c.id).hp.dead:
            out.append(c)
    return out


async def level_up(ctx: ToolContext, ch: Character, reason: str, tool_name: str = "grant_level") -> dict:
    """Один уровень вверх: максимум хитов по SRD, текущие хиты растут на прибавку, плюс кость хитов."""
    act = ctx.world.actor(ch.id)
    level = level_of(ch.sheet)
    inverse = [
        {"table": "characters", "id": ch.id, "field": "sheet", "before": copy.deepcopy(ch.sheet)},
        snapshot(act),
    ]
    old_max = act.hp.maximum
    sheet = {**ch.sheet, "level": level + 1}
    if leveling(ctx.campaign) == "xp":
        sheet["xp"] = max(xp_of(ch.sheet), XP_FOR_LEVEL[level + 1])  # веха в режиме опыта не отстаёт от шкалы
    ch.sheet = sheet
    ctx.world.invalidate(ch.id)
    new = ctx.world.actor(ch.id)
    cls = ctx.world.catalog.find(ch.sheet.get("class_id", ""), "class")
    die = int(str((cls.data if cls else {}).get("hit_die", "d8")).lstrip("d"))
    new_max = engine.hit_points_max(die, new.mods["con"], level + 1)
    res = dict(ch.resources or {})
    res.update(
        {
            "hp_max": new_max,
            "hp": int(res.get("hp", old_max)) + new_max - old_max,
            "hit_dice": int(res.get("hit_dice", level)) + 1,
        }
    )
    ch.resources = res
    ctx.world.invalidate(ch.id)
    await ctx.record(
        tool_name,
        target_id=ch.id,
        payload={"level": level + 1, "reason": reason, "hp_max": new_max},
        inverse=inverse,
    )
    return {"character": ch.name, "level": level + 1, "hp_max": new_max}


async def award(ctx: ToolContext, total: int, source: str, reason: str) -> dict:
    """Делит опыт поровну между героями отряда и поднимает уровень тем, кто дошёл до порога."""
    heroes = party(ctx)
    if not heroes:
        raise ToolError("в отряде нет живых героев: опыт некому выдать")
    sc = ctx.world.scene
    st = dict(sc.state or {})
    pool = int(st.get("xp_pool") or 0)
    share, rest = divmod(total + pool, len(heroes))
    inverse: list[dict] = [
        {"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(sc.state)}
    ]
    st["xp_pool"] = rest
    sc.state = st
    cap = await level_cap(ctx)
    out, levels = [], []
    for ch in heroes:
        inverse.append({"table": "characters", "id": ch.id, "field": "sheet", "before": copy.deepcopy(ch.sheet)})
        xp = xp_of(ch.sheet) + share
        ch.sheet = {**(ch.sheet or {}), "xp": xp}
        ctx.changed.add(ch.id)
        while level_of(ch.sheet) < cap and xp >= XP_FOR_LEVEL[level_of(ch.sheet) + 1]:
            levels.append(await level_up(ctx, ch, f"опыт: {xp}", "level_up"))
        nxt = next_level_xp(level_of(ch.sheet)) if level_of(ch.sheet) < cap else None
        out.append({"character": ch.name, "xp": xp, "level": level_of(ch.sheet), "next_level_xp": nxt})
    result: dict[str, Any] = {
        "source": SOURCE_RU.get(source, source),
        "total": total,
        "each": share,
        "heroes": out,
    }
    if rest:
        result["carried"] = rest  # остаток уйдёт в следующую выдачу
    if levels:
        result["level_up"] = levels
    await ctx.record("award_xp", payload={**result, "kind": source, "reason": reason}, inverse=inverse)
    ctx.outbox.append({"kind": "system", "content": _line(result, [c.name for c in heroes])})
    return result


def _line(result: dict, names: list[str]) -> str:
    """Строка в чат всем за столом: сколько опыта, кому и кто вырос."""
    who = ", ".join(names)
    text = f"Опыт отряду: +{result['total']} ({result['source']}), по {result['each']} каждому: {who}."
    for x in result.get("level_up") or []:
        text += f" {x['character']} достигает {x['level']} уровня!"
    return text


def reward_for(ctx: ToolContext, kind: str, difficulty: str) -> int:
    """Опыт за задачу или квест из таблицы порогов SRD: порог сложности по уровню каждого героя, у квеста — вдвое."""
    col = DIFFICULTY[difficulty]
    total = sum(ENCOUNTER_XP[level_of(c.sheet)][col] for c in party(ctx))
    return total * (QUEST_FACTOR if kind == "quest" else 1)


def creature_xp(ctx: ToolContext, en) -> int:
    rec = ctx.world.catalog.find(en.template_id or "")
    return int(((rec.data if rec else {}) or {}).get("xp") or 0)


async def goal_reached(ctx: ToolContext, kind: str, difficulty: str, reason: str) -> dict | None:
    """Опыт за пройденный узел сюжета или закрытый акт. В режиме вех и без живых героев — ничего."""
    if leveling(ctx.campaign) != "xp" or not party(ctx):
        return None
    total = reward_for(ctx, kind, difficulty)
    return await award(ctx, total, kind, reason) if total else None


async def sweep_defeated(ctx: ToolContext, result: dict) -> None:
    """После вызова: враги, убитые им, приносят опыт отряду. Каждый враг — один раз (отметка xp_awarded)."""
    if leveling(ctx.campaign) != "xp":
        return
    fallen = []
    for en in ctx.world.entities.values():
        st = en.state or {}
        if en.kind != "creature" or not st.get("dead") or st.get("xp_awarded"):
            continue
        if st.get("attitude", "hostile") != "hostile":
            continue
        fallen.append(en)
    if not fallen or not party(ctx):
        return
    total = 0
    for en in fallen:
        en.state = {**(en.state or {}), "xp_awarded": True}
        total += creature_xp(ctx, en)
    if total:
        names = ", ".join(en.name for en in fallen)
        result["xp"] = await award(ctx, total, "defeat", f"повержены: {names}")


AFTER_CALL.append(sweep_defeated)


class AwardXpArgs(BaseModel):
    kind: Literal["quest", "task", "defeat"] = Field(
        description="quest — выполнен квест (большая цель); task — задача или поручение; defeat — враги побеждены "
        "без убийства: сдались, бежали, взяты в плен (убитых сервер считает сам)"
    )
    difficulty: Literal["easy", "medium", "hard", "deadly"] = Field(
        "medium", description="для quest и task: насколько трудно было, как у встреч SRD"
    )
    entity_ids: list[str] = Field(default_factory=list, description="для defeat: побеждённые существа")
    reason: str = Field(min_length=1, max_length=300, description="за что: какой квест, задача или победа")


@tool(
    "award_xp",
    "Опыт отряду за выполненный квест, задачу или побеждённых без убийства врагов. Сколько — считает сервер по "
    "таблицам SRD и делит поровну между живыми героями; уровень растёт сам. За убитых врагов и пройденные узлы "
    "каркаса опыт начисляется автоматически: не вызывай для них.",
    AwardXpArgs,
    ids={"entity_ids": "creatures"},
    closes=False,
)
async def award_xp(ctx: ToolContext, a: AwardXpArgs) -> dict:
    if leveling(ctx.campaign) != "xp":
        raise ToolError("в этой кампании уровни по вехам: опыт не начисляется, уровень выдаёт grant_level")
    if a.kind != "defeat":
        if a.entity_ids:
            raise ToolError("entity_ids — только для defeat")
        return await award(ctx, reward_for(ctx, a.kind, a.difficulty), a.kind, a.reason)
    if not a.entity_ids:
        raise ToolError("для defeat укажите побеждённых существ в entity_ids")
    total = 0
    for eid in dict.fromkeys(a.entity_ids):
        en = ctx.world.entities.get(eid)
        if en is None or en.kind != "creature":
            raise ToolError(f"нет существа {eid}")
        st = en.state or {}
        if st.get("xp_awarded"):
            raise ToolError(f"за {en.name} опыт уже выдан")
        if st.get("attitude", "hostile") != "hostile" and not st.get("fled"):
            raise ToolError(f"{en.name} не враг отряду: за него опыт не дают")
        en.state = {**st, "xp_awarded": True}
        total += creature_xp(ctx, en)
    if not total:
        raise ToolError("у этих существ нет опыта в шаблоне")
    return await award(ctx, total, "defeat", a.reason)


class GrantLevelArgs(BaseModel):
    character_ids: list[str] = Field(min_length=1)
    reason: str = Field(description="сюжетная веха")


@tool(
    "grant_level",
    "Повышение уровня на сюжетной вехе. Потолок — уровень пакета. Хиты растут по SRD. В кампании с опытом уровень "
    "растёт сам: вызывай только по прямому решению владельца.",
    GrantLevelArgs,
    ids={"character_ids": "characters"},
    closes=False,
)
async def grant_level(ctx: ToolContext, a: GrantLevelArgs) -> dict:
    cap = await level_cap(ctx)
    out = []
    for cid in a.character_ids:
        ch = _character(ctx, cid)
        if level_of(ch.sheet) >= cap:
            raise ToolError(f"{ch.name} уже на потолке уровня ({cap})")
        out.append(await level_up(ctx, ch, a.reason))
    return {"levels": out}


PROGRESS_TOOLS = ("award_xp", "grant_level")
__all__ = ["PROGRESS_TOOLS", "XP_FOR_LEVEL", "award", "goal_reached", "leveling", "progress_view"]
