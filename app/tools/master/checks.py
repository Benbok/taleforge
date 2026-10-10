"""Проверки и бой: броски, атаки, спасброски от смерти, опасности и эффекты, области и инициатива."""

from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field

from app.core import adventure, economy
from app.core import positions as grid
from app.core.positions import COVER_AC, areas_at, pos_of
from app.core.world import PLAYABLE, ZONE_NAMES, Actor, format_time
from app.db.models import Character, Entity
from app.rules.dnd5e import features as cf
from app.rules.dnd5e import modifiers as mod
from app.rules.dnd5e.tables import ABILITIES, SKILLS
from app.tools import effects as fx
from app.tools.master.base import EDGE_HINT, Edge, _alive, _character, _hidden_skills, engine, snapshot
from app.tools.registry import ToolContext, ToolError, dice_json, tool

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
    as_bonus: bool = Field(
        False,
        description="удар бонусным действием героя (вторая рука, особенность класса); "
        "иначе удар идёт из действия «Атака» в его ход",
    )
    reckless: bool = Field(
        False,
        description="Безрассудная атака варвара (игрок заявил): рукопашные удары Силой этого хода с преимуществом, "
        "атаки по нему с преимуществом до его следующего хода",
    )
    stunning_strike: bool = Field(
        False, description="Оглушающий удар монаха (игрок заявил): при попадании в рукопашную 1 ци, спасбросок цели"
    )


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
    if grid.wall_between(w, att.id, tgt.id):
        raise ToolError(f"между {att.name} и {tgt.name} стена: прямой линии для атаки нет, сначала обойти")
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
    if a.reckless:
        _check_reckless(att, weapon)
    if a.stunning_strike:
        _check_stun(ctx, att, weapon)
    turn_inv = economy.charge_attack(ctx, att.id, a.as_bonus)
    reckless_inv = await _go_reckless(ctx, att) if a.reckless else []
    if reckless_inv:
        att = w.actor(att.id)
    target_ac = tgt.ac + COVER_AC.get(cover, 0)
    am = mod.attack_mods(att.modifiers, tgt.modifiers, dist, extra)
    mode, am_reasons = mod.with_circumstance(am.mode, list(am.reasons), a.edge, _edge_reason(a.edge, a.edge_reason))
    if _reckless_on(att) and weapon["kind"] == "melee" and weapon.get("ability", "str") == "str":
        mode, am_reasons = mod.with_circumstance(mode, am_reasons, "advantage", "Безрассудная атака")
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
    if weapon.get("magical"):
        result["magical"] = True
        if weapon.get("enchantment"):
            result["enchantment"] = weapon["enchantment"]
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
    inverse = [snapshot(tgt), *(spent or []), *turn_inv, *reckless_inv]
    if roll.hit:
        bonus = class_hit(ctx, att, tgt, weapon, mode, critical)
        result.update(bonus["notes"])
        dodge = uncanny_dodge(ctx, tgt)
        if dodge:
            result["uncanny_dodge"] = dodge
        expr = weapon["damage"] + (f"+{bonus['flat']}" if bonus["flat"] else "")
        o, droll = fx.damage_to(tgt, expr, weapon["damage_type"], critical, ctx.dice, half=bool(dodge))
        dice.append(droll)
        result.update({"damage": o["damage"], "damage_type": o["damage_type"], "target_status": o["status"]})
        for k in ("instant_death", "death_save_failures_added", "defenses"):
            if o.get(k):
                result[k] = o[k]
        extras = [*(weapon.get("extra_damage") or []), *bonus["extra"]]
        for extra_dmg in extras:
            if not tgt.alive:
                break
            crit = critical and not extra_dmg.get("no_crit")
            o2, r2 = fx.damage_to(tgt, extra_dmg["dice"], extra_dmg["type"], crit, ctx.dice, half=bool(dodge))
            dice.append(r2)
            result["damage"] += o2["damage"]
            result["target_status"] = o2["status"]
        if a.stunning_strike and tgt.alive:
            inverse.append(snapshot(att))
            result["stunning_strike"] = await _stun(ctx, att, w.actor(tgt.id), dice)
        if tgt.hp.dead:
            result["killed"] = True
        from app.tools.spells import concentration_check

        conc = await concentration_check(ctx, tgt, int(result["damage"]))
        if conc:
            result["concentration_check"] = conc
    await ctx.record("resolve_attack", actor_id=att.id, target_id=tgt.id, payload=result, dice=dice, inverse=inverse)
    w.invalidate(tgt.id)
    return result


# --- умения классов в атаке (SRD 5.1): ярость, скрытая атака, сильный крит, безрассудство, оглушение, уклонение ---


def _check_reckless(att: Actor, weapon: dict) -> None:
    if "reckless_attack" not in att.features:
        raise ToolError(f"{att.name}: Безрассудная атака — умение варвара 2-го уровня")
    if weapon["kind"] != "melee" or weapon.get("ability", "str") != "str":
        raise ToolError(f"{att.name}: Безрассудная атака — только рукопашный удар Силой")


async def _go_reckless(ctx: ToolContext, att: Actor) -> list[dict]:
    """Накладывает «Безрассудную атаку» на этот раунд: свои удары с преимуществом через edge, по нему — эффект."""
    rec = ctx.world.catalog.find("effect.feature_reckless", "effect_template")
    if rec is None or any(r.id == rec.id for _, r in att.effects):
        return []
    eff, _ = await fx.add_effect(ctx, att, rec, fx.duration_seconds(rec.data.get("duration")))
    return [{"table": "active_effects", "op": "delete", "id": eff.id}] if eff is not None else []


def _reckless_on(att: Actor) -> bool:
    return any(r.id == "effect.feature_reckless" for _, r in att.effects)


def _check_stun(ctx: ToolContext, att: Actor, weapon: dict) -> None:
    if "stunning_strike" not in att.features:
        raise ToolError(f"{att.name}: Оглушающий удар — умение монаха 5-го уровня")
    if weapon["kind"] != "melee":
        raise ToolError(f"{att.name}: Оглушающий удар — только рукопашная атака")
    _ki_after(ctx, att.obj, "Оглушающий удар")  # отказ до броска, если ци кончилась


async def _stun(ctx: ToolContext, att: Actor, tgt: Actor, dice: list) -> dict:
    """1 ци; цель — спасбросок Телосложения против Сл ци (8 + мастерство + Мудрость) или ошеломлена до конца
    следующего хода монаха (два раунда: эффекты снимаются на границе раунда)."""
    from app.tools.spells import spell_save

    spent, left = _ki_after(ctx, att.obj, "Оглушающий удар")
    att.obj.resources = {**(att.obj.resources or {}), "uses_spent": spent}
    ctx.world.invalidate(att.id)
    ctx.changed.add(att.id)
    dc = 8 + att.pb + att.mods["wis"]
    row = spell_save(ctx, tgt, "con", dc, dice)
    out = {"dc": dc, "save": row["total"], "success": row["success"], "ki_left": left}
    if not row["success"]:
        _, out["effect"] = await fx.add_effect(ctx, tgt, ctx.world.catalog.condition("stunned"), 12)
    return out


def class_hit(ctx: ToolContext, att: Actor, tgt: Actor, weapon: dict, mode, critical: bool) -> dict:
    """Прибавки умений класса к попаданию героя: ярость (к урону), скрытая атака (раз в ход), сильный крит."""
    out: dict = {"flat": 0, "extra": [], "notes": {}}
    if att.kind != "character":
        return out
    melee_str = weapon["kind"] == "melee" and weapon.get("ability", "str") == "str"
    if melee_str and any(r.id == "effect.feature_rage" for _, r in att.effects):
        out["flat"] = int(att.class_numbers.get("rage_damage_bonus") or 2)
        out["notes"]["rage_bonus"] = out["flat"]
    sneak = str(att.class_numbers.get("sneak_attack") or "")
    if "sneak_attack" in att.features and sneak and _sneak_ok(ctx, att, tgt, weapon, mode):
        out["extra"].append({"dice": sneak, "type": weapon["damage_type"]})
        out["notes"]["sneak_attack"] = sneak
        _mark_sneak(ctx, att.id)
    brutal = int(att.class_numbers.get("brutal_critical_dice") or 0)
    if critical and weapon["kind"] == "melee" and brutal and cf.has(att.features, "brutal_critical"):
        die = weapon["damage"].split("+")[0].split("-")[0]
        if "d" in die:
            size = die.split("d", 1)[1]
            out["extra"].append({"dice": f"{brutal}d{size}", "type": weapon["damage_type"], "no_crit": True})
            out["notes"]["brutal_critical"] = f"{brutal}d{size}"
    return out


def _sneak_ok(ctx: ToolContext, att: Actor, tgt: Actor, weapon: dict, mode) -> bool:
    """Скрытая атака (SRD): фехтовальное или дальнобойное оружие, раз в ход; преимущество или союзник героя
    в 5 футах от цели (и нет помехи)."""
    from app.rules.base import RollMode

    if weapon["kind"] != "ranged" and "finesse" not in (weapon.get("properties") or []):
        return False
    from app.core.combat import turn_marker

    marker = turn_marker(ctx.world.scene)
    if marker and ((ctx.world.scene.state or {}).get("sneak") or {}).get(att.id) == marker:
        return False
    if mode is RollMode.ADVANTAGE:
        return True
    if mode is RollMode.DISADVANTAGE:
        return False
    w = ctx.world
    for ch in w.characters.values():
        if ch.id == att.id or ch.status not in PLAYABLE:
            continue
        ally = w.actor(ch.id)
        if ally.conscious and not mod.can_act(ally.modifiers) and w.distance_ft(ally, tgt) <= 5:
            return True
    return False


def _mark_sneak(ctx: ToolContext, hero_id: str) -> None:
    from app.core.combat import turn_marker

    marker = turn_marker(ctx.world.scene)
    if not marker:
        return
    st = dict(ctx.world.scene.state or {})
    st["sneak"] = {**(st.get("sneak") or {}), hero_id: marker}
    ctx.world.scene.state = st


def uncanny_dodge(ctx: ToolContext, tgt: Actor) -> str | None:
    """Невероятное уклонение плута: реакцией половина урона от попавшей атаки. Сервер тратит реакцию сам, если она
    свободна и плут в сознании."""
    from app.core import combat

    if tgt.kind != "character" or "uncanny_dodge" not in tgt.features or not tgt.conscious:
        return None
    if mod.can_act(tgt.modifiers):
        return None
    if combat.in_combat(ctx):
        if not combat.reaction_available(ctx, tgt.id):
            return None
        combat.use_reaction(ctx, tgt.id)
    return f"{tgt.name} реакцией уходит от удара: урон вдвое меньше"


class ShoveArgs(BaseModel):
    attacker_id: str = Field(description="герой, который толкает цель вместо одной оружейной атаки")
    target_id: str = Field(description="существо, которое герой пытается опрокинуть или оттолкнуть")
    technique: Literal["prone", "push"] = Field(description="prone — сбить с ног; push — оттолкнуть от себя на 5 футов")


SIZE_ORDER = {"tiny": 0, "small": 1, "medium": 2, "large": 3, "huge": 4, "gargantuan": 5}


def _creature_size(ctx: ToolContext, actor: Actor) -> int:
    if actor.kind == "character":
        sheet = actor.obj.sheet or {}
        rec = ctx.world.catalog.find(sheet.get("origin_id") or "", "origin")
        size = (rec.data.get("size") if rec else None) or "medium"
    else:
        rec = ctx.world.catalog.find(actor.obj.template_id or "", "creature_template")
        size = rec.data.get("size", "medium") if rec else "medium"
    return SIZE_ORDER.get(str(size).lower(), 2)


@tool(
    "resolve_shove",
    "Толчок вместо одного удара: противоборство Атлетики героя и лучшей Атлетики/Акробатики цели. "
    "При успехе либо состояние «Сбит с ног», либо реальный сдвиг по сетке на 5 футов. "
    "Не добавляет урон, преимущество и оглушение по описанию игрока.",
    ShoveArgs,
    ids={"attacker_id": "characters", "target_id": "combatants"},
)
async def resolve_shove(ctx: ToolContext, a: ShoveArgs) -> dict:
    w = ctx.world
    attacker, target = w.actor(a.attacker_id), w.actor(a.target_id)
    if attacker.id == target.id:
        raise ToolError("себя толкнуть нельзя")
    _alive(attacker, "Толкающий")
    _alive(target, "Цель")
    if not attacker.conscious or mod.can_act(attacker.modifiers):
        raise ToolError(f"{attacker.name}: сейчас не может совершить толчок")
    if not economy.active(w, attacker.id):
        raise ToolError(f"{attacker.name}: толчок возможен только в свой ход боя")
    if w.actor_place(attacker.id) != w.actor_place(target.id) or w.distance_ft(attacker, target) > 5:
        raise ToolError(f"{target.name} слишком далеко: для толчка нужно находиться в пределах 5 футов")
    if grid.wall_between(w, attacker.id, target.id):
        raise ToolError("между существами стена: толкнуть через неё нельзя")
    if _creature_size(ctx, target) > _creature_size(ctx, attacker) + 1:
        raise ToolError(f"{target.name} слишком велик для толчка")

    destination = None
    if a.technique == "push":
        start, other = grid.pos_of(w, attacker.id).cell, grid.pos_of(w, target.id).cell
        if start is None or other is None or start == other:
            raise ToolError("для отталкивания нужна определённая позиция обоих существ на сетке")
        dx = (other[0] > start[0]) - (other[0] < start[0])
        dy = (other[1] > start[1]) - (other[1] < start[1])
        destination = (other[0] + dx, other[1] + dy)
        problem = grid.cell_problem(w, w.actor_place(target.id), destination, target.id)
        if problem:
            raise ToolError(f"оттолкнуть некуда: {problem}")

    inv = economy.charge_attack(ctx, attacker.id)
    atk_bonus, _ = attacker.ability_check_bonus("athletics")
    def_skill = max(("athletics", "acrobatics"), key=lambda skill: target.ability_check_bonus(skill)[0])
    def_bonus, def_ability = target.ability_check_bonus(def_skill)
    amode, _ = mod.roll_mode(attacker.modifiers, "check", "str", "athletics")
    dmode, _ = mod.roll_mode(target.modifiers, "check", def_ability, def_skill)
    aroll = engine.roll_d20(ctx.dice, atk_bonus, amode)
    droll = engine.roll_d20(ctx.dice, def_bonus, dmode)
    success = aroll.total > droll.total  # равенство в противоборстве оставляет положение прежним
    result = {
        "attacker": attacker.name,
        "target": target.name,
        "technique": a.technique,
        "attacker_total": aroll.total,
        "defender_total": droll.total,
        "defender_skill": def_skill,
        "success": success,
    }
    if success and a.technique == "prone":
        record = w.catalog.condition("prone")
        existing = next((e for e, r in target.effects if r.id == record.id), None)
        effect, note = await fx.add_effect(ctx, target, record, None)
        if effect is not None and existing is None:
            inv.append({"table": "active_effects", "op": "delete", "id": effect.id})
        result["effect"] = note
    elif success and destination is not None:
        if target.id in w.characters:
            inv.append(
                {"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(w.scene.state)}
            )
        else:
            inv.extend(
                [
                    {"table": "entities", "id": target.id, "field": "state", "before": copy.deepcopy(target.obj.state)},
                    {"table": "entities", "id": target.id, "field": "zone", "before": target.obj.zone},
                ]
            )
        grid.set_cell(w, target.id, destination)
        result["cell"] = list(destination)
    result["left"] = economy.line(w, attacker.id)
    await ctx.record(
        "resolve_shove",
        actor_id=attacker.id,
        target_id=target.id,
        payload=result,
        dice=[dice_json(aroll), dice_json(droll)],
        inverse=inv,
    )
    return result


class TakeActionArgs(BaseModel):
    character_id: str
    action: Literal["dash", "disengage", "dodge", "help", "hide", "ready", "search", "other"] = Field(
        description="dash — рывок (ещё скорость шагов), disengage — отход (без атак по возможности до конца хода), "
        "dodge — уклонение, help — помощь, hide — спрятаться, ready — подготовить действие, search — поиск, "
        "other — другое действие хода; толчок выполняется через resolve_shove"
    )
    bonus: bool = Field(
        False,
        description="бонусным действием: Хитрое действие плута (рывок, отход, засада), Терпеливая оборона "
        "(уклонение) и Поступь ветра (рывок или отход) монаха — сервер спишет 1 ци; other — другая особенность",
    )
    note: str | None = Field(None, max_length=200, description="что именно, если other или ready")


@tool(
    "take_action",
    "Герой в свой ход в бою тратит действие (или бонусное действие) на рывок, отход, уклонение, помощь, засаду, "
    "подготовку и поиск. Атака, толчок, заклинание и предмет тратят действие сами — отдельный вызов не нужен. "
    "Сервер откажет, если действие этого хода уже потрачено.",
    TakeActionArgs,
    ids={"character_id": "characters"},
    closes=False,
)
async def take_action(ctx: ToolContext, a: TakeActionArgs) -> dict:
    ch = _character(ctx, a.character_id)
    if not economy.active(ctx.world, ch.id):
        raise ToolError(f"{ch.name}: действия хода считаются только в бою и только в ход героя")
    ki = _bonus_source(ctx, ch, a.action) if a.bonus else None
    ki_spent = _ki_after(ctx, ch, ki) if ki else None  # сначала проверить запас, потом тратить действие
    before = snapshot(ctx.world.actor(ch.id))
    inverse = economy.charge(ctx, ch.id, a.action, a.bonus)
    out = {"character": ch.name, "action": economy.ACTIONS_RU.get(a.action, a.action), "bonus": a.bonus}
    if ki and ki_spent:
        inverse.append(before)
        spent, left = ki_spent
        ch.resources = {**(ch.resources or {}), "uses_spent": spent}
        ctx.world.invalidate(ch.id)
        ctx.changed.add(ch.id)
        out["ki"] = {"move": ki, "left": left}
    if a.note:
        out["note"] = a.note
    if a.action == "dodge":
        out["effect"] = (
            "до начала его следующего хода атаки по нему с помехой (edge), спасброски Ловкости с преимуществом"
        )
    out["left"] = economy.line(ctx.world, ch.id)
    await ctx.record("take_action", actor_id=ch.id, payload=out, inverse=inverse)
    return out


BONUS_BY_FEATURE = {"dash": "рывок", "disengage": "отход", "hide": "засада", "dodge": "уклонение"}


def _bonus_source(ctx: ToolContext, ch: Character, action: str) -> str | None:
    """Чем герой оплачивает рывок, отход, засаду или уклонение бонусным действием. Возвращает имя приёма монаха,
    если он стоит 1 ци; Хитрое действие плута бесплатно. Без такого умения — отказ."""
    if action not in BONUS_BY_FEATURE:
        return None
    have = ctx.world.actor(ch.id).features
    if "cunning_action" in have and action != "dodge":
        return None
    if "ki" in have and action in ("dash", "disengage"):
        return "Поступь ветра"
    if "ki" in have and action == "dodge":
        return "Терпеливая оборона"
    raise ToolError(
        f"{ch.name}: {BONUS_BY_FEATURE[action]} бонусным действием даёт только Хитрое действие плута или приём монаха "
        "за ци; иначе это действие хода (bonus=false)"
    )


def _ki_after(ctx: ToolContext, ch: Character, move: str) -> tuple[dict[str, int], int]:
    """Траты умений после приёма за 1 ци и сколько ци останется; отказ, если ци кончилась."""
    from app.core import features as feats
    from app.rules.dnd5e import rest as rest_rules

    act = ctx.world.actor(ch.id)
    pool = next((p for p in feats.pools_for(ch, ctx.world.catalog, act.mods, act.pb) if p.key == "ki"), None)
    if pool is None:
        raise ToolError(f"{ch.name}: у героя нет запаса ци")
    try:
        spent = rest_rules.use(pool, feats.spent_of(ch), 1)
    except rest_rules.RestError as e:
        raise ToolError(f"{ch.name}: {move} — {e}") from e
    return spent, pool.max - spent["ki"]


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


def _deploy(ctx: ToolContext, ids: list[str], inverse: list[dict]) -> tuple[list[str], bool]:
    """Начало боя: враг без стороны света встаёт туда же, где уже стоят его товарищи (или на север), чтобы схема
    боя сразу показывала, кто где, а не разбрасывала врагов по кругу случайно. Затем все без клетки встают на
    свободные клетки сетки."""
    w = ctx.world
    foes = [
        w.entities[i]
        for i in ids
        if i in w.entities
        and w.entities[i].kind == "creature"
        and (w.entities[i].state or {}).get("attitude", "hostile") == "hostile"
    ]
    for i in ids:
        if i in w.entities:
            en = w.entities[i]
            inverse.append({"table": "entities", "id": i, "field": "state", "before": copy.deepcopy(en.state)})
            inverse.append({"table": "entities", "id": i, "field": "zone", "before": en.zone})
    side = next((e.state["bearing"] for e in foes if (e.state or {}).get("bearing")), "n")
    placed = []
    for e in foes:
        if (e.state or {}).get("bearing"):
            continue
        e.state = {**(e.state or {}), "bearing": side}
        w.invalidate(e.id)
        ctx.changed.add(e.id)
        placed.append(e.name)
    # бой на сетке (решение Arty 2026-10-05): каждый участник встаёт на свою клетку возле своей зоны и стороны
    gridded = False
    for place in dict.fromkeys(w.actor_place(i) for i in ids):
        for aid, _ in grid.grid_deploy(w, place, [i for i in ids if w.actor_place(i) == place]):
            ctx.changed.add(aid)
            gridded = True
    return placed, gridded


def roll_initiative(ctx: ToolContext, ids: list[str]) -> tuple[list[dict], list[dict]]:
    """Броски инициативы: участники по убыванию и карточки бросков."""
    entries, dice = [], []
    for i in ids:
        act = ctx.world.actor(i)
        if not act.alive:
            continue
        # инициатива — проверка Ловкости (SRD): эффекты с преимуществом или помехой на неё действуют
        mode, reasons = mod.roll_mode(act.modifiers, "check", "dex")
        if "feral_instinct" in act.features:  # Дикий инстинкт варвара: инициатива с преимуществом
            mode, reasons = mod.with_circumstance(mode, reasons, "advantage", "Дикий инстинкт")
        roll = engine.initiative(ctx.dice, act.mods["dex"], mode)
        entries.append((act.id, roll, act.mods["dex"]))
        dice.append({"who": act.id, **dice_json(roll), **({"reasons": reasons} if reasons else {})})
    totals = {e[0]: e[1].total for e in entries}
    return [{"id": i, "initiative": totals[i]} for i in engine.initiative_order(entries)], dice
