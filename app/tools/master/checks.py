"""Проверки и бой: броски, атаки, спасброски от смерти, опасности и эффекты, области и инициатива."""

from __future__ import annotations

import json
from typing import Literal

from pydantic import BaseModel, Field

from app.core import adventure
from app.core.positions import areas_at
from app.core.world import Actor, WorldError, format_time
from app.db.models import Character, Entity
from app.rules import modifiers as mod
from app.rules.attributes import ABILITIES, SKILLS
from app.tools import effects as fx
from app.tools.master.base import EDGE_HINT, Edge, _alive, _hidden_skills, engine, snapshot
from app.tools.registry import ToolContext, ToolError, dice_json, tool

# --- проверки и бой ---


class CheckArgs(BaseModel):
    character_id: str = Field(description="кто бросает: персонаж или существо в сцене")
    target_id: str | None = Field(
        None, description="против кого или что исследует: цель социальной проверки, поиска, кражи"
    )
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
    ids={"character_id": "combatants", "target_id": "subjects", "difficulty": "dc"},
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
    from app.rules.dice import DiceError

    try:
        res = (engine.saving_throw if a.kind == "save" else engine.check)(
            ctx.dice, bonus, dc, mode, critical_checks(ctx)
        )
    except DiceError as error:
        # Only this validated check's typed dice failure is safe. Registry still
        # has to roll back (including inspiration) before granting admission.
        raise ToolError(str(error), code="check_dice_failure", category="technical_safe") from error
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
        "target_id": a.target_id,
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
        target_id=a.target_id,
        payload={"reason": a.reason, "difficulty": a.difficulty, **result},
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


# --- умения классов в атаке (SRD 5.1): ярость, скрытая атака, сильный крит, безрассудство, оглушение, уклонение ---


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
    reason: str = Field(min_length=3, max_length=200, description="почему наложено — увидят игрок и мастер")
    source: str | None = Field(
        None,
        max_length=120,
        description="кто или что наложил: id существа из таблицы сцены или короткое имя явления. Обязателен "
        "для состояний, чьи правила завязаны на источник (испуг, очарование)",
    )


@tool(
    "apply_effect",
    "Накладывает эффект или состояние из шаблона. Без длительности — длительность шаблона или пока не снимут. "
    "Сначала проверь правило состояния: испуганный не может приближаться к источнику, но отходить ему можно.",
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
    source = _effect_source(ctx, rec, a.source)
    eff, note = await fx.add_effect(ctx, tgt, rec, dur, source=source, reason=a.reason)
    result = {"target": tgt.name, "effect": rec.name, "note": note, "reason": a.reason}
    if source:
        result["source"] = source
    if eff is not None:
        result["effect_id"] = eff.id
        if eff.expires_at is not None:
            result["until"] = format_time(eff.expires_at)
    inverse = [{"table": "active_effects", "op": "delete", "id": eff.id}] if eff is not None else []
    ev = await ctx.record("apply_effect", target_id=tgt.id, payload=result, inverse=inverse)
    if eff is not None and eff.source_event_id is None:
        eff.source_event_id = ev.id
    return result


def _effect_source(ctx: ToolContext, rec, source: str | None) -> str | None:
    """Имя источника эффекта: id существа превращается в имя. Состояние, чьи правила смотрят на источник, без него
    не накладывается — иначе ни игрок, ни мастер потом не поймут, к кому нельзя приближаться."""
    if source and source.strip():
        try:
            return ctx.world.actor(source.strip()).name
        except WorldError:
            ent = ctx.world.entities.get(source.strip())
            return ent.name if ent is not None else source.strip()
    if "source" in json.dumps(rec.data.get("modifiers") or [], ensure_ascii=False):
        raise ToolError(f"у состояния {rec.name} правила завязаны на источник: укажите source — кто или что его вызвал")
    return None


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
