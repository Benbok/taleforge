"""Исполнение модификаторов записи на цели: опасности, предметы, эффекты (язык модификаторов, ТЗ, раздел 3.2).

Этап 3 исполняет ``extra_damage``, ``condition``, ``remove_condition``, ``save`` (с ``on_fail``, ``on_success``,
``on_fail_by_5``, ``half``), ``resource`` (хиты, временные хиты, истощение и ресурсы пакета) и ``add`` к временным
хитам. Остальные операции описывают постоянные свойства (их читает интерпретатор бросков) или ждут своих этапов:
такие модификаторы не исполняются и перечисляются в результате как ``skipped``.
"""

from __future__ import annotations

from typing import Any

from app.content.catalog import Entry
from app.core.world import Actor
from app.db.models import ActiveEffect
from app.rules.dice import parse
from app.rules.dnd5e import modifiers as mod
from app.rules.dnd5e.engine import Dnd5eEngine
from app.tools.registry import ToolContext, ToolError, dice_json

engine = Dnd5eEngine()
UNIT_SECONDS = {"round": 6, "minute": 60, "hour": 3600, "day": 86400}
MAX_DEPTH = 4


def duration_seconds(duration: Any) -> int | None:
    """``{unit, value}`` → секунды игрового времени. ``until_rest``/``permanent``/нет длительности → None."""
    if not isinstance(duration, dict):
        return None
    unit = duration.get("unit")
    if unit not in UNIT_SECONDS:
        return None
    return int(duration.get("value", 1)) * UNIT_SECONDS[unit]


def resolve_dc(ctx: ToolContext, value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value in {e.id for e in ctx.world.catalog.dc_scale()}:
        return int(ctx.world.catalog.get(value).data["value"])
    if isinstance(value, dict) and value.get("dc_ref"):
        return resolve_dc(ctx, value["dc_ref"])
    raise ToolError(f"сложность {value!r} не из данных: нужна запись шкалы сложностей")


async def add_effect(
    ctx: ToolContext, target: Actor, rec: Entry, duration: int | None, source_event_id: str | None = None
) -> tuple[ActiveEffect | None, str]:
    """Накладывает эффект. Иммунитет к состоянию — отказ без ошибки; нестакающийся эффект обновляет длительность."""
    name = rec.id.removeprefix("condition.")
    if rec.id.startswith("condition.") and name in target.condition_immunities:
        return None, f"{target.name}: иммунитет к состоянию {rec.name}"
    expires = ctx.world.scene.game_time + duration if duration else None
    existing = next((e for e, r in target.effects if r.id == rec.id), None)
    if existing is not None:
        if rec.data.get("stackable") or rec.data.get("levels"):
            existing.stacks = min(existing.stacks + 1, 6)
        if expires and (existing.expires_at is None or existing.expires_at < expires):
            existing.expires_at = expires
        ctx.world.invalidate(target.id)
        return existing, f"{target.name}: {rec.name} ×{existing.stacks}"
    e = ActiveEffect(
        campaign_id=ctx.campaign.id,
        target_id=target.id,
        effect_template_id=rec.id,
        stacks=1,
        expires_at=expires,
        source_event_id=source_event_id,
    )
    ctx.session.add(e)
    await ctx.session.flush()
    ctx.world.effects.append(e)
    ctx.world.invalidate(target.id)
    return e, f"{target.name}: {rec.name}"


async def remove_effect(ctx: ToolContext, target: Actor, effect_ref: str) -> ActiveEffect | None:
    e = next((e for e, r in target.effects if e.id == effect_ref or r.id == effect_ref), None)
    if e is None:
        return None
    if e.stacks > 1:
        e.stacks -= 1
    else:
        await ctx.session.delete(e)
        ctx.world.effects.remove(e)
    await ctx.session.flush()
    ctx.world.invalidate(target.id)
    return e


def damage_to(
    target: Actor, expr: str, damage_type: str, critical: bool, dice, half: bool = False
) -> tuple[dict, dict]:
    """Урон по цели с защитами и списанием хитов. ``half`` — половина после успешного спасброска
    (SRD: сначала делится урон, потом применяются сопротивления). Возвращает итог и бросок для журнала."""
    res = engine.damage(dice, expr, damage_type, critical=critical)
    raw = res.raw // 2 if half else res.raw
    final, applied = engine.apply_defenses(
        raw,
        damage_type,
        frozenset(target.resistances),
        frozenset(target.vulnerabilities),
        frozenset(target.immunities),
    )
    change = engine.apply_damage(target.hp, final, critical=critical)
    if target.kind == "creature" and target.hp.current == 0 and not target.hp.dead:
        target.hp.dead = True  # существа по SRD умирают на 0 хитов; спасброски от смерти — у героев
    target.save_hp()
    out = {
        "target_id": target.id,
        "damage": final,
        "damage_type": damage_type,
        "raw": res.raw,
        "defenses": list(applied) + (["half"] if half else []),
        "hp": [change.before, target.hp.current],
        "status": target.status(),
    }
    if change.instant_death:
        out["instant_death"] = True
    if change.death_save_failures_added:
        out["death_save_failures_added"] = change.death_save_failures_added
    return out, dice_json(res.roll)


async def run_ops(
    ctx: ToolContext,
    source: str,
    ops: list[dict],
    target: Actor,
    params: dict[str, Any] | None = None,
    depth: int = 0,
) -> dict[str, Any]:
    """Исполняет модификаторы записи на цели. Возвращает {outcomes, dice, skipped}."""
    out: dict[str, Any] = {"outcomes": [], "dice": [], "skipped": []}
    if depth > MAX_DEPTH:
        return out
    params = params or {}
    for m in ops or []:
        if not isinstance(m, dict):
            continue
        op = m.get("op")
        if "if" in m:
            out["skipped"].append(f"{op}: условие {m['if']} движок этапа 3 не проверяет")
            continue
        if op == "extra_damage" and m.get("dice"):
            expr = str(m["dice"])
            per = m.get("per")
            if isinstance(per, dict):  # урон за шаг параметра: падение — 1d6 за каждые 10 футов, не больше 20d6
                n = int(params.get(per.get("param"), 0)) // int(per.get("step", 1))
                n = min(n, int(per.get("max", n)))
                if n <= 0:
                    out["outcomes"].append({"target_id": target.id, "damage": 0, "note": "урона нет"})
                    params = {**params, "_no_damage": True}
                    continue
                e = parse(expr)
                t = e.terms[0]
                expr = f"{t.count * n}d{t.sides}"
            if not target.alive:
                continue
            o, roll = damage_to(
                target, expr, str(m.get("damage_type", "bludgeoning")), False, ctx.dice, bool(params.get("_half"))
            )
            out["outcomes"].append(o)
            out["dice"].append(roll)
        elif op == "condition" and m.get("condition"):
            if m.get("after_damage") and params.get("_no_damage"):
                continue  # состояние только вместе с уроном: падение с малой высоты не сбивает с ног
            rec = ctx.world.catalog.condition(str(m["condition"]))
            _, note = await add_effect(ctx, target, rec, duration_seconds(m.get("duration")))
            out["outcomes"].append({"target_id": target.id, "effect": rec.id, "note": note})
            target = ctx.world.actor(target.id)
        elif op == "remove_condition":
            names = m.get("any_of") or [m.get("condition")]
            for name in names:
                if not name:
                    continue
                rid = name if "." in str(name) else f"condition.{name}"
                if await remove_effect(ctx, target, rid):
                    out["outcomes"].append({"target_id": target.id, "removed": rid})
                    target = ctx.world.actor(target.id)
                    break
        elif op == "save" and m.get("stat"):
            stat = str(m["stat"])
            dc = resolve_dc(ctx, m.get("dc"))
            mode, reasons = mod.roll_mode(target.modifiers, "save", stat)
            auto = mod.save_auto_fail(target.modifiers, stat)
            roll = engine.saving_throw(ctx.dice, target.saves.get(stat, 0), dc, mode)
            success = roll.success and auto is None
            out["dice"].append(dice_json(roll.roll))
            out["outcomes"].append(
                {
                    "target_id": target.id,
                    "save": stat,
                    "dc": dc,
                    "total": roll.roll.total,
                    "success": success,
                    **({"auto_fail": auto} if auto else {}),
                    **({"reasons": reasons} if reasons else {}),
                }
            )
            branch = m.get("on_success") if success else m.get("on_fail")
            if not success and roll.margin <= -5 and m.get("on_fail_by_5"):
                branch = m["on_fail_by_5"]
            sub_params = params
            if success and m.get("half") and m.get("on_fail"):  # успех — половина урона, без прочих последствий
                branch = [x for x in m["on_fail"] if x.get("op") == "extra_damage"]
                sub_params = {**params, "_half": True}
            sub = await run_ops(ctx, source, branch or [], ctx.world.actor(target.id), sub_params, depth + 1)
            for k in out:
                out[k] += sub[k]
            target = ctx.world.actor(target.id)
        elif op == "resource":
            await _resource(ctx, target, m, out)
            target = ctx.world.actor(target.id)
        elif op == "add" and m.get("target") == "temp_hp" and isinstance(m.get("value"), int):
            engine.add_temp_hp(target.hp, int(m["value"]))
            target.save_hp()
            out["outcomes"].append({"target_id": target.id, "temp_hp": target.hp.temp})
        else:
            out["skipped"].append(f"{op}: не исполняется при применении (постоянное свойство или следующий этап)")
    return out


async def _resource(ctx: ToolContext, target: Actor, m: dict, out: dict) -> None:
    stat = m.get("stat")
    delta = m.get("delta")
    if isinstance(stat, list) or stat is None:
        out["skipped"].append("resource: выбор ресурса игроком — следующий этап")
        return
    stat = str(stat).removeprefix("stat.")
    amount: int
    if isinstance(delta, int):
        amount = delta
    elif isinstance(delta, str):
        try:
            roll = ctx.dice.roll(delta)
        except Exception:  # noqa: BLE001 — формулы вроде "floor(x/2)" движок этапа 3 не считает
            out["skipped"].append(f"resource: формула {delta!r} не поддерживается")
            return
        amount = roll.total
        out["dice"].append(dice_json(roll))
    else:
        return
    if stat == "hp":
        if amount >= 0:
            change = engine.heal(target.hp, amount)
            target.save_hp()
            out["outcomes"].append({"target_id": target.id, "healed": amount, "hp": [change.before, change.after]})
        else:
            change = engine.apply_damage(target.hp, -amount)
            target.save_hp()
            out["outcomes"].append({"target_id": target.id, "damage": -amount, "hp": [change.before, change.after]})
        return
    if stat == "temp_hp":
        engine.add_temp_hp(target.hp, max(0, amount))
        target.save_hp()
        out["outcomes"].append({"target_id": target.id, "temp_hp": target.hp.temp})
        return
    if stat == "exhaustion":
        rec = ctx.world.catalog.condition("exhaustion")
        for _ in range(max(0, amount)):
            await add_effect(ctx, target, rec, None)
            target = ctx.world.actor(target.id)
        for _ in range(max(0, -amount)):
            await remove_effect(ctx, target, rec.id)
            target = ctx.world.actor(target.id)
        out["outcomes"].append({"target_id": target.id, "exhaustion_delta": amount})
        return
    # Ресурс пакета (например, Скверна): границы — из stat_definition
    sdef = ctx.world.catalog.find(f"stat.{stat}", "stat_definition")
    if sdef is None:
        out["skipped"].append(f"resource: нет определения stat.{stat} в пакете")
        return
    holder = target.obj
    field_name = "resources" if target.kind == "character" else "state"
    data = dict(getattr(holder, field_name) or {})
    stats = dict(data.get("stats") or {})
    before = int(stats.get(stat, sdef.data.get("default", sdef.data.get("min", 0)) or 0))
    after = before + amount
    if sdef.data.get("min") is not None:
        after = max(int(sdef.data["min"]), after)
    if sdef.data.get("max") is not None:
        after = min(int(sdef.data["max"]), after)
    stats[stat] = after
    data["stats"] = stats
    setattr(holder, field_name, data)
    out["outcomes"].append({"target_id": target.id, "stat": stat, "value": [before, after]})
