"""Инструменты мастера (ТЗ, разделы 7, 7.1, 7.2, 8.1). Числа считает движок правил, мастер передаёт только
шаблоны, цели и параметры из данных. Каждый изменяющий вызов оставляет событие в журнале с обратной дельтой.

Заклинания — в app/tools/spells.py (``cast_spell``).
"""

from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core import adventure, audio, combat, sketch
from app.core.campaigns import master_seat
from app.core.features import uses_view
from app.core.positions import COVER_AC, Pos, active_areas, areas_at, distance, hero_positions, inside, pos_of
from app.core.world import (
    PLAYABLE,
    ZONE_FT,
    ZONE_NAMES,
    Actor,
    WorldError,
    format_time,
    is_scene_item,
    lineage_features,
)
from app.db.models import ActiveEffect, Character, Entity, InventoryItem, Knowledge, KnownFact
from app.rules.dnd5e import modifiers as mod
from app.rules.dnd5e.engine import Dnd5eEngine
from app.rules.dnd5e.tables import ABILITIES, SKILLS
from app.tools import effects as fx
from app.tools.registry import ToolContext, ToolError, dice_json, tool

engine = Dnd5eEngine()
Zone = Literal["melee", "near", "far"]
Bearing = Literal["n", "ne", "e", "se", "s", "sw", "w", "nw"]
BEARING_HINT = "в какой стороне от отряда на схеме места: n — север (вверх), e — восток и т. д."
PLACE_HINT = "место, где стоят герои; нужно, только если отряд разделён (по умолчанию — место сцены)"
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
        "features": uses_view(ch, ctx.world.catalog, act.mods, act.pb),
        **_spellbook(ctx, ch),
    }


def _spellbook(ctx: ToolContext, ch: Character) -> dict:
    """Заклинания героя для мастера: сложность, бонус атаки, ячейки и что он может сотворить (для cast_spell)."""
    from app.core.spells import book_view

    b = book_view(ch.sheet or {}, ch.resources or {}, ctx.world.catalog)
    if b is None:
        return {}
    return {
        "spellcasting": {
            "save_dc": b["save_dc"],
            "attack": b["attack"],
            "slots_left": b["slots_left"],
            "pact_left": b["pact_left"] if b["pact_slots"] else None,
            "concentration": (b["concentration"] or {}).get("name"),
            "spells": [
                {"id": x["id"], "name": x["name"], "level": x["level"], "ritual": x["ritual"]}
                for x in b["spells"]
                if x["prepared"]
            ],
        }
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
    inspiration: bool = Field(False, description="герой тратит вдохновение на преимущество (если игрок попросил)")
    edge: Edge = Field("none", description=EDGE_HINT)
    edge_reason: str | None = Field(None, max_length=200, description="почему преимущество или помеха — увидят игроки")


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
    mode, reasons = mod.with_circumstance(mode, reasons, a.edge, _edge_reason(a.edge, a.edge_reason))
    auto = mod.save_auto_fail(act.modifiers, ability) if a.kind == "save" else None
    spent = _inspire(ctx, act, a.inspiration, mode, reasons)
    if spent:
        mode, reasons, spent = spent
    res = (engine.saving_throw if a.kind == "save" else engine.check)(ctx.dice, bonus, dc, mode, critical_checks(ctx))
    success = res.success and auto is None
    hidden = a.kind == "check" and a.stat in _hidden_skills(ctx)
    result = {
        "who": act.name,
        "stat": a.stat,
        "kind": a.kind,
        "dc": dc,
        "natural": res.roll.natural,
        "total": res.roll.total,
        "success": success,
        "margin": res.margin,
        "hidden": hidden,
    }
    if res.critical and not auto:
        result["critical"] = res.critical
        if isinstance(act.obj, Character):
            result["critical_note"] = CRIT_NOTES[res.critical]
    if reasons:
        result["reasons"] = reasons
    if auto:
        result["auto_fail"] = auto
    if spent:
        result["inspiration_spent"] = True
    await ctx.record(
        "roll_check",
        actor_id=act.id,
        payload={"reason": a.reason, **result},
        dice=[dice_json(res.roll)],
        hidden=hidden,
        inverse=spent or [],
    )
    return result


# Что мастер обязан сделать с критическим исходом героя (просьба Arty 2026-10-04): успех — исполнить заявку,
# провал — закрепить последствие в листе героя, а не оставить его словами в повествовании.
CRIT_NOTES = {
    "success": (
        "критический успех: исполни заявку игрока так близко к задуманному, как только возможно в мире, даже дерзкую "
        "(«стащить штаны со стражника» — штаны у героя). Добытое закрепи инструментом: keep_found_item, give_item, "
        "learn_fact, record_deed"
    ),
    "fail": (
        "критический провал: последствие бьёт по самому герою и должно остаться в его листе. Закрепи его сейчас "
        "инструментом на этого героя: apply_effect с состоянием из шаблонов (condition.prone, condition.poisoned, "
        "condition.frightened, condition.deafened, condition.blinded; укажи длительность), drop_item, apply_hazard "
        "или reposition. Одних слов в повествовании мало"
    ),
}
CONSEQUENCE_TOOLS = ("apply_effect", "drop_item", "apply_hazard", "reposition", "pass_item")


def critical_checks(ctx: ToolContext) -> bool:
    """Натуральные 20 и 1 в проверках и спасбросках вне атак — критический успех и провал. Домашнее правило,
    включено по умолчанию; выключается настройкой кампании ``critical_checks: false``."""
    return (ctx.campaign.settings or {}).get("critical_checks", True) is not False


def _edge_reason(edge: str, why: str | None) -> str | None:
    if edge == "none":
        return None
    why = (why or "").strip()
    if not why:
        word = "преимущество" if edge == "advantage" else "помеху"
        raise ToolError(f"укажите в edge_reason, за что {word}: игрок увидит причину в карточке броска")
    return why


def _inspire(ctx: ToolContext, act: Actor, use: bool, mode, reasons: list) -> tuple | None:
    """Вдохновение героя (SRD): преимущество на этот бросок. None — не тратится."""
    if not use:
        return None
    from app.core.standing import StandingError, spend_inspiration

    if not isinstance(act.obj, Character):
        raise ToolError("вдохновение бывает только у героев")
    try:
        out = spend_inspiration(act.obj, mode, list(reasons))
    except StandingError as e:
        raise ToolError(str(e)) from e
    ctx.changed.add(act.id)
    return out


def _difficulty(ctx: ToolContext, ref: str) -> int:
    scale = {e.id: int(e.data["value"]) for e in ctx.world.catalog.dc_scale()}
    if ref in scale:
        return scale[ref]
    book = adventure.book_dc(ref, ctx.world.entities, ctx.world.catalog)
    if book is not None:
        return book
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
    inspiration: bool = Field(False, description="герой тратит вдохновение на преимущество (если игрок попросил)")
    edge: Edge = Field("none", description=EDGE_HINT)
    edge_reason: str | None = Field(None, max_length=200, description="почему преимущество или помеха — увидят игроки")


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

    cover = pos_of(w, tgt.id).cover
    if cover == "total":
        raise ToolError(f"{tgt.name} за полным укрытием: напрямую не атаковать, сначала выманить или обойти")
    dist = w.distance_ft(att, tgt)
    extra = []
    if weapon["kind"] == "melee" and dist > int(weapon.get("reach_ft") or 5) and weapon.get("normal_ft"):
        weapon = {**weapon, "kind": "ranged"}  # метательное оружие (дротик, копьё) бросают издалека
    if weapon["kind"] == "melee":
        if dist > int(weapon.get("reach_ft") or 5):
            raise ToolError(
                f"{tgt.name} {ZONE_NAMES.get(tgt.zone if tgt.kind != 'character' else att.zone, 'далеко')}: "
                "для рукопашной атаки нужно сблизиться (reposition или update_entity zone=melee)"
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
    target_ac = tgt.ac + COVER_AC.get(cover, 0)
    am = mod.attack_mods(att.modifiers, tgt.modifiers, dist, extra)
    mode, am_reasons = mod.with_circumstance(am.mode, list(am.reasons), a.edge, _edge_reason(a.edge, a.edge_reason))
    spent = _inspire(ctx, att, a.inspiration, mode, am_reasons)
    if spent:
        mode, am_reasons, spent = spent
    roll = engine.attack(ctx.dice, int(weapon["attack_bonus"]) + am.bonus, target_ac, mode)
    critical = roll.critical or (roll.hit and am.auto_crit)
    result: dict = {
        "attacker": att.name,
        "target": tgt.name,
        "attack": weapon["name"],
        "roll": roll.roll.total,
        "natural": roll.roll.natural,
        "target_ac": target_ac,
        "hit": roll.hit,
        "critical": critical,
        "mode": str(mode),
    }
    if roll.roll.natural == 1:
        result["fumble"] = True  # натуральная 1: не просто промах, неудача оборачивается против атакующего
        if isinstance(att.obj, Character):
            result["critical_note"] = CRIT_NOTES["fail"]
    if am_reasons:
        result["reasons"] = am_reasons
    if spent:
        result["inspiration_spent"] = True
    if COVER_AC.get(cover):
        result["cover"] = f"+{COVER_AC[cover]} к КД за укрытие"
    dice = [dice_json(roll.roll)]
    inverse = [snapshot(tgt), *(spent or [])]
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
        from app.tools.spells import concentration_check

        conc = await concentration_check(ctx, tgt, int(result["damage"]))
        if conc:
            result["concentration_check"] = conc
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
    return await _hazard_on(ctx, rec, tgt, params)


async def _hazard_on(ctx: ToolContext, rec, tgt: Actor, params: dict | None = None) -> dict:
    inv = [snapshot(tgt)]
    out = await fx.run_ops(ctx, rec.id, rec.data.get("modifiers") or [], tgt, params or {})
    result = {"hazard": rec.name, "target": tgt.name, **out, "target_status": ctx.world.actor(tgt.id).status()}
    dice = result.pop("dice")
    await ctx.record("apply_hazard", target_id=tgt.id, payload={**result, "hazard_id": rec.id}, dice=dice, inverse=inv)
    ctx.world.invalidate(tgt.id)
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
    "Применяет предмет инвентаря по его шаблону (зелье, расходник). Свиток или формула творит записанное в нём "
    "заклинание по правилам cast_spell без ячейки. Оружие — через resolve_attack.",
    UseItemArgs,
    ids={"character_id": "characters", "inventory_id": "inventory", "target_id": "combatants"},
)
async def use_item(ctx: ToolContext, a: UseItemArgs) -> dict:
    ch = _character(ctx, a.character_id)
    it = next((i for i in ctx.world.inventory.get(ch.id, []) if i.id == a.inventory_id), None)
    if it is None:
        raise ToolError(f"у {ch.name} нет предмета {a.inventory_id}: рука нащупывает пустоту")
    if it.item_template_id == FOUND_ITEM:
        raise ToolError(f"«{ctx.world.item_name(it)}» — обычная вещь без механики: её применение реши проверкой")
    rec = ctx.world.catalog.get(it.item_template_id, "item_template")
    if rec.data.get("spell_scroll"):
        from app.tools.spells import read_scroll

        return await read_scroll(ctx, ch, it, rec, [a.target_id] if a.target_id else [])
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
    "Выдаёт предмет из шаблона прямо в инвентарь персонажа: награда, покупка. Добычу, которая лежит в сцене, клади "
    "через place_item, а подбирает её герой (pick_up_item). Несуществующий шаблон — ошибка.",
    GiveItemArgs,
    ids={"character_id": "characters"},
)
async def give_item(ctx: ToolContext, a: GiveItemArgs) -> dict:
    ch = _character(ctx, a.character_id)
    rec = ctx.world.catalog.get(a.item_template_id, "item_template")
    inv_id, inverse = await _add_to_inventory(ctx, ch, rec.id, a.display_name, a.qty)
    result = {"character": ch.name, "item": a.display_name or rec.name, "qty": a.qty, "inventory_id": inv_id}
    await ctx.record(
        "give_item", target_id=ch.id, payload={**result, "reason": a.reason, "template": rec.id}, inverse=inverse
    )
    return result


class KeepFoundArgs(BaseModel):
    character_id: str
    name: str = Field(min_length=1, max_length=128, description="как вещь называется в мире: «арматура», «шляпа»")
    kind: Literal["object", "improvised_weapon", "template"] = Field(
        description="object — обычная вещь без механики (камень, шляпа, ключ); improvised_weapon — годится как "
        "оружие (арматура, ножка стула): импровизированное оружие SRD 1d4; template — есть подходящий шаблон пакета "
        "(украденный кинжал, найденное зелье), укажи item_template_id"
    )
    item_template_id: str | None = Field(None, description="только для kind=template")
    qty: int = Field(1, ge=1, le=100)
    from_id: str | None = Field(None, description="у кого или откуда взято: NPC, существо, объект сцены")
    how: Literal["found", "pried", "stolen", "looted", "given"] = Field(
        description="found — нашёл, pried — выломал или вытащил, stolen — украл, looted — снял с побеждённого, "
        "given — отдали"
    )
    reason: str = Field(min_length=1, max_length=300, description="что произошло, одной фразой")


HOW_RU = {"found": "находит", "pried": "добывает", "stolen": "крадёт", "looted": "забирает", "given": "получает"}


@tool(
    "keep_found_item",
    "Герой оставляет себе вещь, добытую в мире по ходу игры: нашёл камень, выломал арматуру из стены, украл шляпу "
    "у прохожего. Если добыть вещь было непросто (вытащить, украсть), сначала roll_check, и вызывай это только при "
    "успехе. Вещь попадает в инвентарь героя и остаётся там.",
    KeepFoundArgs,
    ids={"character_id": "characters", "from_id": "subjects"},
)
async def keep_found_item(ctx: ToolContext, a: KeepFoundArgs) -> dict:
    ch = _character(ctx, a.character_id)
    _can_handle(ctx, ch)
    if a.kind == "template":
        if not a.item_template_id:
            raise ToolError("для kind=template укажите item_template_id (найдите его через lookup_template)")
        template = ctx.world.catalog.get(a.item_template_id, "item_template").id
    elif a.item_template_id:
        raise ToolError("item_template_id — только для kind=template")
    elif a.kind == "improvised_weapon":
        template = ctx.world.catalog.get(IMPROVISED_WEAPON, "item_template").id
    else:
        template = FOUND_ITEM
    inv_id, inverse = await _add_to_inventory(ctx, ch, template, a.name, a.qty)
    src = ctx.world.entities.get(a.from_id or "") or ctx.world.characters.get(a.from_id or "")
    result = {"character": ch.name, "item": a.name, "qty": a.qty, "inventory_id": inv_id, "how": a.how}
    if src is not None:
        result["from"] = src.name
    await ctx.record(
        "keep_found_item",
        actor_id=ch.id,
        target_id=a.from_id if src is not None else None,
        payload={**result, "reason": a.reason, "template": template},
        inverse=inverse,
    )
    many = f" ×{a.qty}" if a.qty > 1 else ""
    ctx.outbox.append({"kind": "system", "content": f"{ch.name} {HOW_RU[a.how]} «{a.name}»{many}: вещь в инвентаре."})
    return result


async def _add_to_inventory(
    ctx: ToolContext, ch: Character, template_id: str, display_name: str | None, qty: int
) -> tuple[str, list[dict]]:
    """Кладёт предметы в инвентарь: такой же неснаряжённый предмет складывается в стопку. Строка инвентаря живёт в
    БД, поэтому подобранное остаётся у героя между ходами и сессиями. Возвращает id строки и обратную дельту."""
    items = ctx.world.inventory.setdefault(ch.id, [])
    same = next(
        (i for i in items if i.item_template_id == template_id and i.display_name == display_name and not i.equipped),
        None,
    )
    if same is not None:
        inverse = [{"table": "inventory", "id": same.id, "field": "qty", "before": same.qty}]
        same.qty += qty
        ctx.world.invalidate(ch.id)
        return same.id, inverse
    row = InventoryItem(character_id=ch.id, item_template_id=template_id, display_name=display_name, qty=qty)
    ctx.session.add(row)
    await ctx.session.flush()
    items.append(row)
    ctx.world.invalidate(ch.id)
    return row.id, [{"table": "inventory", "op": "delete", "id": row.id}]


async def _remove_from_inventory(ctx: ToolContext, ch: Character, it: InventoryItem, qty: int) -> list[dict]:
    if qty > it.qty:
        raise ToolError(f"у {ch.name} только {it.qty} шт. «{ctx.world.item_name(it)}»")
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
    it.qty -= qty
    if it.qty == 0:
        await ctx.session.delete(it)
        ctx.world.inventory[ch.id].remove(it)
    ctx.world.invalidate(ch.id)
    return inverse


def _own_item(ctx: ToolContext, ch: Character, inventory_id: str) -> InventoryItem:
    it = next((i for i in ctx.world.inventory.get(ch.id, []) if i.id == inventory_id), None)
    if it is None:
        raise ToolError(f"у {ch.name} нет предмета {inventory_id}")
    return it


def _can_handle(ctx: ToolContext, ch: Character) -> None:
    act = ctx.world.actor(ch.id)
    if act.hp.current == 0:
        raise ToolError(f"{ch.name} без сознания: брать и отдавать вещи не может")


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
    it = _own_item(ctx, ch, a.inventory_id)
    name = ctx.world.item_name(it)
    inverse = await _remove_from_inventory(ctx, ch, it, a.qty)
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
    if it.item_template_id == FOUND_ITEM:
        raise ToolError(f"«{ctx.world.item_name(it)}» нельзя надеть или взять как оружие: это обычная вещь")
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


# --- предметы в сцене: добыча, которую герои подбирают сами ---


class PlaceItemArgs(BaseModel):
    item_template_id: str
    qty: int = Field(1, ge=1, le=100)
    display_name: str | None = Field(None, max_length=128, description="имя предмета в мире; свойства — из шаблона")
    zone: Zone = "near"
    description: str = Field(
        "", max_length=500, description="где и как лежит, как его видят герои: текст карточки для игроков"
    )
    reason: str = Field(description="откуда предмет: выпал у врага, лежит в сундуке, тайник")
    location_id: str | None = Field(None, description=PLACE_HINT)


@tool(
    "place_item",
    "Кладёт предмет из шаблона в текущую сцену: добыча у павшего врага, содержимое сундука, находка на полу. Герой "
    "подбирает его сам через pick_up_item, и тогда предмет остаётся в его инвентаре.",
    PlaceItemArgs,
    ids={"item_template_id": "templates:item_template", "location_id": "places"},
    closes=False,
)
async def place_item(ctx: ToolContext, a: PlaceItemArgs) -> dict:
    rec = ctx.world.catalog.get(a.item_template_id, "item_template")
    place = ctx.world.place_arg(a.location_id, "лежит предмет")
    en, inverse = await _put_in_scene(ctx, rec.id, a.display_name, a.qty, a.zone, a.description, place)
    result = {"entity_id": en.id, "item": en.name, "qty": a.qty}
    await ctx.record(
        "place_item", target_id=en.id, payload={**result, "reason": a.reason, "template": rec.id}, inverse=inverse
    )
    return result


async def _put_in_scene(
    ctx: ToolContext,
    template_id: str,
    display_name: str | None,
    qty: int,
    zone: str,
    description: str = "",
    place: str | None = None,
) -> tuple[Entity, list[dict]]:
    """Предмет в сцене — объект реестра с шаблоном предмета. Такой же, что уже лежит рядом, складывается в стопку.
    ``place`` — место, где он ляжет; по умолчанию основное место сцены."""
    rec = ctx.world.catalog.find(template_id)
    name = display_name or (rec.name if rec else template_id)
    place = place or ctx.world.home()
    for en in ctx.world.in_scene_entities(place):
        st = en.state or {}
        same = en.template_id == template_id and st.get("display_name") == display_name and en.zone == zone
        if is_scene_item(en) and same:
            en.state = {**st, "qty": int(st.get("qty") or 1) + qty}
            return en, [{"table": "entities", "id": en.id, "field": "state", "before": st}]
    en = Entity(
        campaign_id=ctx.campaign.id,
        kind="object",
        name=name,
        template_id=template_id,
        description=description or ((rec.data.get("description") or "") if rec else ""),
        state={"item": True, "qty": qty, "display_name": display_name},
        location_id=place,
        zone=zone,
    )
    ctx.session.add(en)
    await ctx.session.flush()
    ctx.world.entities[en.id] = en
    return en, [{"table": "entities", "op": "delete", "id": en.id}]


class PickUpArgs(BaseModel):
    character_id: str
    entity_id: str = Field(description="предмет, который лежит в сцене")
    qty: int | None = Field(None, ge=1, le=100, description="сколько взять; по умолчанию всё")


@tool(
    "pick_up_item",
    "Герой подбирает предмет, лежащий в сцене: предмет переходит в его инвентарь и остаётся там. Бросок не нужен, "
    "если предмет никто не охраняет.",
    PickUpArgs,
    ids={"character_id": "characters", "entity_id": "scene_items"},
)
async def pick_up_item(ctx: ToolContext, a: PickUpArgs) -> dict:
    ch = _character(ctx, a.character_id)
    _can_handle(ctx, ch)
    en = ctx.world.entities.get(a.entity_id)
    if en is None or en not in ctx.world.in_scene_entities(ctx.world.place_of(ch)):
        raise ToolError(f"предмета {a.entity_id} нет рядом с {ch.name}")
    if not is_scene_item(en):
        raise ToolError(f"{en.name} — не предмет: его нельзя положить в инвентарь")
    st = dict(en.state or {})
    have = int(st.get("qty") or 1)
    qty = a.qty or have
    if qty > have:
        raise ToolError(f"здесь лежит только {have} шт. «{en.name}»")
    if en.template_id != FOUND_ITEM:
        ctx.world.catalog.get(en.template_id or "", "item_template")  # шаблон пропал из пакета — брать нечего
    inverse = [{"table": "entities", "op": "restore", "row": _entity_row(en)}]
    inv_id, inv = await _add_to_inventory(ctx, ch, en.template_id, st.get("display_name"), qty)
    inverse += inv
    result = {"character": ch.name, "item": en.name, "qty": qty, "inventory_id": inv_id, "left": have - qty}
    await ctx.record("pick_up_item", actor_id=ch.id, target_id=en.id, payload=result, inverse=inverse)
    many = f" ×{qty}" if qty > 1 else ""
    ctx.outbox.append({"kind": "system", "content": f"{ch.name} подбирает «{en.name}»{many}: предмет в инвентаре."})
    if qty == have:
        await ctx.session.delete(en)
        ctx.world.entities.pop(en.id, None)
    else:
        en.state = {**st, "qty": have - qty}
    return result


def _entity_row(en: Entity) -> dict:
    return {
        "id": en.id,
        "kind": en.kind,
        "name": en.name,
        "template_id": en.template_id,
        "description": en.description,
        "state": copy.deepcopy(en.state),
        "location_id": en.location_id,
        "zone": en.zone,
    }


class DropArgs(BaseModel):
    character_id: str
    inventory_id: str
    qty: int = Field(1, ge=1, le=100)


@tool(
    "drop_item",
    "Герой бросает или оставляет предмет из инвентаря в сцене: он ляжет рядом, и его можно будет подобрать снова.",
    DropArgs,
    ids={"character_id": "characters", "inventory_id": "inventory"},
)
async def drop_item(ctx: ToolContext, a: DropArgs) -> dict:
    ch = _character(ctx, a.character_id)
    it = _own_item(ctx, ch, a.inventory_id)
    template, display = it.item_template_id, it.display_name
    name = ctx.world.item_name(it)
    inverse = await _remove_from_inventory(ctx, ch, it, a.qty)
    en, inv = await _put_in_scene(ctx, template, display, a.qty, "melee", place=ctx.world.place_of(ch))
    inverse += inv
    result = {"character": ch.name, "item": name, "qty": a.qty, "entity_id": en.id}
    await ctx.record("drop_item", actor_id=ch.id, target_id=en.id, payload=result, inverse=inverse)
    return result


class PassItemArgs(BaseModel):
    character_id: str = Field(description="кто отдаёт")
    to_character_id: str = Field(description="кому из героев отряда")
    inventory_id: str
    qty: int = Field(1, ge=1, le=100)


@tool(
    "pass_item",
    "Герой передаёт предмет из своего инвентаря другому герою отряда.",
    PassItemArgs,
    ids={"character_id": "characters", "to_character_id": "characters", "inventory_id": "inventory"},
)
async def pass_item(ctx: ToolContext, a: PassItemArgs) -> dict:
    ch = _character(ctx, a.character_id)
    to = _character(ctx, a.to_character_id)
    if ch.id == to.id:
        raise ToolError("отдать предмет самому себе нельзя")
    _can_handle(ctx, ch)
    it = _own_item(ctx, ch, a.inventory_id)
    template, display = it.item_template_id, it.display_name
    name = ctx.world.item_name(it)
    inverse = await _remove_from_inventory(ctx, ch, it, a.qty)
    inv_id, inv = await _add_to_inventory(ctx, to, template, display, a.qty)
    result = {"from": ch.name, "to": to.name, "item": name, "qty": a.qty, "inventory_id": inv_id}
    await ctx.record("pass_item", actor_id=ch.id, target_id=to.id, payload=result, inverse=inverse + inv)
    ctx.outbox.append(
        {"kind": "system", "content": f"{ch.name} передаёт {to.name} «{name}»{f' ×{a.qty}' if a.qty > 1 else ''}."}
    )
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


def encounter_budget(ctx: ToolContext, adding: list[dict], place: str | None = None) -> dict:
    """Бюджет встречи SRD: опыт враждебных существ с множителем против порога отряда (раздел 8.1). Разделившийся
    отряд считается по месту: встречу в трюме держат только те, кто в трюме."""
    w = ctx.world
    party = [c for c in w.characters.values() if c.status in PLAYABLE and (place is None or w.place_of(c) == place)]
    if not party:
        return {"ok": True, "note": "в игре нет героев"}
    cap_idx, factor = DIFFICULTY_CAP.get(ctx.campaign.difficulty, (2, 1.0))
    cap = sum(ENCOUNTER_XP[max(1, min(20, int((c.sheet or {}).get("level", 1))))][cap_idx] for c in party) * factor
    xp = [x for x in adding]
    for en in ctx.world.in_scene_entities(place):
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
    bearing: Bearing | None = Field(None, description=BEARING_HINT)
    attitude: Literal["hostile", "neutral", "friendly"] = "hostile"
    description: str = Field(
        "",
        max_length=1000,
        description="внешность и манера, как их видят герои: это текст карточки для игроков. Мотивы и тайны сюда "
        "не пиши",
    )
    location_id: str | None = Field(None, description=PLACE_HINT)


@tool(
    "spawn_entity",
    "Выставляет существо или NPC из шаблона в текущую локацию. Враждебные проверяются бюджетом встречи.",
    SpawnArgs,
    ids={"creature_template_id": "templates:creature_template", "location_id": "places"},
)
async def spawn_entity(ctx: ToolContext, a: SpawnArgs) -> dict:
    from app.core.world import creature_stats

    rec = ctx.world.catalog.get(a.creature_template_id, "creature_template")
    creature_stats(rec.data)  # без блока статов существо в сцену не выходит
    place = ctx.world.place_arg(a.location_id, "появляется существо")
    if a.attitude == "hostile":
        b = encounter_budget(ctx, [{"xp": int(rec.data.get("xp") or 0)} for _ in range(a.count)], place)
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
            state={"hp": hp, "hp_max": hp, "attitude": a.attitude, **({"bearing": a.bearing} if a.bearing else {})},
            location_id=place,
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
    bearing: Bearing | None = Field(None, description=BEARING_HINT)
    elevation: Elevation | None = Field(None, description=ELEVATION_HINT)
    cover: Cover | None = Field(None, description=COVER_HINT)
    fled: bool | None = Field(None, description="существо ушло со сцены")


@tool(
    "update_entity",
    "Меняет нарративные поля сущности: отношение, настроение, зону и сторону на схеме, пометки. Хиты и статы так "
    "не меняются.",
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
    was = {x.id for x in areas_at(ctx.world, en.id)} if en.kind == "creature" else set()
    st = dict(en.state or {})
    changes = {}
    for k in ("attitude", "mood", "note", "bearing", "elevation", "cover"):
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
    out = {"entity": en.name, **changes}
    if en.kind == "creature" and en.location_id is not None:
        hit = await enter_areas(ctx, en.id, was)
        if hit:
            out["areas"] = hit
    return out


# --- позиции и области (app/core/positions.py) ---


async def _area_hits(ctx: ToolContext, area: Entity, actor_id: str) -> dict:
    """Участник оказался в области: опасность и эффект области по шаблонам."""
    ar = (area.state or {}).get("area") or {}
    tgt = ctx.world.actor(actor_id)
    out: dict = {"area": area.name, "who": tgt.name}
    if not tgt.alive:
        return out
    if ar.get("hazard_template_id"):
        rec = ctx.world.catalog.get(ar["hazard_template_id"], "hazard_template")
        out["hazard"] = await _hazard_on(ctx, rec, tgt)
    if ar.get("effect_template_id"):
        rec = ctx.world.catalog.get(ar["effect_template_id"], "effect_template")
        left = ar.get("expires_at")
        dur = int(left) - ctx.world.scene.game_time if left is not None else None
        eff, note = await fx.add_effect(ctx, ctx.world.actor(actor_id), rec, dur)
        await ctx.record(
            "apply_effect",
            target_id=actor_id,
            payload={"target": tgt.name, "effect": rec.name, "note": note, "area": area.name},
            inverse=[{"table": "active_effects", "op": "delete", "id": eff.id}] if eff is not None else [],
        )
        out["effect"] = rec.name
        ctx.world.invalidate(actor_id)
    return out


async def enter_areas(ctx: ToolContext, actor_id: str, before: set[str]) -> list[dict]:
    """Области, в которые участник вошёл этим перемещением (SRD: действует при входе)."""
    return [await _area_hits(ctx, e, actor_id) for e in areas_at(ctx.world, actor_id) if e.id not in before]


class RepositionArgs(BaseModel):
    actor_id: str = Field(description="герой или существо")
    zone: Literal["center", "melee", "near", "far"] | None = Field(
        None, description="где от центра отряда: center — в строю отряда, melee — вплотную, near — близко, far — далеко"
    )
    bearing: Bearing | None = Field(None, description="в какой стороне; n — север (вверх схемы)")
    elevation: Elevation | None = Field(None, description=ELEVATION_HINT)
    cover: Cover | None = Field(None, description=COVER_HINT)


@tool(
    "reposition",
    "Перемещает героя или существо внутри сцены: зона от центра отряда, сторона, высота, укрытие. В бою движение "
    "дальше скорости — рывок (тратит действие), дальше двух скоростей — нельзя.",
    RepositionArgs,
    ids={"actor_id": "combatants"},
    closes=False,
)
async def reposition(ctx: ToolContext, a: RepositionArgs) -> dict:
    w = ctx.world
    act = w.actor(a.actor_id)
    before = pos_of(w, act.id)
    was = {x.id for x in areas_at(w, act.id)}
    after = Pos(before.zone, before.bearing, before.elevation, before.cover)
    if a.zone is not None:
        after.zone = None if a.zone == "center" else a.zone
        if a.zone == "center":
            after.bearing = None
    if a.bearing is not None:
        after.bearing = a.bearing
    if a.elevation is not None:
        after.elevation = a.elevation
    if a.cover is not None:
        after.cover = a.cover
    if act.kind == "creature" and after.zone is None:
        raise ToolError("существо не встаёт в строй отряда: укажите melee, near или far")
    moved = 0
    if (after.zone, after.bearing, after.elevation) != (before.zone, before.bearing, before.elevation):
        moved = distance(before, after)
    out: dict = {"who": act.name, "position": after.public(), "moved_ft": moved}
    if combat.in_combat(ctx) and ctx.world.in_fight(act.id) and moved:
        if moved > 2 * act.speed:
            raise ToolError(
                f"{act.name} проходит за ход не больше {2 * act.speed} футов с рывком, а тут {moved}: "
                "переместите ближе, остальное — следующим ходом"
            )
        if moved > act.speed:
            out["note"] = f"рывок: {moved} футов больше скорости {act.speed}, действие потрачено на рывок"
    if act.kind == "character":
        sc = w.scene
        inverse = [{"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(sc.state)}]
        positions = hero_positions(sc)
        positions[act.id] = after.public()
        sc.state = {**(sc.state or {}), "positions": positions}
    else:
        en = w.entities[act.id]
        inverse = [
            {"table": "entities", "id": en.id, "field": "state", "before": copy.deepcopy(en.state)},
            {"table": "entities", "id": en.id, "field": "zone", "before": en.zone},
        ]
        en.zone = after.zone or en.zone
        st = {**(en.state or {}), "elevation": after.elevation, "cover": after.cover}
        if after.bearing:
            st["bearing"] = after.bearing
        en.state = st
    w.invalidate(act.id)
    await ctx.record("reposition", actor_id=act.id, target_id=act.id, payload=out, inverse=inverse)
    hit = await enter_areas(ctx, act.id, was)
    if hit:
        out["areas"] = hit
    return out


class AreaArgs(BaseModel):
    name: str = Field(max_length=80, description="что это: «Облако трупного газа», «Горящее масло», «Туман»")
    zone: Zone = "near"
    bearing: Bearing | None = Field(None, description="где центр области; n — север (вверх)")
    radius_ft: Literal[5, 10, 15, 20, 30] = Field(10, description="радиус области в футах")
    hazard_template_id: str | None = Field(None, description="опасность по шаблону: срабатывает на тех, кто внутри")
    effect_template_id: str | None = Field(None, description="эффект или состояние на тех, кто внутри")
    duration_rounds: int | None = Field(
        None, ge=1, le=600, description="сколько раундов держится; пусто — пока не уберут"
    )
    location_id: str | None = Field(None, description=PLACE_HINT)


@tool(
    "place_area",
    "Отмечает на схеме область: облако, огонь, туман, лужу масла. Опасность и эффект из шаблонов срабатывают на "
    "всех внутри сразу и на тех, кто войдёт потом.",
    AreaArgs,
    ids={
        "hazard_template_id": "templates:hazard_template",
        "effect_template_id": "templates:effect_template",
        "location_id": "places",
    },
    closes=False,
)
async def place_area(ctx: ToolContext, a: AreaArgs) -> dict:
    w = ctx.world
    if w.scene.location_id is None:
        raise ToolError("у сцены нет места; сначала create_location с make_current")
    place = w.place_arg(a.location_id, "область")
    if a.hazard_template_id:
        rec = w.catalog.get(a.hazard_template_id, "hazard_template")
        if rec.data.get("params_schema"):
            raise ToolError(f"опасности {rec.name} нужны параметры: примените её apply_hazard к каждой цели")
    if a.effect_template_id:
        w.catalog.get(a.effect_template_id, "effect_template")
    area: dict = {"radius_ft": a.radius_ft}
    for k in ("hazard_template_id", "effect_template_id"):
        if getattr(a, k):
            area[k] = getattr(a, k)
    if a.duration_rounds:
        area["expires_at"] = w.scene.game_time + a.duration_rounds * 6
    en = Entity(
        campaign_id=ctx.campaign.id,
        kind="object",
        name=a.name,
        state={"area": area, "landmark": True, **({"bearing": a.bearing} if a.bearing else {})},
        location_id=place,
        zone=a.zone,
    )
    ctx.session.add(en)
    await ctx.session.flush()
    w.entities[en.id] = en
    await ctx.record(
        "place_area",
        target_id=en.id,
        payload={"name": a.name, "zone": a.zone, "radius_ft": a.radius_ft},
        inverse=[{"table": "entities", "op": "delete", "id": en.id}],
    )
    ids = [c.id for c in w.characters.values() if c.status in PLAYABLE] + [
        e.id for e in w.in_scene_entities(place) if e.kind == "creature" and not (e.state or {}).get("dead")
    ]
    caught = [i for i in ids if inside(w, en, i)]
    hits = [await _area_hits(ctx, en, i) for i in caught]
    return {"area_id": en.id, "name": a.name, "inside": [w.actor(i).name for i in caught], "hits": hits}


class RemoveAreaArgs(BaseModel):
    area_id: str


@tool("remove_area", "Убирает область со схемы: облако рассеялось, огонь погас.", RemoveAreaArgs, closes=False)
async def remove_area(ctx: ToolContext, a: RemoveAreaArgs) -> dict:
    en = ctx.world.entities.get(a.area_id)
    if en is None or not (en.state or {}).get("area"):
        ids = ", ".join(f"{e.id} {e.name}" for e in active_areas(ctx.world)) or "нет"
        raise ToolError(f"нет области {a.area_id}; области сцены: {ids}")
    inverse = [{"table": "entities", "id": en.id, "field": "location_id", "before": en.location_id}]
    en.location_id = None
    await ctx.record("remove_area", target_id=en.id, payload={"name": en.name}, inverse=inverse)
    return {"removed": en.name}


class CreateLocationArgs(BaseModel):
    name: str = Field(max_length=128)
    description: str = Field(
        "", max_length=2000, description="как место выглядит для героев: это текст карточки для игроков, без тайн"
    )
    template_id: str | None = Field(None, description="шаблон локации пакета, если есть подходящий")
    make_current: bool = Field(False, description="сразу сделать текущей локацией сцены")
    parent_id: str | None = Field(None, description="внутри какого места находится: район туши, дом на улице, комната")
    link_to: list[str] = Field(
        default_factory=list, max_length=6, description="соседние места, куда отсюда можно пройти (появятся на карте)"
    )
    via: str | None = Field(None, max_length=40, description="чем связаны с соседями: лестница, переулок, тоннель")
    bearing: Bearing | None = Field(None, description="в какой стороне от текущего места; n — север (вверх)")
    secret: bool = Field(False, description="тайное место: на карте только после того, как герои его нашли")


def _link(a: Entity, b_id: str, label: str | None = None, bearing: str | None = None) -> bool:
    """Путь между местами хранится у места ``a`` в ``state.links``. Повтор не добавляет второй путь."""
    st = dict(a.state or {})
    links = list(st.get("links") or [])
    if any(x.get("to") == b_id for x in links):
        return False
    links.append({"to": b_id, **({"label": label} if label else {}), **({"bearing": bearing} if bearing else {})})
    st["links"] = links
    a.state = st
    return True


def _linked(ctx: ToolContext, a: Entity, b: Entity) -> bool:
    """Места уже связаны на карте: путь в любую сторону или одно внутри другого."""
    return (
        a.location_id == b.id
        or b.location_id == a.id
        or any(x.get("to") == b.id for x in (a.state or {}).get("links") or [])
        or any(x.get("to") == a.id for x in (b.state or {}).get("links") or [])
    )


def _connect(ctx: ToolContext, a: Entity, b: Entity, inverse: list) -> None:
    """Герои прошли из ``a`` в ``b``: путь отмечается на карте, если места ещё не связаны."""
    if a.id != b.id and not _linked(ctx, a, b):
        inverse.append({"table": "entities", "id": a.id, "field": "state", "before": copy.deepcopy(a.state)})
        _link(a, b.id)


def _visit(ctx: ToolContext, loc: Entity, heroes: list[Character], inverse: list) -> None:
    st = dict(loc.state or {})
    seen = list(st.get("visited_by") or [])
    new = [h.id for h in heroes if h.id not in seen]
    if not new:
        return
    inverse.append({"table": "entities", "id": loc.id, "field": "state", "before": copy.deepcopy(loc.state)})
    st["visited_by"] = seen + new
    loc.state = st


def _reset_positions(ctx: ToolContext, inverse: list) -> None:
    """В новом месте герои снова стоят в строю отряда."""
    sc = ctx.world.scene
    if hero_positions(sc):
        inverse.append({"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(sc.state)})
        sc.state = {k: v for k, v in (sc.state or {}).items() if k != "positions"}


def relocate_scene(ctx: ToolContext, loc: Entity, inverse: list) -> None:
    """Сцена переходит в новое место вместе с героями, которые стояли в старом: место отмечается посещённым,
    а старое и новое связываются на карте, если ещё не связаны."""
    old_id = ctx.world.scene.location_id
    old = ctx.world.entities.get(old_id or "")
    party = [c for c in ctx.world.characters.values() if c.status in PLAYABLE]
    going = [c for c in party if (c.location_id or old_id) == old_id]
    if old is not None and old.id != loc.id:
        _visit(ctx, old, going, inverse)
        _connect(ctx, old, loc, inverse)
    for c in going:
        if c.location_id is not None and c.location_id != loc.id:
            inverse.append({"table": "characters", "id": c.id, "field": "location_id", "before": c.location_id})
            c.location_id = loc.id
    inverse.append({"table": "scenes", "id": ctx.campaign.id, "field": "location_id", "before": old_id})
    _reset_positions(ctx, inverse)
    ctx.world.scene.location_id = loc.id
    _visit(ctx, loc, going, inverse)


@tool(
    "create_location",
    "Регистрирует локацию в реестре мира (по шаблону пакета, если он есть). Место сразу попадает на карту героев: "
    "укажи, внутри чего оно и с какими местами соседствует.",
    CreateLocationArgs,
    ids={"parent_id": "locations", "link_to": "locations"},
    closes=False,
)
async def create_location(ctx: ToolContext, a: CreateLocationArgs) -> dict:
    state: dict = {}
    if a.template_id:
        rec = ctx.world.catalog.get(a.template_id, "location_template")
        if rec.data.get("dc") is not None:
            state["dc"] = rec.data["dc"]
    if a.bearing:
        state["bearing"] = a.bearing
    if a.secret:
        state["secret"] = True
    en = Entity(
        campaign_id=ctx.campaign.id,
        kind="location",
        name=a.name,
        template_id=a.template_id,
        description=a.description,
        state=state,
        location_id=a.parent_id,
    )
    ctx.session.add(en)
    await ctx.session.flush()
    ctx.world.entities[en.id] = en
    inverse = [{"table": "entities", "op": "delete", "id": en.id}]
    for other in dict.fromkeys(a.link_to):
        if other != en.id:
            _link(en, other, a.via)
    if a.make_current:
        relocate_scene(ctx, en, inverse)
    await ctx.record(
        "create_location",
        target_id=en.id,
        payload={"name": a.name, "current": a.make_current, "parent": a.parent_id, "links": a.link_to},
        inverse=inverse,
    )
    return {"location_id": en.id, "name": a.name, "current": a.make_current}


class LinkArgs(BaseModel):
    from_id: str
    to_id: str
    via: str | None = Field(None, max_length=40, description="чем связаны: лестница, переулок, тоннель, люк")
    bearing: Bearing | None = Field(None, description="в какой стороне от from_id; n — север (вверх)")


@tool(
    "link_locations",
    "Отмечает на карте путь между двумя местами реестра: герои нашли проход, лестницу, тоннель.",
    LinkArgs,
    ids={"from_id": "locations", "to_id": "locations"},
    closes=False,
)
async def link_locations(ctx: ToolContext, a: LinkArgs) -> dict:
    if a.from_id == a.to_id:
        raise ToolError("место не связывают само с собой")
    src, dst = ctx.world.entities[a.from_id], ctx.world.entities[a.to_id]
    before = copy.deepcopy(src.state)
    if not _link(src, dst.id, a.via, a.bearing):
        return {"linked": False, "note": "путь уже отмечен"}
    await ctx.record(
        "link_locations",
        target_id=src.id,
        payload={"from": src.name, "to": dst.name, "via": a.via},
        inverse=[{"table": "entities", "id": src.id, "field": "state", "before": before}],
    )
    return {"linked": True, "from": src.name, "to": dst.name}


class LandmarkArgs(BaseModel):
    name: str = Field(max_length=128, description="что видно: «Фонтан с костяной чашей», «Запертая дверь»")
    description: str = Field("", max_length=1000, description="как это выглядит для героев, без тайн")
    zone: Zone = "near"
    bearing: Bearing | None = Field(None, description=BEARING_HINT)
    location_id: str | None = Field(None, description=PLACE_HINT)


@tool(
    "add_landmark",
    "Отмечает на схеме места заметную примету: дверь, статую, лавку, провал. Механики у приметы нет: для существ — "
    "spawn_entity, для отдельного места, куда можно войти, — create_location.",
    LandmarkArgs,
    ids={"location_id": "places"},
    closes=False,
)
async def add_landmark(ctx: ToolContext, a: LandmarkArgs) -> dict:
    if ctx.world.scene.location_id is None:
        raise ToolError("у сцены нет места; сначала create_location с make_current")
    place = ctx.world.place_arg(a.location_id, "примета")
    en = Entity(
        campaign_id=ctx.campaign.id,
        kind="object",
        name=a.name,
        description=a.description,
        state={"landmark": True, **({"bearing": a.bearing} if a.bearing else {})},
        location_id=place,
        zone=a.zone,
    )
    ctx.session.add(en)
    await ctx.session.flush()
    ctx.world.entities[en.id] = en
    await ctx.record(
        "add_landmark",
        target_id=en.id,
        payload={"name": a.name, "zone": a.zone},
        inverse=[{"table": "entities", "op": "delete", "id": en.id}],
    )
    return {"landmark_id": en.id, "name": a.name}


class SketchExit(BaseModel):
    name: str = Field(min_length=1, max_length=60, description="как его видят герои: «Дверь решётки», «Узкое окно»")
    side: Literal["n", "e", "s", "w"] = Field(description="край места: n — северный (верх схемы)")
    at: int = Field(ge=0, description="клетка на этом краю: для n и s — столбец, для e и w — строка, с нуля")
    kind: Literal["door", "bars", "window", "arch", "stairs", "hatch", "gap", "passage"] = "door"
    state: Literal["open", "closed", "locked"] = "open"
    to: str | None = Field(None, description="место реестра, куда ведёт, если оно уже есть")
    beyond: str | None = Field(None, max_length=60, description="что видно или известно за ним: «тёмный коридор»")
    hidden: bool = Field(False, description="тайный выход: игроки не видят, пока не найдут")


class SketchFeature(BaseModel):
    name: str = Field(min_length=1, max_length=60, description="«Каменный стол», «Колонна», «Жаровня»")
    kind: Literal["furniture", "cover", "hazard", "light", "object", "nature"] = "object"
    cells: list[list[int]] = Field(
        min_length=1, max_length=4, description="прямоугольники [c0, r0, c1, r1] от северо-западной клетки"
    )
    cover: Literal["none", "half", "three_quarters", "total"] = "none"
    hidden: bool = Field(False, description="игроки не видят, пока не найдут")


class SketchArgs(BaseModel):
    shape: Literal["room", "corridor", "cave", "street", "open"] = "room"
    cols: int = Field(ge=1, le=sketch.MAX_SIDE, description="ширина с запада на восток, клеток по 5 футов")
    rows: int = Field(ge=1, le=sketch.MAX_SIDE, description="длина с севера на юг, клеток по 5 футов")
    party: list[int] = Field(min_length=2, max_length=2, description="клетка [c, r], где сейчас стоит отряд")
    walls: list[list[int]] = Field(
        default_factory=list, max_length=sketch.MAX_WALLS, description="непроходимые клетки [c, r]: колонны, обвал"
    )
    exits: list[SketchExit] = Field(default_factory=list, max_length=sketch.MAX_EXITS)
    features: list[SketchFeature] = Field(default_factory=list, max_length=sketch.MAX_FEATURES)
    location_id: str | None = Field(None, description=PLACE_HINT)


@tool(
    "sketch_place",
    "Эскиз места для схемы игроков: форма и размер в клетках по 5 футов, где стоит отряд, входы и выходы (дверь, "
    "решётка, окно, лестница) и что за ними, крупные предметы в поле зрения. Клетка (0, 0) — северо-западный угол. "
    "Новый вызов заменяет эскиз целиком. Существ сюда не клади — для них spawn_entity.",
    SketchArgs,
    ids={"location_id": "places"},
    closes=False,
)
async def sketch_place(ctx: ToolContext, a: SketchArgs) -> dict:
    w = ctx.world
    if w.scene.location_id is None:
        raise ToolError("у сцены нет места; сначала create_location с make_current")
    place = w.entities[w.place_arg(a.location_id, "эскиз")]
    for f in a.features:
        if any(len(c) != 4 for c in f.cells):
            raise ToolError(f"«{f.name}»: каждая клетка предмета — [c0, r0, c1, r1]")
    if any(len(c) != 2 for c in a.walls):
        raise ToolError("стена — клетка [c, r]")
    data = a.model_dump(exclude={"location_id"})
    data["walls"] = [list(x) for x in dict.fromkeys(tuple(c) for c in a.walls)]
    places = {e.id for e in w.entities.values() if e.kind == "location"}
    errors = sketch.check(data, places)
    if errors:
        raise ToolError("; ".join(errors[:8]))
    before = copy.deepcopy(place.state)
    for x in data["exits"]:
        if x["to"] and x["to"] != place.id and not _linked(ctx, place, w.entities[x["to"]]):
            _link(place, x["to"], x["name"])  # выход в известное место — путь и на карте мест
    place.state = {**(place.state or {}), "sketch": data}
    await ctx.record(
        "sketch_place",
        target_id=place.id,
        payload={"place": place.name, "size": [a.cols, a.rows], "exits": len(a.exits), "features": len(a.features)},
        inverse=[{"table": "entities", "id": place.id, "field": "state", "before": before}],
    )
    return {"place": place.name, "sketch": sketch.describe(data)}


class MoveArgs(BaseModel):
    character_ids: list[str] = Field(min_length=1)
    location_id: str


@tool(
    "move",
    "Перемещает героев в локацию реестра. Если уходят все герои — локация становится текущей сценой. Путь сам "
    "отмечается на карте.",
    MoveArgs,
    ids={"character_ids": "characters", "location_id": "locations"},
)
async def move(ctx: ToolContext, a: MoveArgs) -> dict:
    loc = ctx.world.entities.get(a.location_id)
    if loc is None or loc.kind != "location":
        raise ToolError(f"нет локации {a.location_id}; сначала create_location")
    inverse: list = []
    dice: list = []
    joined = await move_heroes(ctx, [_character(ctx, cid) for cid in a.character_ids], loc, inverse, dice)
    await ctx.record(
        "move",
        target_id=loc.id,
        payload={"characters": a.character_ids, "location": loc.name, **joined},
        dice=dice or None,
        inverse=inverse,
    )
    return {"moved": a.character_ids, "location": loc.name, "scene_location": ctx.world.scene.location_id, **joined}


class EnterRoomArgs(BaseModel):
    room: str = Field(min_length=1, max_length=40, description="номер комнаты на карте книги или её id")
    character_ids: list[str] = Field(
        default_factory=list, description="кто входит; пусто — все герои, что стоят там же, где сцена"
    )
    location_id: str | None = Field(
        None, description="место модуля или комната в нём, откуда идут; нужно, только если отряд разделён"
    )


@tool(
    "enter_room",
    "Готовое приключение: герои входят в комнату места по номеру из книги. Комната и соседние с ней появляются в "
    "реестре и на карте; в ответе — комната целиком по книге (текст вслух, проверки, существа, сокровища, тайное).",
    EnterRoomArgs,
    ids={"character_ids": "characters", "location_id": "places"},
)
async def enter_room(ctx: ToolContext, a: EnterRoomArgs) -> dict:
    w = ctx.world
    start = w.place_arg(a.location_id, "отряд входит в комнату")
    found = adventure.module_place(w.entities.get(start or ""), w.catalog, w.entities)
    if found is None:
        raise ToolError("герои не в месте готового приключения: сначала разверни место каркаса через develop")
    place, rec = found
    room = adventure.find_room(rec, a.room)
    if room is None:
        listed = "; ".join(adventure.room_title(r) for r in adventure.rooms(rec))
        raise ToolError(f"в месте «{rec.name}» нет комнаты {a.room}. Комнаты: {listed}")
    inverse: list = []

    async def ensure(r: dict) -> Entity:
        en = adventure.room_entity(w.entities, place, r["id"])
        if en is None:
            en = adventure.new_room(ctx.campaign.id, place, rec, r)
            ctx.session.add(en)
            await ctx.session.flush()
            w.entities[en.id] = en
            inverse.insert(0, {"table": "entities", "op": "delete", "id": en.id})
        return en

    target = await ensure(room)
    for rid in room.get("exits") or []:
        other = adventure.find_room(rec, rid)
        if other is not None:
            nxt = await ensure(other)
            if not _linked(ctx, target, nxt):
                inverse.append(
                    {"table": "entities", "id": target.id, "field": "state", "before": copy.deepcopy(target.state)}
                )
                _link(target, nxt.id)
    if a.character_ids:
        heroes = [_character(ctx, cid) for cid in a.character_ids]
    else:
        heroes = [c for c in w.characters.values() if c.status in PLAYABLE and w.place_of(c) == start]
    if not heroes:
        raise ToolError("некому входить: назови героев в character_ids")
    dice: list = []
    joined = await move_heroes(ctx, heroes, target, inverse, dice)
    await ctx.record(
        "enter_room",
        target_id=target.id,
        payload={"characters": [h.id for h in heroes], "location": target.name, "room": room.get("number"), **joined},
        dice=dice or None,
        inverse=inverse,
    )
    return {
        "room_id": target.id,
        "moved": [h.id for h in heroes],
        "book": adventure.room_text(rec, room, target, w.catalog, w.entities),
        **joined,
    }


async def move_heroes(ctx: ToolContext, heroes: list[Character], loc: Entity, inverse: list, dice: list) -> dict:
    """Герои переходят в место ``loc``: посещения и пути на карте, вход в бой и выход из него, сцена — за отрядом."""
    scene_loc = ctx.world.scene.location_id
    moved = []
    for ch in heroes:
        was = ctx.world.entities.get(ch.location_id or scene_loc or "")
        if was is not None and was.id != loc.id:
            _visit(ctx, was, [ch], inverse)
            _connect(ctx, was, loc, inverse)
        inverse.append({"table": "characters", "id": ch.id, "field": "location_id", "before": ch.location_id})
        ch.location_id = loc.id
        moved.append(ch)
    _visit(ctx, loc, moved, inverse)
    joined = await _move_in_combat(ctx, moved, inverse, dice)
    party = [c for c in ctx.world.characters.values() if c.status in PLAYABLE]
    if all(c.location_id == loc.id for c in party):
        inverse.append(
            {"table": "scenes", "id": ctx.campaign.id, "field": "location_id", "before": ctx.world.scene.location_id}
        )
        if ctx.world.scene.location_id != loc.id:
            _reset_positions(ctx, inverse)
        ctx.world.scene.location_id = loc.id
    return joined


async def _move_in_combat(ctx: ToolContext, moved: list, inverse: list, dice: list) -> dict:
    """Идёт бой: герой, ушедший из места боя, выходит из очереди; пришедший в место боя бросает инициативу и
    встаёт в очередь (5e: опоздавший вступает в бой)."""
    if not combat.in_combat(ctx):
        return {}
    sc = ctx.world.scene
    inverse += [
        {"table": "scenes", "id": ctx.campaign.id, "field": f, "before": copy.deepcopy(getattr(sc, f))}
        for f in ("mode", "round", "turn_order", "state")
    ]
    fronts = {combat._at(ctx, x["id"]) for x in sc.turn_order if x["id"] not in ctx.world.characters}
    have = {x["id"] for x in sc.turn_order}
    out: dict = {}
    left = combat.drop(ctx, {ch.id for ch in moved if ch.id in have and ch.location_id not in fronts})
    if left:
        out["left_combat"] = [ctx.world.characters[i].name for i in left]
    came = [ch.id for ch in moved if ch.id not in have and ch.location_id in fronts]
    if came:
        entries, rolls_ = roll_initiative(ctx, came)
        combat.insert(ctx, entries)
        dice += rolls_
        out["joined_combat"] = [f"{ctx.world.characters[e['id']].name} ({e['initiative']})" for e in entries]
    if not sc.turn_order:  # в бою никого не осталось
        sc.mode, sc.round = "free", 0
        combat.end_combat(ctx)
        audio.on_mode(ctx, "free")
    return out


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
    w = ctx.world
    if a.mode == "free":
        # отряд разделён: ход группы заканчивает только свой бой, бой другой части отряда идёт дальше
        mine = set(w.scene_places())
        elsewhere = [p for p, end in combat.active_fronts(ctx).items() if end is None and p not in mine]
        if w.focus and combat.in_combat(ctx) and elsewhere:
            left = combat.drop(ctx, {x["id"] for x in sc.turn_order if combat._at(ctx, x["id"]) in mine})
            await ctx.record("set_scene_mode", payload={"mode": "free", "left": left}, inverse=inverse)
            if left:
                audio.on_mode(ctx, "free")
            return {"mode": "free", "note": "здесь боя нет; в другом месте отряд ещё сражается"}
        won = sc.mode == "combat" and bool(combat._heroes_standing(ctx)) and not combat._hostiles_left(ctx)
        sc.mode, sc.round, sc.turn_order = "free", 0, []
        combat.end_combat(ctx)
        audio.on_mode(ctx, "free", victory=won)
        await ctx.record("set_scene_mode", payload={"mode": "free"}, inverse=inverse)
        return {"mode": "free"}
    ids = a.participants
    joining = combat.in_combat(ctx)  # бой уже идёт: новые участники встают в очередь, начатый бой не сбрасывается
    if not ids:
        foes = [
            e
            for e in w.in_scene_entities()
            if e.kind == "creature" and (e.state or {}).get("attitude", "hostile") == "hostile"
        ]
        # отряд разделён: в бой вступают герои того места, где враги
        fronts = {e.location_id for e in foes} if w.split and foes else None
        ids = [
            c.id for c in w.characters.values() if c.status in PLAYABLE and (fronts is None or w.place_of(c) in fronts)
        ]
        ids += [e.id for e in foes]
    if joining:
        have = {x["id"] for x in sc.turn_order}
        ids = [i for i in ids if i not in have]
    entries, dice = roll_initiative(ctx, ids)
    if joining:
        combat.insert(ctx, entries)
        names = [f"{w.actor(e['id']).name} ({e['initiative']})" for e in entries]
        await ctx.record("set_scene_mode", payload={"mode": "combat", "joined": names}, dice=dice, inverse=inverse)
        return {"mode": "combat", "round": sc.round, "joined": names}
    sc.mode, sc.round = "combat", 1
    sc.turn_order = entries
    combat.start_combat(ctx)
    audio.on_mode(ctx, "combat")
    placed = _deploy(ctx, [e["id"] for e in entries], inverse)
    names = [f"{w.actor(e['id']).name} ({e['initiative']})" for e in entries]
    await ctx.record("set_scene_mode", payload={"mode": "combat", "order": sc.turn_order}, dice=dice, inverse=inverse)
    out = {"mode": "combat", "round": 1, "initiative": names}
    if placed:
        out["placed"] = (
            f"на схеме боя враги без стороны встали с одной стороны ({', '.join(placed)}); "
            "если по сцене они стоят иначе, поправь reposition"
        )
    return out


def _deploy(ctx: ToolContext, ids: list[str], inverse: list[dict]) -> list[str]:
    """Начало боя: враг без стороны света встаёт туда же, где уже стоят его товарищи (или на север), чтобы схема
    боя сразу показывала, кто где, а не разбрасывала врагов по кругу случайно."""
    w = ctx.world
    foes = [
        w.entities[i]
        for i in ids
        if i in w.entities
        and w.entities[i].kind == "creature"
        and (w.entities[i].state or {}).get("attitude", "hostile") == "hostile"
    ]
    side = next((e.state["bearing"] for e in foes if (e.state or {}).get("bearing")), "n")
    placed = []
    for e in foes:
        if (e.state or {}).get("bearing"):
            continue
        inverse.append({"table": "entities", "id": e.id, "field": "state", "before": copy.deepcopy(e.state)})
        e.state = {**(e.state or {}), "bearing": side}
        w.invalidate(e.id)
        ctx.changed.add(e.id)
        placed.append(e.name)
    return placed


def roll_initiative(ctx: ToolContext, ids: list[str]) -> tuple[list[dict], list[dict]]:
    """Броски инициативы: участники по убыванию и карточки бросков."""
    entries, dice = [], []
    for i in ids:
        act = ctx.world.actor(i)
        if not act.alive:
            continue
        # инициатива — проверка Ловкости (SRD): эффекты с преимуществом или помехой на неё действуют
        mode, reasons = mod.roll_mode(act.modifiers, "check", "dex")
        roll = engine.initiative(ctx.dice, act.mods["dex"], mode)
        entries.append((act.id, roll, act.mods["dex"]))
        dice.append({"who": act.id, **dice_json(roll), **({"reasons": reasons} if reasons else {})})
    totals = {e[0]: e[1].total for e in entries}
    return [{"id": i, "initiative": totals[i]} for i in engine.initiative_order(entries)], dice


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
    if ctx.world.in_fight() and a.unit == "round":
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
    for ch in ctx.world.characters.values():
        conc = (ch.resources or {}).get("concentration")
        if isinstance(conc, dict) and conc.get("until") is not None and conc["until"] <= ctx.world.scene.game_time:
            inverse.append(snapshot(ctx.world.actor(ch.id)))
            ch.resources = {k: v for k, v in ch.resources.items() if k != "concentration"}
            out.append(f"{ch.id}: концентрация на «{conc.get('name')}» закончилась")
            ctx.world.invalidate(ch.id)
            ctx.changed.add(ch.id)
    await ctx.session.flush()
    return out


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
