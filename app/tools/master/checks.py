"""Проверки и бой: броски, атаки, спасброски от смерти, опасности и эффекты, области и инициатива."""

from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field

from app.core import adventure, economy
from app.core import positions as grid
from app.core.positions import COVER_AC, areas_at, pos_of
from app.core.world import ZONE_NAMES, Actor, format_time
from app.db.models import Character, Entity
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
    turn_inv = economy.charge_attack(ctx, att.id, a.as_bonus)
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
    inverse = [snapshot(tgt), *(spent or []), *turn_inv]
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


class TakeActionArgs(BaseModel):
    character_id: str
    action: Literal["dash", "disengage", "dodge", "help", "hide", "ready", "search", "grapple", "other"] = Field(
        description="dash — рывок (ещё скорость шагов), disengage — отход (без атак по возможности до конца хода), "
        "dodge — уклонение, help — помощь, hide — спрятаться, ready — подготовить действие, search — поиск, "
        "grapple — захват или толчок (вместо одного удара атаки), other — другое действие хода"
    )
    bonus: bool = Field(False, description="бонусным действием: Хитрое действие плута, особенность класса")
    note: str | None = Field(None, max_length=200, description="что именно, если other или ready")


@tool(
    "take_action",
    "Герой в свой ход в бою тратит действие (или бонусное действие) на рывок, отход, уклонение, помощь, засаду, "
    "подготовку, поиск, захват. Атака, заклинание и предмет тратят действие сами — для них этот вызов не нужен. "
    "Сервер откажет, если действие этого хода уже потрачено.",
    TakeActionArgs,
    ids={"character_id": "characters"},
    closes=False,
)
async def take_action(ctx: ToolContext, a: TakeActionArgs) -> dict:
    ch = _character(ctx, a.character_id)
    if not economy.active(ctx.world, ch.id):
        raise ToolError(f"{ch.name}: действия хода считаются только в бою и только в ход героя")
    if a.action == "grapple":
        inverse = economy.charge_attack(ctx, ch.id, a.bonus)
    else:
        inverse = economy.charge(ctx, ch.id, a.action, a.bonus)
    out = {"character": ch.name, "action": economy.ACTIONS_RU.get(a.action, a.action), "bonus": a.bonus}
    if a.note:
        out["note"] = a.note
    if a.action == "dodge":
        out["effect"] = (
            "до начала его следующего хода атаки по нему с помехой (edge), спасброски Ловкости с преимуществом"
        )
    out["left"] = economy.line(ctx.world, ch.id)
    await ctx.record("take_action", actor_id=ch.id, payload=out, inverse=inverse)
    return out


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
        roll = engine.initiative(ctx.dice, act.mods["dex"], mode)
        entries.append((act.id, roll, act.mods["dex"]))
        dice.append({"who": act.id, **dice_json(roll), **({"reasons": reasons} if reasons else {})})
    totals = {e[0]: e[1].total for e in entries}
    return [{"id": i, "initiative": totals[i]} for i in engine.initiative_order(entries)], dice
