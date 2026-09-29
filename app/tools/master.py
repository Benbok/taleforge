"""Инструменты мастера (ТЗ, разделы 7, 7.1, 7.2, 8.1). Числа считает движок правил, мастер передаёт только
шаблоны, цели и параметры из данных. Каждый изменяющий вызов оставляет событие в журнале с обратной дельтой.

Не вошли в этап 3: ``lookup_rules`` (поиск по фрагментам правил — этап «Память»), ``cast_spell`` (механика
заклинаний), автоматический ход монстров по профилю поведения и очередь хода (этап 4).
"""

from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core import audio, combat
from app.core.campaigns import master_seat
from app.core.world import PLAYABLE, ZONE_FT, ZONE_NAMES, Actor, WorldError, format_time, lineage_features
from app.db.models import ActiveEffect, Character, Entity, InventoryItem, Knowledge, KnownFact
from app.rules.base import RollMode
from app.rules.dnd5e import modifiers as mod
from app.rules.dnd5e.engine import Dnd5eEngine
from app.rules.dnd5e.tables import ABILITIES, SKILLS
from app.tools import effects as fx
from app.tools.registry import ToolContext, ToolError, dice_json, tool

engine = Dnd5eEngine()
Zone = Literal["melee", "near", "far"]
HIDDEN_SKILLS_DEFAULT = ("perception", "insight", "stealth")
MAX_LEVEL_DEFAULT = 20


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


# --- чтение ---


class NoArgs(BaseModel):
    pass


@tool("get_scene", "Сцена: сущности с id, хиты, зоны, эффекты, режим и игровое время.", NoArgs, mutating=False)
async def get_scene(ctx: ToolContext, a: NoArgs) -> dict:
    return {"scene": ctx.world.scene_table()}


class CharacterArg(BaseModel):
    character_id: str


@tool(
    "get_character",
    "Актуальный лист персонажа: характеристики, навыки, атаки, хиты, эффекты, снаряжение.",
    CharacterArg,
    mutating=False,
    ids={"character_id": "characters"},
    closes=False,
)
async def get_character(ctx: ToolContext, a: CharacterArg) -> dict:
    ch = _character(ctx, a.character_id)
    act = ctx.world.actor(ch.id)
    return {
        "id": ch.id,
        "name": ch.name,
        "class": (ch.sheet or {}).get("class_id"),
        "origin": (ch.sheet or {}).get("origin_id"),
        "lineage": (ch.sheet or {}).get("lineage_id"),
        "lineage_caste": (ch.sheet or {}).get("lineage_caste"),
        "level": (ch.sheet or {}).get("level", 1),
        "status": act.status(),
        "ac": act.ac,
        "abilities": act.abilities,
        "saves": act.saves,
        "skills": act.skills,
        "attacks": act.attacks,
        "effects": [{"id": e.id, "template": r.id, "name": r.name, "stacks": e.stacks} for e, r in act.effects],
        "inventory": [
            {
                "id": it.id,
                "item": it.item_template_id,
                "name": ctx.world.item_name(it),
                "qty": it.qty,
                "equipped": it.equipped,
            }
            for it in ctx.world.inventory.get(ch.id, [])
        ],
        "personality": ch.personality,
        "public_bio": ch.public_bio,
    }


class ThresholdArgs(BaseModel):
    character_id: str
    lineage_id: str = Field(description="вторая раса из данных пакета (kind lineage), например lineage.kept_self")
    caste: str = Field(description="id касты из поля castes этой расы: игрок выбирает её сам")
    variant: str | None = Field(None, description="исход испытания из поля variants, если оно есть у расы")


@tool(
    "cross_threshold",
    "Герой прошёл испытание Порога, сохранив личность: получает вторую расу пакета поверх человеческого "
    "происхождения и выбранную игроком касту. Класс, уровень, характеристики и черты происхождения остаются. "
    "Вызывай только по итогу испытания из правил пакета, не по просьбе игрока.",
    ThresholdArgs,
    ids={"character_id": "characters"},
)
async def cross_threshold(ctx: ToolContext, a: ThresholdArgs) -> dict:
    ch = _character(ctx, a.character_id)
    lin = ctx.world.catalog.find(a.lineage_id, "lineage")
    if lin is None:
        raise ToolError(f"в мире кампании нет второй расы {a.lineage_id}")
    sheet = ch.sheet or {}
    if sheet.get("lineage_id"):
        raise ToolError(f"{ch.name} уже прошёл Порог")
    castes = {c.get("id"): c for c in lin.data.get("castes") or []}
    if castes and a.caste not in castes:
        raise ToolError(f"у расы {lin.name} нет касты {a.caste}: есть {', '.join(castes)}")
    variants = {v.get("id") for v in lin.data.get("variants") or []}
    if a.variant and a.variant not in variants:
        raise ToolError(f"у расы {lin.name} нет исхода {a.variant}")
    inverse = [
        {"table": "characters", "id": ch.id, "field": "sheet", "before": copy.deepcopy(sheet)},
        {"table": "characters", "id": ch.id, "field": "resources", "before": copy.deepcopy(ch.resources)},
    ]
    new = {**sheet, "lineage_id": lin.id, "lineage_caste": a.caste if castes else None}
    if a.variant:
        new["lineage_variant"] = a.variant
    ch.sheet = new
    # шкалы, которые форма обнуляет (op set со значением-числом у ресурса пакета): Скверна, Перемена, зависимость
    res = copy.deepcopy(ch.resources or {})
    stats = dict(res.get("stats") or {})
    _, caste, feats = lineage_features(new, ctx.world.catalog)
    for f in feats:
        for m in f.get("modifiers") or []:
            tgt = m.get("target")
            if m.get("op") == "set" and isinstance(m.get("value"), int) and ctx.world.catalog.find(f"stat.{tgt}"):
                stats[tgt] = m["value"]
    res["stats"] = stats
    ch.resources = res
    result = {
        "character": ch.name,
        "lineage": lin.name,
        "caste": (caste or {}).get("name"),
        "features": [f.get("name") for f in feats],
    }
    await ctx.record("cross_threshold", target_id=ch.id, payload=result, inverse=inverse)
    return result


TemplateKind = Literal[
    "creature_template",
    "item_template",
    "effect_template",
    "hazard_template",
    "location_template",
    "dc_scale",
    "faction",
    "lore_fact",
    "class",
    "origin",
    "lineage",
]


class LookupArgs(BaseModel):
    kind: TemplateKind
    query: str = Field("", description="слова для поиска: название, тег, английское имя SRD")


@tool(
    "lookup_template",
    "Поиск шаблонов в данных кампании. Предмет, существо, эффект или опасность можно создать только из шаблона.",
    LookupArgs,
    mutating=False,
)
async def lookup_template(ctx: ToolContext, a: LookupArgs) -> dict:
    found = ctx.world.catalog.search(a.kind, a.query, limit=8)
    out = []
    for e in found:
        d = e.data
        item = {"id": e.id, "name": e.name}
        for k in ("description", "cr", "category", "value", "ac", "tags", "duration"):
            if d.get(k) not in (None, "", []):
                item[k] = d[k] if k != "description" else str(d[k])[:240]
        if d.get("castes"):  # вторая раса: мастеру нужны касты и исходы, чтобы провести Порог
            item["castes"] = [{"id": c.get("id"), "name": c.get("name")} for c in d["castes"]]
            item["variants"] = [v.get("id") for v in d.get("variants") or []]
        out.append(item)
    return {"results": out, "note": "" if out else "ничего не найдено: такого в мире нет"}


# --- проверки и бой ---


class CheckArgs(BaseModel):
    character_id: str = Field(description="кто бросает: персонаж или существо в сцене")
    stat: str = Field(description=f"навык ({', '.join(SKILLS)}) или характеристика ({', '.join(ABILITIES)})")
    kind: Literal["check", "save"] = "check"
    difficulty: str = Field(
        description="id записи шкалы сложностей (dc.*) или id сущности, у которой сложность задана в шаблоне"
    )
    reason: str = Field(description="что проверяется, для журнала")


@tool(
    "roll_check",
    "Проверка навыка или характеристики или спасбросок против сложности из данных. Скрытые проверки "
    "(внимательность, проницательность, скрытность) игрок не видит — сообщи только последствия.",
    CheckArgs,
    ids={"character_id": "combatants", "difficulty": "dc"},
)
async def roll_check(ctx: ToolContext, a: CheckArgs) -> dict:
    act = ctx.world.actor(a.character_id)
    _alive(act, "Бросающий")
    dc = _difficulty(ctx, a.difficulty)
    if a.kind == "save":
        if a.stat not in ABILITIES:
            raise ToolError(f"спасбросок делается по характеристике: {', '.join(ABILITIES)}")
        bonus, ability = act.saves[a.stat], a.stat
    else:
        bonus, ability = act.ability_check_bonus(a.stat)
    mode, reasons = mod.roll_mode(act.modifiers, a.kind, ability, a.stat if a.stat in SKILLS else None)
    auto = mod.save_auto_fail(act.modifiers, ability) if a.kind == "save" else None
    res = (engine.saving_throw if a.kind == "save" else engine.check)(ctx.dice, bonus, dc, mode)
    success = res.success and auto is None
    hidden = a.kind == "check" and a.stat in _hidden_skills(ctx)
    result = {
        "who": act.name,
        "stat": a.stat,
        "kind": a.kind,
        "dc": dc,
        "total": res.roll.total,
        "success": success,
        "margin": res.margin,
        "hidden": hidden,
    }
    if reasons:
        result["reasons"] = reasons
    if auto:
        result["auto_fail"] = auto
    await ctx.record(
        "roll_check",
        actor_id=act.id,
        payload={"reason": a.reason, **result},
        dice=[dice_json(res.roll)],
        hidden=hidden,
    )
    return result


def _difficulty(ctx: ToolContext, ref: str) -> int:
    scale = {e.id: int(e.data["value"]) for e in ctx.world.catalog.dc_scale()}
    if ref in scale:
        return scale[ref]
    en = ctx.world.entities.get(ref)
    if en is not None:
        dc = (en.state or {}).get("dc")
        if dc is None and en.template_id:
            rec = ctx.world.catalog.find(en.template_id)
            dc = rec.data.get("dc") if rec else None
        if isinstance(dc, dict):
            dc = dc.get("value")
        if isinstance(dc, int):
            return dc
        raise ToolError(f"у {en.name} нет сложности в шаблоне; возьмите запись шкалы: {', '.join(scale)}")
    raise ToolError(f"сложность только из данных: {', '.join(scale)} или сущность со сложностью в шаблоне")


class AttackArgs(BaseModel):
    attacker_id: str = Field(description="атакующий: персонаж или существо")
    target_id: str
    attack: str = Field(description="ключ атаки из листа: id предмета инвентаря, ключ оружия или действия существа")


@tool(
    "resolve_attack",
    "Атака оружием или природным оружием: бросок попадания, урон по шаблону, списание хитов. Числа — только сервер.",
    AttackArgs,
    ids={"attacker_id": "combatants", "target_id": "combatants"},
)
async def resolve_attack(ctx: ToolContext, a: AttackArgs) -> dict:
    w = ctx.world
    att, tgt = w.actor(a.attacker_id), w.actor(a.target_id)
    if att.id == tgt.id:
        raise ToolError("атаковать себя нельзя")
    _alive(att, "Атакующий")
    _alive(tgt, "Цель")
    if att.kind == "character" and att.hp.current == 0:
        raise ToolError(f"{att.name} без сознания и не может атаковать")
    blocked = mod.can_act(att.modifiers)
    if blocked:
        raise ToolError(f"{att.name} не может действовать: {blocked}")
    weapon = next((x for x in att.attacks if a.attack in (x.get("key"), x.get("inventory_id"), x.get("name"))), None)
    if weapon is None:
        opts = ", ".join(f"{x.get('inventory_id') or x['key']} ({x['name']})" for x in att.attacks)
        raise ToolError(f"у {att.name} нет атаки {a.attack}; доступно: {opts}")

    dist = w.distance_ft(att, tgt)
    extra = []
    if weapon["kind"] == "melee" and dist > int(weapon.get("reach_ft") or 5) and weapon.get("normal_ft"):
        weapon = {**weapon, "kind": "ranged"}  # метательное оружие (дротик, копьё) бросают издалека
    if weapon["kind"] == "melee":
        if dist > int(weapon.get("reach_ft") or 5):
            raise ToolError(
                f"{tgt.name} {ZONE_NAMES.get(tgt.zone if tgt.kind != 'character' else att.zone, 'далеко')}: "
                "для рукопашной атаки нужно сблизиться (update_entity zone=melee или move)"
            )
    else:
        long_ft = weapon.get("long_ft") or weapon.get("normal_ft")
        normal = weapon.get("normal_ft")
        if long_ft and dist > int(long_ft):
            raise ToolError(f"{tgt.name} вне дальности {weapon['name']} ({long_ft} футов)")
        if normal and dist > int(normal):
            extra.append("помеха: дальше обычной дистанции")
        if dist <= 5:
            extra.append("помеха: дальняя атака вплотную к врагу")
    am = mod.attack_mods(att.modifiers, tgt.modifiers, dist, extra)
    roll = engine.attack(ctx.dice, int(weapon["attack_bonus"]) + am.bonus, tgt.ac, am.mode)
    critical = roll.critical or (roll.hit and am.auto_crit)
    result: dict = {
        "attacker": att.name,
        "target": tgt.name,
        "attack": weapon["name"],
        "roll": roll.roll.total,
        "natural": roll.roll.natural,
        "target_ac": tgt.ac,
        "hit": roll.hit,
        "critical": critical,
        "mode": str(am.mode),
    }
    if am.reasons:
        result["reasons"] = list(am.reasons)
    dice = [dice_json(roll.roll)]
    inverse = [snapshot(tgt)]
    if roll.hit:
        o, droll = fx.damage_to(tgt, weapon["damage"], weapon["damage_type"], critical, ctx.dice)
        dice.append(droll)
        result.update({"damage": o["damage"], "damage_type": o["damage_type"], "target_status": o["status"]})
        for k in ("instant_death", "death_save_failures_added", "defenses"):
            if o.get(k):
                result[k] = o[k]
        for extra_dmg in weapon.get("extra_damage") or []:
            if not tgt.alive:
                break
            o2, r2 = fx.damage_to(tgt, extra_dmg["dice"], extra_dmg["type"], critical, ctx.dice)
            dice.append(r2)
            result["damage"] += o2["damage"]
            result["target_status"] = o2["status"]
        if tgt.hp.dead:
            result["killed"] = True
    await ctx.record("resolve_attack", actor_id=att.id, target_id=tgt.id, payload=result, dice=dice, inverse=inverse)
    w.invalidate(tgt.id)
    return result


class DeathSaveArgs(BaseModel):
    character_id: str


@tool(
    "death_save",
    "Спасбросок от смерти героя при 0 хитов, в начале его хода. Три успеха — стабилен, три провала — смерть.",
    DeathSaveArgs,
    ids={"character_id": "characters"},
)
async def death_save(ctx: ToolContext, a: DeathSaveArgs) -> dict:
    act = ctx.world.actor(a.character_id)
    if not act.hp.dying:
        raise ToolError(f"{act.name} не при смерти: спасбросок не нужен")
    inv = [snapshot(act)]
    res = engine.death_save(ctx.dice, act.hp)
    act.save_hp()
    result = {
        "who": act.name,
        "natural": res.roll.natural,
        "successes": res.saves.successes,
        "failures": res.saves.failures,
        "stable": res.saves.stable,
        "dead": act.hp.dead,
        "regained_hp": res.regained_hp,
    }
    await ctx.record("death_save", target_id=act.id, payload=result, dice=[dice_json(res.roll)], inverse=inv)
    ctx.world.invalidate(act.id)
    return result


class HazardArgs(BaseModel):
    target_id: str
    hazard_template_id: str
    height_ft: int | None = Field(None, ge=0, le=1000, description="высота падения, если опасность — падение")


@tool(
    "apply_hazard",
    "Урон и последствия от среды по шаблону опасности (падение, яд, огонь). Урон считает формула шаблона.",
    HazardArgs,
    ids={"target_id": "combatants", "hazard_template_id": "templates:hazard_template"},
)
async def apply_hazard(ctx: ToolContext, a: HazardArgs) -> dict:
    rec = ctx.world.catalog.get(a.hazard_template_id, "hazard_template")
    tgt = ctx.world.actor(a.target_id)
    _alive(tgt, "Цель")
    params = {"height_ft": a.height_ft} if a.height_ft is not None else {}
    for p in rec.data.get("params_schema") or {}:
        if p not in params:
            raise ToolError(f"опасности {rec.name} нужен параметр {p}")
    inv = [snapshot(tgt)]
    out = await fx.run_ops(ctx, rec.id, rec.data.get("modifiers") or [], tgt, params)
    result = {"hazard": rec.name, "target": tgt.name, **out, "target_status": ctx.world.actor(tgt.id).status()}
    dice = result.pop("dice")
    await ctx.record("apply_hazard", target_id=tgt.id, payload={**result, "hazard_id": rec.id}, dice=dice, inverse=inv)
    return result


class EffectArgs(BaseModel):
    target_id: str
    effect_template_id: str = Field(description="шаблон эффекта или состояния, например condition.prone")
    duration_value: int | None = Field(None, ge=1, le=1000)
    duration_unit: Literal["round", "minute", "hour", "day"] | None = None


@tool(
    "apply_effect",
    "Накладывает эффект или состояние из шаблона. Без длительности — длительность шаблона или пока не снимут.",
    EffectArgs,
    ids={"target_id": "combatants"},
)
async def apply_effect(ctx: ToolContext, a: EffectArgs) -> dict:
    rec = ctx.world.catalog.get(a.effect_template_id, "effect_template")
    tgt = ctx.world.actor(a.target_id)
    dur = (
        fx.duration_seconds({"unit": a.duration_unit, "value": a.duration_value or 1})
        if a.duration_unit
        else fx.duration_seconds(rec.data.get("duration") or rec.data.get("default_duration"))
    )
    eff, note = await fx.add_effect(ctx, tgt, rec, dur)
    result = {"target": tgt.name, "effect": rec.name, "note": note}
    if eff is not None:
        result["effect_id"] = eff.id
        if eff.expires_at is not None:
            result["until"] = format_time(eff.expires_at)
    inverse = [{"table": "active_effects", "op": "delete", "id": eff.id}] if eff is not None else []
    ev = await ctx.record("apply_effect", target_id=tgt.id, payload=result, inverse=inverse)
    if eff is not None and eff.source_event_id is None:
        eff.source_event_id = ev.id
    return result


class RemoveEffectArgs(BaseModel):
    target_id: str
    effect_id: str = Field(description="id наложенного эффекта (ef_…) или id его шаблона")


@tool("remove_effect", "Снимает наложенный эффект.", RemoveEffectArgs, ids={"target_id": "combatants"})
async def remove_effect(ctx: ToolContext, a: RemoveEffectArgs) -> dict:
    tgt = ctx.world.actor(a.target_id)
    before = next((e for e, r in tgt.effects if a.effect_id in (e.id, r.id)), None)
    if before is None:
        have = ", ".join(f"{e.id} ({r.name})" for e, r in tgt.effects) or "нет эффектов"
        raise ToolError(f"на {tgt.name} нет эффекта {a.effect_id}; есть: {have}")
    row = {
        "id": before.id,
        "effect_template_id": before.effect_template_id,
        "stacks": before.stacks,
        "expires_at": before.expires_at,
        "target_id": before.target_id,
    }
    await fx.remove_effect(ctx, tgt, a.effect_id)
    result = {"target": tgt.name, "removed": row["effect_template_id"]}
    await ctx.record(
        "remove_effect",
        target_id=tgt.id,
        payload=result,
        inverse=[{"table": "active_effects", "op": "restore", "row": row}],
    )
    return result


# --- предметы ---


class UseItemArgs(BaseModel):
    character_id: str
    inventory_id: str
    target_id: str | None = Field(None, description="на кого применить; по умолчанию на себя")


@tool(
    "use_item",
    "Применяет предмет инвентаря по его шаблону (зелье, расходник). Оружие — через resolve_attack.",
    UseItemArgs,
    ids={"character_id": "characters", "inventory_id": "inventory", "target_id": "combatants"},
)
async def use_item(ctx: ToolContext, a: UseItemArgs) -> dict:
    ch = _character(ctx, a.character_id)
    it = next((i for i in ctx.world.inventory.get(ch.id, []) if i.id == a.inventory_id), None)
    if it is None:
        raise ToolError(f"у {ch.name} нет предмета {a.inventory_id}: рука нащупывает пустоту")
    rec = ctx.world.catalog.get(it.item_template_id, "item_template")
    ops = rec.data.get("modifiers") or rec.data.get("use") or []
    if not ops:
        raise ToolError(f"у предмета {rec.name} нет механики применения")
    tgt = ctx.world.actor(a.target_id or ch.id)
    _alive(tgt, "Цель")
    inv = [snapshot(tgt), {"table": "inventory", "id": it.id, "field": "qty", "before": it.qty}]
    out = await fx.run_ops(ctx, rec.id, ops, tgt, {})
    consumed = rec.data.get("category") == "consumable" or bool(rec.data.get("consumable"))
    if consumed:
        it.qty -= 1
        if it.qty <= 0:
            await ctx.session.delete(it)
            ctx.world.inventory[ch.id].remove(it)
    dice = out.pop("dice")
    result = {
        "user": ch.name,
        "item": ctx.world.item_name(it),
        "target": tgt.name,
        **out,
        "consumed": consumed,
        "target_status": ctx.world.actor(tgt.id).status(),
    }
    await ctx.record("use_item", actor_id=ch.id, target_id=tgt.id, payload=result, dice=dice, inverse=inv)
    return result


class GiveItemArgs(BaseModel):
    character_id: str
    item_template_id: str
    qty: int = Field(1, ge=1, le=100)
    display_name: str | None = Field(None, max_length=128, description="имя предмета в мире; свойства — из шаблона")
    reason: str = Field(description="откуда предмет: добыча, покупка, награда")


@tool(
    "give_item",
    "Выдаёт предмет из шаблона в инвентарь персонажа. Несуществующий шаблон — ошибка.",
    GiveItemArgs,
    ids={"character_id": "characters"},
)
async def give_item(ctx: ToolContext, a: GiveItemArgs) -> dict:
    ch = _character(ctx, a.character_id)
    rec = ctx.world.catalog.get(a.item_template_id, "item_template")
    items = ctx.world.inventory.setdefault(ch.id, [])
    same = next(
        (i for i in items if i.item_template_id == rec.id and i.display_name == a.display_name and not i.equipped),
        None,
    )
    if same is not None:
        before = same.qty
        same.qty += a.qty
        inverse = [{"table": "inventory", "id": same.id, "field": "qty", "before": before}]
        inv_id = same.id
    else:
        row = InventoryItem(character_id=ch.id, item_template_id=rec.id, display_name=a.display_name, qty=a.qty)
        ctx.session.add(row)
        await ctx.session.flush()
        items.append(row)
        inverse = [{"table": "inventory", "op": "delete", "id": row.id}]
        inv_id = row.id
    ctx.world.invalidate(ch.id)
    result = {"character": ch.name, "item": a.display_name or rec.name, "qty": a.qty, "inventory_id": inv_id}
    await ctx.record(
        "give_item", target_id=ch.id, payload={**result, "reason": a.reason, "template": rec.id}, inverse=inverse
    )
    return result


class TakeItemArgs(BaseModel):
    character_id: str
    inventory_id: str
    qty: int = Field(1, ge=1, le=100)
    reason: str


@tool(
    "take_item",
    "Забирает предмет из инвентаря персонажа.",
    TakeItemArgs,
    ids={"character_id": "characters", "inventory_id": "inventory"},
)
async def take_item(ctx: ToolContext, a: TakeItemArgs) -> dict:
    ch = _character(ctx, a.character_id)
    it = next((i for i in ctx.world.inventory.get(ch.id, []) if i.id == a.inventory_id), None)
    if it is None:
        raise ToolError(f"у {ch.name} нет предмета {a.inventory_id}")
    if a.qty > it.qty:
        raise ToolError(f"у {ch.name} только {it.qty} шт.")
    name = ctx.world.item_name(it)
    inverse = [
        {
            "table": "inventory",
            "id": it.id,
            "field": "qty",
            "before": it.qty,
            "row": {
                "character_id": ch.id,
                "item_template_id": it.item_template_id,
                "display_name": it.display_name,
                "equipped": it.equipped,
            },
        }
    ]
    it.qty -= a.qty
    if it.qty == 0:
        await ctx.session.delete(it)
        ctx.world.inventory[ch.id].remove(it)
    ctx.world.invalidate(ch.id)
    result = {"character": ch.name, "item": name, "qty": a.qty}
    await ctx.record("take_item", target_id=ch.id, payload={**result, "reason": a.reason}, inverse=inverse)
    return result


class EquipArgs(BaseModel):
    character_id: str
    inventory_id: str
    equipped: bool = True


@tool(
    "equip_item",
    "Надевает или снимает доспех, щит, берёт оружие в руки.",
    EquipArgs,
    ids={"character_id": "characters", "inventory_id": "inventory"},
)
async def equip_item(ctx: ToolContext, a: EquipArgs) -> dict:
    ch = _character(ctx, a.character_id)
    it = next((i for i in ctx.world.inventory.get(ch.id, []) if i.id == a.inventory_id), None)
    if it is None:
        raise ToolError(f"у {ch.name} нет предмета {a.inventory_id}")
    rec = ctx.world.catalog.get(it.item_template_id, "item_template")
    inverse = [{"table": "inventory", "id": it.id, "field": "equipped", "before": it.equipped}]
    if a.equipped and rec.data.get("category") == "armor":
        kind = rec.data.get("armor_type")
        for other in ctx.world.inventory.get(ch.id, []):
            o = ctx.world.catalog.find(other.item_template_id)
            if other is not it and other.equipped and o and o.data.get("category") == "armor":
                if (o.data.get("armor_type") == "shield") == (kind == "shield"):
                    inverse.append({"table": "inventory", "id": other.id, "field": "equipped", "before": True})
                    other.equipped = False
    it.equipped = a.equipped
    ctx.world.invalidate(ch.id)
    act = ctx.world.actor(ch.id)
    result = {"character": ch.name, "item": ctx.world.item_name(it), "equipped": a.equipped, "ac": act.ac}
    await ctx.record("equip_item", target_id=ch.id, payload=result, inverse=inverse)
    return result


# --- реестр мира ---

ENCOUNTER_XP = {  # SRD 5.1: пороги опыта на персонажа (лёгкая, средняя, трудная, смертельная)
    1: (25, 50, 75, 100),
    2: (50, 100, 150, 200),
    3: (75, 150, 225, 400),
    4: (125, 250, 375, 500),
    5: (250, 500, 750, 1100),
    6: (300, 600, 900, 1400),
    7: (350, 750, 1100, 1700),
    8: (450, 900, 1400, 2100),
    9: (550, 1100, 1600, 2400),
    10: (600, 1200, 1900, 2800),
    11: (800, 1600, 2400, 3600),
    12: (1000, 2000, 3000, 4500),
    13: (1100, 2200, 3400, 5100),
    14: (1250, 2500, 3800, 5700),
    15: (1400, 2800, 4300, 6400),
    16: (1600, 3200, 4800, 7200),
    17: (2000, 3900, 5900, 8800),
    18: (2100, 4200, 6300, 9500),
    19: (2400, 4900, 7300, 10900),
    20: (2800, 5700, 8500, 12700),
}
MULTIPLIERS = (1, 1.5, 2, 2.5, 3, 4)
# Сложность кампании → потолок встречи: какой порог SRD нельзя превышать (индекс в ENCOUNTER_XP) и множитель
DIFFICULTY_CAP = {"easy": (1, 1.0), "normal": (2, 1.0), "hard": (3, 1.0), "deadly": (3, 1.5)}


def _multiplier(count: int, party: int) -> float:
    idx = 0 if count <= 1 else 1 if count == 2 else 2 if count <= 6 else 3 if count <= 10 else 4 if count <= 14 else 5
    if party < 3:
        idx = min(idx + 1, len(MULTIPLIERS) - 1)
    elif party >= 6:
        idx = max(idx - 1, 0)
    return MULTIPLIERS[idx]


def encounter_budget(ctx: ToolContext, adding: list[dict]) -> dict:
    """Бюджет встречи SRD: опыт враждебных существ с множителем против порога отряда (раздел 8.1)."""
    party = [c for c in ctx.world.characters.values() if c.status in PLAYABLE]
    if not party:
        return {"ok": True, "note": "в игре нет героев"}
    cap_idx, factor = DIFFICULTY_CAP.get(ctx.campaign.difficulty, (2, 1.0))
    cap = sum(ENCOUNTER_XP[max(1, min(20, int((c.sheet or {}).get("level", 1))))][cap_idx] for c in party) * factor
    xp = [x for x in adding]
    for en in ctx.world.in_scene_entities():
        st = en.state or {}
        if en.kind == "creature" and not st.get("dead") and st.get("attitude", "hostile") == "hostile":
            rec = ctx.world.catalog.find(en.template_id or "")
            xp.append({"xp": int((rec.data.get("xp") if rec else 0) or 0)})
    total = sum(x["xp"] for x in xp)
    adjusted = total * _multiplier(len(xp), len(party))
    return {"ok": adjusted <= cap, "adjusted_xp": int(adjusted), "cap": int(cap), "party": len(party)}


class SpawnArgs(BaseModel):
    creature_template_id: str
    name: str = Field(max_length=128, description="имя экземпляра, например «Гоблин-лучник»")
    count: int = Field(1, ge=1, le=12)
    zone: Zone = "near"
    attitude: Literal["hostile", "neutral", "friendly"] = "hostile"
    description: str = Field(
        "",
        max_length=1000,
        description="внешность и манера, как их видят герои: это текст карточки для игроков. Мотивы и тайны сюда "
        "не пиши",
    )


@tool(
    "spawn_entity",
    "Выставляет существо или NPC из шаблона в текущую локацию. Враждебные проверяются бюджетом встречи.",
    SpawnArgs,
    ids={"creature_template_id": "templates:creature_template"},
)
async def spawn_entity(ctx: ToolContext, a: SpawnArgs) -> dict:
    from app.core.world import creature_stats

    rec = ctx.world.catalog.get(a.creature_template_id, "creature_template")
    creature_stats(rec.data)  # без блока статов существо в сцену не выходит
    if a.attitude == "hostile":
        b = encounter_budget(ctx, [{"xp": int(rec.data.get("xp") or 0)} for _ in range(a.count)])
        if not b["ok"]:
            raise ToolError(
                f"встреча превышает бюджет сложности кампании ({b['adjusted_xp']} > {b['cap']} опыта с поправкой на "
                f"число существ, героев: {b['party']}). Выставьте меньше или слабее"
            )
    hp = int((rec.data.get("hp") or {}).get("average", 1))
    created = []
    for i in range(a.count):
        name = a.name if a.count == 1 else f"{a.name} {i + 1}"
        en = Entity(
            campaign_id=ctx.campaign.id,
            kind="creature",
            name=name,
            template_id=rec.id,
            description=a.description,
            state={"hp": hp, "hp_max": hp, "attitude": a.attitude},
            location_id=ctx.world.scene.location_id,
            zone=a.zone,
        )
        ctx.session.add(en)
        await ctx.session.flush()
        ctx.world.entities[en.id] = en
        created.append({"id": en.id, "name": name})
        await ctx.record(
            "spawn_entity",
            target_id=en.id,
            payload={"template": rec.id, "name": name, "attitude": a.attitude, "zone": a.zone},
            inverse=[{"table": "entities", "op": "delete", "id": en.id}],
        )
    return {"spawned": created, "template": rec.name, "hp": hp, "ac": rec.data.get("ac")}


class UpdateEntityArgs(BaseModel):
    entity_id: str
    attitude: Literal["hostile", "neutral", "friendly"] | None = None
    mood: str | None = Field(None, max_length=64)
    note: str | None = Field(None, max_length=500, description="нарративная пометка: мотив, что пообещал")
    zone: Zone | None = Field(None, description="сблизился или отошёл: вплотную, близко, далеко")
    fled: bool | None = Field(None, description="существо ушло со сцены")


@tool(
    "update_entity",
    "Меняет нарративные поля сущности: отношение, настроение, зону, пометки. Хиты и статы так не меняются.",
    UpdateEntityArgs,
    ids={"entity_id": "entities"},
    closes=False,
)
async def update_entity(ctx: ToolContext, a: UpdateEntityArgs) -> dict:
    en = ctx.world.entities.get(a.entity_id)
    if en is None:
        raise ToolError(f"нет сущности {a.entity_id}")
    inverse = [
        {"table": "entities", "id": en.id, "field": "state", "before": copy.deepcopy(en.state)},
        {"table": "entities", "id": en.id, "field": "zone", "before": en.zone},
        {"table": "entities", "id": en.id, "field": "location_id", "before": en.location_id},
    ]
    st = dict(en.state or {})
    changes = {}
    for k in ("attitude", "mood", "note"):
        v = getattr(a, k)
        if v is not None:
            st[k] = v
            changes[k] = v
    if a.zone is not None:
        en.zone = a.zone
        changes["zone"] = a.zone
    if a.fled:
        en.location_id = None
        changes["fled"] = True
    en.state = st
    ctx.world.invalidate(en.id)
    await ctx.record("update_entity", target_id=en.id, payload={"name": en.name, **changes}, inverse=inverse)
    return {"entity": en.name, **changes}


class CreateLocationArgs(BaseModel):
    name: str = Field(max_length=128)
    description: str = Field(
        "", max_length=2000, description="как место выглядит для героев: это текст карточки для игроков, без тайн"
    )
    template_id: str | None = Field(None, description="шаблон локации пакета, если есть подходящий")
    make_current: bool = Field(False, description="сразу сделать текущей локацией сцены")


@tool(
    "create_location",
    "Регистрирует локацию в реестре мира (по шаблону пакета, если он есть).",
    CreateLocationArgs,
    closes=False,
)
async def create_location(ctx: ToolContext, a: CreateLocationArgs) -> dict:
    state = {}
    if a.template_id:
        rec = ctx.world.catalog.get(a.template_id, "location_template")
        if rec.data.get("dc") is not None:
            state["dc"] = rec.data["dc"]
    en = Entity(
        campaign_id=ctx.campaign.id,
        kind="location",
        name=a.name,
        template_id=a.template_id,
        description=a.description,
        state=state,
    )
    ctx.session.add(en)
    await ctx.session.flush()
    ctx.world.entities[en.id] = en
    inverse = [{"table": "entities", "op": "delete", "id": en.id}]
    if a.make_current:
        inverse.append(
            {"table": "scenes", "id": ctx.campaign.id, "field": "location_id", "before": ctx.world.scene.location_id}
        )
        ctx.world.scene.location_id = en.id
    await ctx.record(
        "create_location", target_id=en.id, payload={"name": a.name, "current": a.make_current}, inverse=inverse
    )
    return {"location_id": en.id, "name": a.name, "current": a.make_current}


class MoveArgs(BaseModel):
    character_ids: list[str] = Field(min_length=1)
    location_id: str


@tool(
    "move",
    "Перемещает героев в локацию реестра. Если уходят все герои — локация становится текущей сценой.",
    MoveArgs,
    ids={"character_ids": "characters", "location_id": "locations"},
)
async def move(ctx: ToolContext, a: MoveArgs) -> dict:
    loc = ctx.world.entities.get(a.location_id)
    if loc is None or loc.kind != "location":
        raise ToolError(f"нет локации {a.location_id}; сначала create_location")
    inverse = []
    for cid in a.character_ids:
        ch = _character(ctx, cid)
        inverse.append({"table": "characters", "id": ch.id, "field": "location_id", "before": ch.location_id})
        ch.location_id = loc.id
    party = [c for c in ctx.world.characters.values() if c.status in PLAYABLE]
    if all(c.location_id == loc.id for c in party):
        inverse.append(
            {"table": "scenes", "id": ctx.campaign.id, "field": "location_id", "before": ctx.world.scene.location_id}
        )
        ctx.world.scene.location_id = loc.id
    await ctx.record(
        "move", target_id=loc.id, payload={"characters": a.character_ids, "location": loc.name}, inverse=inverse
    )
    return {"moved": a.character_ids, "location": loc.name, "scene_location": ctx.world.scene.location_id}


class RevealArgs(BaseModel):
    character_id: str
    entity_id: str
    level: int = Field(ge=0, le=3, description="0 — видел, 1 — наслышан, 2 — изучил, 3 — знает всё")


@tool(
    "reveal_knowledge",
    "Открывает персонажу сведения о сущности до уровня знаний.",
    RevealArgs,
    ids={"character_id": "characters", "entity_id": "entities"},
    closes=False,
)
async def reveal_knowledge(ctx: ToolContext, a: RevealArgs) -> dict:
    ch = _character(ctx, a.character_id)
    if a.entity_id not in ctx.world.entities:
        raise ToolError(f"нет сущности {a.entity_id}")
    row = await ctx.session.get(Knowledge, (ch.id, a.entity_id))
    before = row.level if row else None
    if row is None:
        row = Knowledge(character_id=ch.id, entity_id=a.entity_id, level=a.level)
        ctx.session.add(row)
    else:
        row.level = max(row.level, a.level)
    await ctx.session.flush()
    await ctx.record(
        "reveal_knowledge",
        actor_id=ch.id,
        target_id=a.entity_id,
        payload={"level": row.level},
        inverse=[{"table": "knowledge", "id": [ch.id, a.entity_id], "field": "level", "before": before}],
    )
    return {"character": ch.name, "entity": ctx.world.entities[a.entity_id].name, "level": row.level}


class FactArgs(BaseModel):
    character_ids: list[str] = Field(
        min_length=1, max_length=8, description="кто из героев это узнал (обычно все, кто был в сцене)"
    )
    subject_id: str = Field(description="о ком или о чём факт: id сущности, места или героя")
    fact: str = Field(
        min_length=3,
        max_length=300,
        description="что герои теперь знают, одной фразой от третьего лица: «Староста боится леса». "
        "Только то, что они действительно узнали, без тайн, до которых не добрались",
    )


@tool(
    "learn_fact",
    "Герои узнали факт о NPC, месте, существе или другом герое: он появится в карточке по клику на имя "
    "у тех, кто узнал. Вызывай, когда в сцене прозвучало что-то новое и важное.",
    FactArgs,
    ids={"subject_id": "subjects"},
    closes=False,
)
async def learn_fact(ctx: ToolContext, a: FactArgs) -> dict:
    w = ctx.world
    subject = w.entities.get(a.subject_id) or w.characters.get(a.subject_id)
    if subject is None:
        raise ToolError(f"нет сущности или героя {a.subject_id}")
    text = " ".join(a.fact.split())
    names = []
    for cid in dict.fromkeys(a.character_ids):
        ch = _character(ctx, cid)
        row = KnownFact(campaign_id=ctx.campaign.id, character_id=ch.id, subject_id=a.subject_id, text=text)
        ctx.session.add(row)
        if a.subject_id in w.entities and await ctx.session.get(Knowledge, (ch.id, a.subject_id)) is None:
            ctx.session.add(Knowledge(character_id=ch.id, entity_id=a.subject_id, level=0))  # теперь он о нём знает
        await ctx.session.flush()
        await ctx.record(
            "learn_fact",
            actor_id=ch.id,
            target_id=a.subject_id,
            payload={"fact": text},
            inverse=[{"table": "known_facts", "op": "delete", "id": row.id}],
        )
        names.append(ch.name)
    return {"learned": names, "subject": subject.name, "fact": text}


# --- сцена и время ---


class SceneModeArgs(BaseModel):
    mode: Literal["free", "combat"]
    participants: list[str] | None = Field(
        None, description="кто участвует в бою; по умолчанию все герои и враждебные существа сцены"
    )


@tool(
    "set_scene_mode",
    "Включает бой (бросает инициативу, раунд 1) или свободный режим.",
    SceneModeArgs,
    ids={"participants": "combatants"},
    closes=False,
)
async def set_scene_mode(ctx: ToolContext, a: SceneModeArgs) -> dict:
    sc = ctx.world.scene
    inverse = [
        {"table": "scenes", "id": ctx.campaign.id, "field": f, "before": copy.deepcopy(getattr(sc, f))}
        for f in ("mode", "round", "turn_order", "state")
    ]
    if a.mode == "free":
        won = sc.mode == "combat" and bool(combat._heroes_standing(ctx)) and not combat._hostiles_left(ctx)
        sc.mode, sc.round, sc.turn_order = "free", 0, []
        combat.end_combat(ctx)
        audio.on_mode(ctx, "free", victory=won)
        await ctx.record("set_scene_mode", payload={"mode": "free"}, inverse=inverse)
        return {"mode": "free"}
    ids = a.participants
    if not ids:
        ids = [c.id for c in ctx.world.characters.values() if c.status in PLAYABLE]
        ids += [
            e.id
            for e in ctx.world.in_scene_entities()
            if e.kind == "creature" and (e.state or {}).get("attitude", "hostile") == "hostile"
        ]
    entries, dice = [], []
    for i in ids:
        act = ctx.world.actor(i)
        if not act.alive:
            continue
        roll = engine.initiative(ctx.dice, act.mods["dex"], RollMode.NORMAL)
        entries.append((act.id, roll, act.mods["dex"]))
        dice.append({"who": act.id, **dice_json(roll)})
    order = engine.initiative_order(entries)
    totals = {e[0]: e[1].total for e in entries}
    sc.mode, sc.round = "combat", 1
    sc.turn_order = [{"id": i, "initiative": totals[i]} for i in order]
    combat.start_combat(ctx)
    audio.on_mode(ctx, "combat")
    names = [f"{ctx.world.actor(i).name} ({totals[i]})" for i in order]
    await ctx.record("set_scene_mode", payload={"mode": "combat", "order": sc.turn_order}, dice=dice, inverse=inverse)
    return {"mode": "combat", "round": 1, "initiative": names}


class TimeArgs(BaseModel):
    amount: int = Field(ge=1, le=1000)
    unit: Literal["round", "minute", "hour", "day"]
    reason: str


@tool(
    "advance_time",
    "Двигает игровые часы. Сервер сам снимает истёкшие эффекты. В бою раунд — 6 секунд.",
    TimeArgs,
    closes=False,
)
async def advance_time(ctx: ToolContext, a: TimeArgs) -> dict:
    seconds = a.amount * fx.UNIT_SECONDS[a.unit]
    before = ctx.world.scene.game_time
    ctx.world.scene.game_time = before + seconds
    inverse = [{"table": "scenes", "id": ctx.campaign.id, "field": "game_time", "before": before}]
    if ctx.world.scene.mode == "combat" and a.unit == "round":
        inverse.append({"table": "scenes", "id": ctx.campaign.id, "field": "round", "before": ctx.world.scene.round})
        ctx.world.scene.round += a.amount
    expired = await expire_effects(ctx, inverse)
    await ctx.record(
        "advance_time", payload={"seconds": seconds, "reason": a.reason, "expired": expired}, inverse=inverse
    )
    return {"time": format_time(ctx.world.scene.game_time), "expired": expired}


async def expire_effects(ctx: ToolContext, inverse: list) -> list[str]:
    out = []
    for e in list(ctx.world.effects):
        if e.expires_at is not None and e.expires_at <= ctx.world.scene.game_time:
            inverse.append(
                {
                    "table": "active_effects",
                    "op": "restore",
                    "row": {
                        "id": e.id,
                        "effect_template_id": e.effect_template_id,
                        "stacks": e.stacks,
                        "expires_at": e.expires_at,
                        "target_id": e.target_id,
                    },
                }
            )
            rec = ctx.world.catalog.find(e.effect_template_id)
            out.append(f"{e.target_id}: {rec.name if rec else e.effect_template_id}")
            await ctx.session.delete(e)
            ctx.world.effects.remove(e)
            ctx.world.invalidate(e.target_id)
            ctx.changed.add(e.target_id)
    await ctx.session.flush()
    return out


class RestArgs(BaseModel):
    character_ids: list[str] = Field(min_length=1)
    kind: Literal["short", "long"]
    spend_hit_dice: int = Field(0, ge=0, le=20, description="короткий отдых: сколько костей хитов тратит каждый")


@tool(
    "rest",
    "Короткий (1 час) или продолжительный (8 часов) отдых по SRD: время, хиты, кости хитов.",
    RestArgs,
    ids={"character_ids": "characters"},
)
async def rest(ctx: ToolContext, a: RestArgs) -> dict:
    if ctx.world.scene.mode == "combat":
        raise ToolError("в бою не отдыхают: сначала set_scene_mode free")
    hours = 1 if a.kind == "short" else 8
    last_long = int((ctx.world.scene.state or {}).get("last_long_rest", -(10**9)))
    if a.kind == "long" and ctx.world.scene.game_time - last_long < 24 * 3600 and last_long >= 0:
        raise ToolError("продолжительный отдых — не чаще раза в 24 часа игрового времени")
    sc = ctx.world.scene
    inverse = [
        {"table": "scenes", "id": ctx.campaign.id, "field": "game_time", "before": sc.game_time},
        {"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(sc.state)},
    ]
    results, dice = [], []
    for cid in a.character_ids:
        ch = _character(ctx, cid)
        act = ctx.world.actor(ch.id)
        inverse.append(snapshot(act))
        res = dict(ch.resources or {})
        level = int((ch.sheet or {}).get("level", 1))
        hd_left = int(res.get("hit_dice", level))
        if act.hp.dead:
            continue
        if a.kind == "long":
            act.hp.current, act.hp.temp = act.hp.maximum, 0
            act.hp.death_saves = type(act.hp.death_saves)()
            hd_left = min(level, hd_left + max(1, level // 2))
            act.save_hp()
            ch.resources = {**ch.resources, "hit_dice": hd_left}
            results.append({"character": ch.name, "hp": act.hp.current, "hit_dice": hd_left})
            continue
        cls = ctx.world.catalog.find((ch.sheet or {}).get("class_id", ""), "class")
        die = int(str((cls.data if cls else {}).get("hit_die", "d8")).lstrip("d"))
        healed = 0
        for _ in range(min(a.spend_hit_dice, hd_left)):
            if act.hp.current >= act.hp.maximum:
                break
            r = ctx.dice.roll(f"1d{die}")
            dice.append({"who": ch.id, **dice_json(r)})
            gain = max(0, r.total + act.mods["con"])
            engine.heal(act.hp, gain)
            healed += gain
            hd_left -= 1
        act.save_hp()
        ch.resources = {**ch.resources, "hit_dice": hd_left}
        results.append({"character": ch.name, "healed": healed, "hp": act.hp.current, "hit_dice": hd_left})
        ctx.world.invalidate(ch.id)
    ctx.world.scene.game_time += hours * 3600
    if a.kind == "long":
        sc.state = {**(sc.state or {}), "last_long_rest": sc.game_time}
    expired = await expire_effects(ctx, inverse)
    await ctx.record(
        "rest", payload={"kind": a.kind, "results": results, "expired": expired}, dice=dice, inverse=inverse
    )
    return {"kind": a.kind, "results": results, "time": format_time(ctx.world.scene.game_time), "expired": expired}


class GrantLevelArgs(BaseModel):
    character_ids: list[str] = Field(min_length=1)
    reason: str = Field(description="сюжетная веха")


@tool(
    "grant_level",
    "Повышение уровня на сюжетной вехе. Потолок — уровень пакета. Хиты растут по SRD.",
    GrantLevelArgs,
    ids={"character_ids": "characters"},
    closes=False,
)
async def grant_level(ctx: ToolContext, a: GrantLevelArgs) -> dict:
    cap = MAX_LEVEL_DEFAULT
    for pid, ver in ctx.campaign.content_chain or []:
        from app.db.models import ContentPack

        p = await ctx.session.get(ContentPack, (pid, ver))
        if p and p.manifest.get("level_cap"):
            cap = min(cap, int(p.manifest["level_cap"]))
    out = []
    for cid in a.character_ids:
        ch = _character(ctx, cid)
        act = ctx.world.actor(ch.id)
        level = int((ch.sheet or {}).get("level", 1))
        if level >= cap:
            raise ToolError(f"{ch.name} уже на потолке уровня ({cap})")
        inverse = [
            {"table": "characters", "id": ch.id, "field": "sheet", "before": copy.deepcopy(ch.sheet)},
            snapshot(act),
        ]
        old_max = act.hp.maximum
        ch.sheet = {**ch.sheet, "level": level + 1}
        ctx.world.invalidate(ch.id)
        new = ctx.world.actor(ch.id)
        # максимум хитов в карточке пересчитывается, текущие растут на прибавку
        res = dict(ch.resources or {})
        gain = new_max = 0
        from app.rules.dnd5e.character import derive  # noqa: F401 — пересчёт уже сделан в actor

        new_max = engine.hit_points_max(
            int(
                str(
                    (ctx.world.catalog.find(ch.sheet.get("class_id", ""), "class").data or {}).get("hit_die", "d8")
                ).lstrip("d")
            ),
            new.mods["con"],
            level + 1,
        )
        gain = new_max - old_max
        res.update(
            {
                "hp_max": new_max,
                "hp": int(res.get("hp", old_max)) + gain,
                "hit_dice": int(res.get("hit_dice", level)) + 1,
            }
        )
        ch.resources = res
        ctx.world.invalidate(ch.id)
        await ctx.record(
            "grant_level",
            target_id=ch.id,
            payload={"level": level + 1, "reason": a.reason, "hp_max": new_max},
            inverse=inverse,
        )
        out.append({"character": ch.name, "level": level + 1, "hp_max": new_max})
    return {"levels": out}


# --- общение и контракт намерения ---


class WhisperArgs(BaseModel):
    character_id: str = Field(description="персонаж, чьему игроку уйдёт личное сообщение")
    text: str = Field(min_length=1, max_length=2000)


@tool(
    "whisper",
    "Личное сообщение одному игроку: видят только он и мастер.",
    WhisperArgs,
    ids={"character_id": "characters"},
    closes=False,
)
async def whisper(ctx: ToolContext, a: WhisperArgs) -> dict:
    ch = _character(ctx, a.character_id)
    if ch.seat_id is None:
        raise ToolError(f"у персонажа {ch.name} нет игрока")
    ms = master_seat(ctx.campaign)
    # Номер сообщения выдаётся при фиксации хода: строку кампании нельзя держать заблокированной весь ход
    ctx.outbox.append({"kind": "narration", "seat_id": ms.id, "visible_to": [ch.seat_id, ms.id], "content": a.text})
    await ctx.record("whisper", target_id=ch.id, payload={"text": a.text}, hidden=True)
    return {"sent_to": ch.name}


class ReasonArgs(BaseModel):
    character_id: str
    reason: str = Field(min_length=1, max_length=500)


@tool(
    "cancel_action",
    "Явный отказ в действии игрока с причиной: цель скрылась, дверь уже открыта.",
    ReasonArgs,
    ids={"character_id": "characters"},
)
async def cancel_action(ctx: ToolContext, a: ReasonArgs) -> dict:
    ch = _character(ctx, a.character_id)
    await ctx.record("cancel_action", target_id=ch.id, payload={"reason": a.reason})
    return {"character": ch.name, "cancelled": a.reason}


@tool(
    "auto_success",
    "Тривиальное действие без броска: открыть незапертую дверь, поднять монету.",
    ReasonArgs,
    ids={"character_id": "characters"},
)
async def auto_success(ctx: ToolContext, a: ReasonArgs) -> dict:
    ch = _character(ctx, a.character_id)
    await ctx.record("auto_success", target_id=ch.id, payload={"reason": a.reason})
    return {"character": ch.name, "success": a.reason}


MOMENTS = {
    "betrayal": "предательство",
    "rescue": "спасение",
    "failure": "крупный провал",
    "victory": "крупная победа",
    "loss": "тяжёлая потеря",
}


class MomentArgs(BaseModel):
    kind: Literal["betrayal", "rescue", "failure", "victory", "loss"] = Field(
        description="betrayal — предательство, rescue — спасение, failure — крупный провал, "
        "victory — крупная победа, loss — тяжёлая потеря (не гибель героя: её сервер видит сам)"
    )
    character_ids: list[str] = Field(default_factory=list, description="герои, которых это задело")
    text: str = Field(min_length=1, max_length=300, description="что случилось, одной фразой")


@tool(
    "mark_moment",
    "Отмечает сильный момент для летописи характера героев под ИИ и ИИ-мастера: предательство, спасение, "
    "крупный провал или победу, тяжёлую потерю. Только по-настоящему поворотное, не каждый удачный бросок. "
    "Игроки отметку не видят.",
    MomentArgs,
    ids={"character_ids": "characters"},
    closes=False,
)
async def mark_moment(ctx: ToolContext, a: MomentArgs) -> dict:
    names = [_character(ctx, cid).name for cid in a.character_ids]
    await ctx.record(
        "mark_moment",
        payload={"kind": a.kind, "label": MOMENTS[a.kind], "characters": a.character_ids, "text": a.text},
        hidden=True,
    )
    return {"marked": MOMENTS[a.kind], "characters": names}


class ReviewArgs(BaseModel):
    character_id: str
    approve: bool
    comment: str = Field("", max_length=2000, description="замечания игроку; при возврате — обязательно")
    secret_link: str | None = Field(
        None, max_length=2000, description="тайная связь истории героя с сюжетом, игрок её не увидит"
    )
    hook_ref: str | None = Field(
        None, description="к чему в каркасе привязать эту связь: id узла, NPC, злодея или места (если каркас есть)"
    )


@tool(
    "review_character",
    "Решение мастера по персонажу на проверке: одобрить или вернуть с комментарием.",
    ReviewArgs,
    ids={"hook_ref": "plot:hooks"},
    closes=False,
)
async def review_character(ctx: ToolContext, a: ReviewArgs) -> dict:
    ch = ctx.world.characters.get(a.character_id)
    if ch is None or ch.status != "submitted":
        raise ToolError("персонаж не на проверке")
    if not a.approve and not a.comment:
        raise ToolError("при возврате на доработку нужен комментарий")
    from app.core.campaigns import Conflict
    from app.core.characters import approve_character, record_secret_link

    before = ch.status
    if a.approve:
        await approve_character(ctx.session, ctx.campaign, ch, ctx.world.catalog)
    else:
        ch.status = "draft"
    ch.review_comment = a.comment or None
    if a.hook_ref and not a.secret_link:
        raise ToolError("hook_ref задаётся вместе с secret_link")
    if a.secret_link:
        try:
            await record_secret_link(ctx.session, ctx.campaign.id, ch, a.secret_link, ref=a.hook_ref)
        except Conflict as e:
            raise ToolError(str(e)) from e
    await ctx.record(
        "review_character",
        target_id=ch.id,
        payload={"approve": a.approve, "comment": a.comment},
        inverse=[{"table": "characters", "id": ch.id, "field": "status", "before": before}],
    )
    return {"character": ch.name, "status": ch.status}


MUTATING_FOR_NARRATION: tuple[str, ...] = ()  # в фазе повествования изменяющих инструментов нет (раздел 7.1)
READ_TOOLS = ("get_scene", "get_character", "lookup_template")


async def pending_effects_ids(ctx: ToolContext) -> list[str]:
    rows = await ctx.session.scalars(select(ActiveEffect.id).where(ActiveEffect.campaign_id == ctx.campaign.id))
    return list(rows)


__all__ = ["READ_TOOLS", "WorldError", "ZONE_FT", "encounter_budget", "expire_effects"]
