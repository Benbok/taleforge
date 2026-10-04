"""Сотворение заклинаний (ТЗ, раздел 7): ячейка, бросок атаки заклинанием или спасбросок цели, урон, лечение,
состояния и концентрация. Числа — из записи заклинания и листа героя, мастер передаёт только что, кем и в кого.

То же ядро творит заклинание из предмета (формула, свиток): тогда ячейка не тратится, а сложность и бонус атаки
берутся из предмета.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from pydantic import BaseModel, Field

from app.core import spells as book
from app.core.positions import COVER_AC, pos_of
from app.core.world import Actor, format_time
from app.db.models import Character
from app.rules.dnd5e import modifiers as mod
from app.rules.dnd5e import spells as rules
from app.rules.dnd5e.engine import Dnd5eEngine
from app.tools import effects as fx
from app.tools.registry import ToolContext, ToolError, dice_json, tool

engine = Dnd5eEngine()
MAX_TARGETS = 12
DURATION_RE = re.compile(r"(?:Up to )?(\d+) (round|minute|hour|day)s?")


def spell_seconds(duration: str) -> int | None:
    m = DURATION_RE.fullmatch(str(duration or ""))
    if not m:
        return None
    return int(m.group(1)) * fx.UNIT_SECONDS[m.group(2)]


def _snapshot(a: Actor) -> dict:
    if isinstance(a.obj, Character):
        return {"table": "characters", "id": a.id, "field": "resources", "before": copy.deepcopy(a.obj.resources)}
    return {"table": "entities", "id": a.id, "field": "state", "before": copy.deepcopy(a.obj.state)}


async def end_concentration(ctx: ToolContext, caster: Actor, why: str) -> dict | None:
    """Снимает концентрацию героя и эффекты, которые держались на ней."""
    if not isinstance(caster.obj, Character):
        return None
    res = dict(caster.obj.resources or {})
    conc = res.get("concentration")
    if not isinstance(conc, dict):
        return None
    removed = []
    for eid in conc.get("effects") or []:
        for x in list(ctx.world.effects):
            if x.id == eid:
                await ctx.session.delete(x)
                ctx.world.effects.remove(x)
                ctx.world.invalidate(x.target_id)
                ctx.changed.add(x.target_id)
                removed.append(eid)
    res.pop("concentration", None)
    caster.obj.resources = res
    ctx.world.invalidate(caster.id)
    ctx.changed.add(caster.id)
    return {"spell": conc.get("name"), "ended": why, "effects_removed": len(removed)}


async def concentration_check(ctx: ToolContext, target: Actor, damage: int) -> dict | None:
    """Урон по сосредоточенному герою: спасбросок Телосложения, сложность 10 или половина урона. Провал — конец."""
    if damage <= 0 or not isinstance(target.obj, Character):
        return None
    conc = (target.obj.resources or {}).get("concentration")
    if not isinstance(conc, dict):
        return None
    act = ctx.world.actor(target.id)
    if act.hp.current == 0 or act.hp.dead:
        return await end_concentration(ctx, act, "герой без сознания")
    dc = max(10, damage // 2)
    mode, _ = mod.roll_mode(act.modifiers, "save", "con")
    roll = engine.saving_throw(ctx.dice, act.saves.get("con", 0), dc, mode)
    out = {"concentration": conc.get("name"), "save": "con", "dc": dc, "total": roll.roll.total, "kept": roll.success}
    if not roll.success:
        ended = await end_concentration(ctx, act, "провален спасбросок концентрации")
        if ended:
            out["effects_removed"] = ended["effects_removed"]
    return out


class CastArgs(BaseModel):
    caster_id: str = Field(description="герой, который творит заклинание")
    spell_id: str = Field(description="id заклинания из книги героя (get_character → spells)")
    target_ids: list[str] = Field(
        default_factory=list,
        max_length=MAX_TARGETS,
        description="цели: одна для атаки или касания, все попавшие в область — для площадных; пусто — на себя",
    )
    slot_level: int | None = Field(None, ge=1, le=9, description="круг ячейки, если игрок творит выше круга заклинания")
    ritual: bool = Field(False, description="ритуалом: без ячейки, на 10 минут дольше, только вне боя")


@tool(
    "cast_spell",
    "Сотворение заклинания героем по правилам: ячейка, бросок атаки или спасбросок целей, урон, лечение, состояния, "
    "концентрация. Заговоры — без ячейки. Вне боя тоже: лечение, свет, опознание, ритуалы. Числа — только сервер.",
    CastArgs,
    ids={"caster_id": "characters", "target_ids": "combatants"},
)
async def cast_spell(ctx: ToolContext, a: CastArgs) -> dict:
    w = ctx.world
    ch = w.characters.get(a.caster_id)
    if ch is None:
        raise ToolError("заклинания творят герои; способности существ — описанием или resolve_attack")
    act = w.actor(ch.id)
    if not act.alive or act.hp.current == 0:
        raise ToolError(f"{act.name} без сознания и не может творить заклинания")
    blocked = mod.can_act(act.modifiers)
    if blocked:
        raise ToolError(f"{act.name} не может действовать: {blocked}")
    sc = book.spell_catalog(w.catalog)
    spell = sc.spells.get(a.spell_id)
    if spell is None:
        raise ToolError(f"нет заклинания {a.spell_id} в мире кампании")
    caster = book.caster_for(ch.sheet or {}, w.catalog)
    if caster is None:
        raise ToolError(f"{act.name} не заклинатель: его класс не творит заклинаний")
    if a.spell_id in sc.forbidden:
        raise ToolError(f"«{spell['name']}» героям этого мира недоступно")
    why = rules.can_cast_now(caster, rules.Choice.of(ch.sheet or {}), a.spell_id, spell, a.ritual)
    if why:
        raise ToolError(f"{act.name}: {why}")

    combat = w.in_fight(ch.id)  # бой другой части отряда не мешает
    ct = str(spell.get("casting_time"))
    if combat and (a.ritual or ct not in rules.COMBAT_TIMES):
        took = "ритуал идёт 10 минут" if a.ritual else f"оно творится {rules.TIME_RU.get(ct, ct)}"
        raise ToolError(f"в бою «{spell['name']}» не успеть: {took}. Можно после боя")

    level = int(spell.get("level", 0))
    res_before = copy.deepcopy(ch.resources or {})
    slot_kind, slot = None, level
    if level > 0 and not a.ritual:
        try:
            slot_kind, slot = rules.pick_slot(caster, ch.resources or {}, level, a.slot_level)
        except rules.SpellError as e:
            raise ToolError(f"{act.name}: {e}") from e
        ch.resources = rules.spend(ch.resources or {}, slot_kind, slot)
        w.invalidate(ch.id)
    return await resolve(
        ctx,
        act,
        spell,
        slot=slot,
        dc=caster.save_dc,
        attack_bonus=caster.attack,
        ability_mod=caster.ability_mod,
        char_level=caster.level,
        targets=a.target_ids,
        ritual=a.ritual,
        inverse=[{"table": "characters", "id": ch.id, "field": "resources", "before": res_before}],
        extra={"slot": {"kind": slot_kind, "level": slot}} if slot_kind else {},
        class_tags=_class_tags(w, ch),
    )


def _class_tags(w, ch: Character) -> set[str]:
    cls = w.catalog.find((ch.sheet or {}).get("class_id") or "", "class")
    return set((cls.data if cls else {}).get("tags") or [])


async def resolve(
    ctx: ToolContext,
    act: Actor,
    spell: dict,
    *,
    slot: int,
    dc: int,
    attack_bonus: int,
    ability_mod: int,
    char_level: int,
    targets: list[str],
    ritual: bool = False,
    inverse: list | None = None,
    extra: dict | None = None,
    class_tags: set[str] = frozenset(),
    source: str | None = None,
    pre_dice: list | None = None,
    before_record: Any = None,
) -> dict:
    """Общее ядро: цели, дальность, бросок, урон, лечение, эффекты, концентрация и время сотворения."""
    w = ctx.world
    level = int(spell.get("level", 0))
    kind = rules.target_kind(spell)
    ids = list(dict.fromkeys(targets or []))
    if not ids and kind in ("self", "ally", "any"):
        ids = [act.id]
    if kind == "enemy" and not ids:
        raise ToolError(f"«{spell['name']}»: нужна цель (target_ids)")
    if kind == "enemy" and len(ids) > 1 and not (spell.get("rays") or spell.get("rays_by_char_level")):
        raise ToolError(f"«{spell['name']}» бьёт одну цель: передайте одну")
    rng = rules.range_ft(spell)
    area = spell.get("area") or {}
    tgts: list[Actor] = []
    for tid in ids:
        try:
            t = w.actor(tid)
        except Exception as e:  # noqa: BLE001 — неизвестный id или не существо
            raise ToolError(str(e)) from e
        if not t.alive and not spell.get("revives"):
            raise ToolError(f"{t.name} мёртв: это заклинание мёртвым не поможет")
        if t.id != act.id and rng is not None:
            reach = max(rng, int(area.get("size_ft") or 0)) if str(spell.get("range")) == "Self" else rng
            dist = w.distance_ft(act, t)
            if dist > reach:
                raise ToolError(f"{t.name} дальше {reach} фт ({dist} фт): «{spell['name']}» не достанет")
        if kind == "enemy" and pos_of(w, t.id).cover == "total":
            raise ToolError(f"{t.name} за полным укрытием: заклинанию нужна видимая цель")
        tgts.append(t)

    result: dict[str, Any] = {
        "caster": act.name,
        "spell": spell["name"],
        "spell_id": spell["id"],
        "level": level,
        "slot_level": slot if level else 0,
        **(extra or {}),
    }
    if source:
        result["source"] = source
    if ritual:
        result["ritual"] = True
    dice: list = []
    inverse = list(inverse or [])
    for t in tgts:
        if t.id != act.id or not isinstance(act.obj, Character):
            inverse.append(_snapshot(t))

    # новая концентрация обрывает прежнюю
    if spell.get("concentration") and isinstance(act.obj, Character):
        prev = await end_concentration(ctx, act, f"начато «{spell['name']}»")
        if prev:
            result["concentration_ended"] = prev
        act = w.actor(act.id)

    outcomes: list[dict] = []
    effects_made: list[str] = []
    parts = rules.damage_parts(spell, slot or level, char_level)
    heal = rules.heal_expr(spell, slot or level, ability_mod)
    on_fail = list(spell.get("on_fail") or [])
    buff = spell.get("effect")
    seconds = spell_seconds(spell.get("duration"))

    async def apply(t: Actor, ref: str) -> None:
        rec = w.catalog.condition(ref) if "." not in ref else w.catalog.get(ref)
        e, note = await fx.add_effect(ctx, t, rec, seconds)
        outcomes.append({"target_id": t.id, "effect": rec.id, "note": note})
        if e is not None and spell.get("concentration"):
            effects_made.append(e.id)

    for t in tgts:
        t = w.actor(t.id)
        if spell.get("attack"):
            rays = _rays(spell, slot or level, char_level)
            for n in range(rays):
                if not t.alive:
                    break
                dist = w.distance_ft(act, t)
                extra_r = (
                    ["помеха: дальняя атака вплотную к врагу"] if spell["attack"] == "ranged" and dist <= 5 else []
                )
                cover = pos_of(w, t.id).cover
                am = mod.attack_mods(act.modifiers, t.modifiers, dist, extra_r)
                roll = engine.attack(ctx.dice, attack_bonus + am.bonus, t.ac + COVER_AC.get(cover, 0), am.mode)
                dice.append(dice_json(roll.roll))
                row: dict[str, Any] = {
                    "target_id": t.id,
                    "target": t.name,
                    "attack_roll": roll.roll.total,
                    "natural": roll.roll.natural,
                    "target_ac": t.ac + COVER_AC.get(cover, 0),
                    "hit": roll.hit,
                    "critical": roll.critical,
                }
                if roll.roll.natural == 1:
                    row["fumble"] = True
                if rays > 1:
                    row["ray"] = n + 1
                if am.reasons:
                    row["reasons"] = list(am.reasons)
                if roll.hit:
                    await _damage(ctx, t, parts, roll.critical, False, row, dice)
                    for ref in on_fail:
                        await apply(w.actor(t.id), ref)
                outcomes.append(row)
                t = w.actor(t.id)
        elif spell.get("save"):
            stat = str(spell["save"]["stat"])
            mode, reasons = mod.roll_mode(t.modifiers, "save", stat)
            auto = mod.save_auto_fail(t.modifiers, stat)
            roll = engine.saving_throw(ctx.dice, t.saves.get(stat, 0), dc, mode)
            ok = roll.success and auto is None
            dice.append(dice_json(roll.roll))
            row = {"target_id": t.id, "target": t.name, "save": stat, "dc": dc, "total": roll.roll.total, "success": ok}
            if reasons:
                row["reasons"] = reasons
            if auto:
                row["auto_fail"] = auto
            half = str(spell["save"].get("on_success")) == "half"
            if parts and (not ok or half):
                await _damage(ctx, t, parts, False, ok, row, dice)
            if not ok:
                for ref in on_fail:
                    await apply(w.actor(t.id), ref)
            outcomes.append(row)
        elif spell.get("auto_hit") and parts:
            row = {"target_id": t.id, "target": t.name, "hit": True}
            await _damage(ctx, t, parts, False, False, row, dice)
            outcomes.append(row)
        elif heal:
            await _heal(ctx, t, heal, spell.get("heal_kind"), row := {"target_id": t.id, "target": t.name}, dice)
            outcomes.append(row)
        if buff:
            await apply(w.actor(t.id), str(buff))

    if spell.get("concentration") and isinstance(act.obj, Character):
        until = w.scene.game_time + seconds if seconds else None
        act.obj.resources = {
            **(act.obj.resources or {}),
            "concentration": {"spell_id": spell["id"], "name": spell["name"], "effects": effects_made, "until": until},
        }
        result["concentration"] = True
        w.invalidate(act.id)

    if outcomes:
        result["outcomes"] = outcomes
    if not (parts or heal or on_fail or buff):
        # действие без чисел: что именно происходит, мастер описывает по тексту заклинания
        result["effect_text"] = str(spell.get("description") or spell.get("srd_text") or "")[:600]
    if spell.get("heal_kind") == "max_hp":
        result["note"] = "максимум и текущие хиты целей выше на число из заклинания на 8 часов: учтено как лечение"
    if dc and (spell.get("save") or not (parts or heal)):
        result["save_dc"] = dc
    took = rules.cast_seconds(spell, ritual)
    if not w.in_fight(act.id) and took >= 60:
        inverse.append({"table": "scenes", "id": ctx.campaign.id, "field": "game_time", "before": w.scene.game_time})
        w.scene.game_time += took
        result["time"] = format_time(w.scene.game_time)
    result["after"] = await _after_cast(ctx, act, spell, slot if level else 0, class_tags, dice)
    if not result["after"]:
        result.pop("after")
    dice += pre_dice or []  # проверка свитка — после бросков заклинания, чтобы карточка показала атаку
    if before_record is not None:
        await before_record()
    await ctx.record(
        "cast_spell",
        actor_id=act.id,
        target_id=tgts[0].id if len(tgts) == 1 else None,
        payload=result,
        dice=dice,
        inverse=inverse,
    )
    for t in tgts:
        w.invalidate(t.id)
    w.invalidate(act.id)
    return result


async def read_scroll(ctx: ToolContext, ch: Character, it: Any, rec: Any, target_ids: list[str]) -> dict:
    """Свиток (в мире — формула): заклинание без ячейки, сложность и бонус атаки — из свитка по кругу.
    Прочесть может заклинатель, у которого это заклинание в списке класса; круг выше доступного — проверка
    заклинательной характеристики, сл. 10 + круг, провал — свиток пропал зря. Свиток тратится в любом случае."""
    w = ctx.world
    spec = rec.data.get("spell_scroll") or {}
    act = w.actor(ch.id)
    if not act.alive or act.hp.current == 0:
        raise ToolError(f"{act.name} без сознания и не может читать свиток")
    blocked = mod.can_act(act.modifiers)
    if blocked:
        raise ToolError(f"{act.name} не может действовать: {blocked}")
    sc = book.spell_catalog(w.catalog)
    sid = str(spec.get("spell_ref") or "")
    spell = sc.spells.get(sid)
    if spell is None:
        raise ToolError(f"в свитке «{rec.name}» записано {sid or 'непонятно что'}: такого заклинания в мире нет")
    if sid in sc.forbidden:
        raise ToolError(f"«{spell['name']}» героям этого мира недоступно — свиток не откликается")
    caster = book.caster_for(ch.sheet or {}, w.catalog)
    try:
        need = rules.scroll_check(caster, sid, spell)
    except rules.SpellError as e:
        raise ToolError(f"{act.name}: {e}") from e
    ct = str(spell.get("casting_time"))
    if w.in_fight(ch.id) and ct not in rules.COMBAT_TIMES:
        raise ToolError(f"в бою «{spell['name']}» со свитка не успеть: оно творится {rules.TIME_RU.get(ct, ct)}")

    level = int(spell.get("level", 0))
    slot = max(level, int(spec.get("slot_level") or level))
    dc, bonus = rules.SCROLL_STATS.get(slot, rules.SCROLL_STATS[9])
    dc, bonus = int(spec.get("dc") or dc), int(spec.get("attack_bonus") or bonus)
    inverse: list[dict] = [{"table": "inventory", "id": it.id, "field": "qty", "before": it.qty}]
    item_name = w.item_name(it)

    async def consume() -> None:
        it.qty -= 1
        if it.qty <= 0:
            await ctx.session.delete(it)
            w.inventory[ch.id].remove(it)

    if need is not None:
        res = engine.check(ctx.dice, caster.ability_mod, need)
        check = {"dc": need, "total": res.roll.total, "success": res.success}
        if not res.success:
            result = {
                "caster": act.name,
                "spell": spell["name"],
                "spell_id": sid,
                "level": level,
                "source": item_name,
                "scroll_check": check,
                "fizzled": True,
            }
            await consume()
            await ctx.record("cast_spell", actor_id=ch.id, payload=result, dice=[dice_json(res.roll)], inverse=inverse)
            return result
        extra = {"scroll_check": check}
        pre_dice = [dice_json(res.roll)]
    else:
        extra, pre_dice = {}, []
    # цели и дальность проверяются до траты свитка: ошибка откатит всё, а свиток останется у героя
    result = await resolve(
        ctx,
        act,
        spell,
        slot=slot,
        dc=dc,
        attack_bonus=bonus,
        ability_mod=caster.ability_mod if caster else 0,
        char_level=caster.level if caster else 1,
        targets=target_ids,
        inverse=inverse,
        extra={**extra, "scroll": True},
        class_tags=_class_tags(w, ch),
        source=item_name,
        pre_dice=pre_dice,
        before_record=consume,
    )
    return result


def _rays(spell: dict, slot: int, char_level: int) -> int:
    if spell.get("rays"):
        r = spell["rays"]
        return int(r.get("count", 1)) + max(0, slot - int(spell.get("level", 1))) * int(r.get("per_slot", 0))
    if spell.get("rays_by_char_level"):
        return int(rules.dice_at(spell["rays_by_char_level"], char_level) or 1)
    return 1


async def _damage(
    ctx: ToolContext, t: Actor, parts: list[tuple[str, str]], crit: bool, half: bool, row: dict, dice: list
) -> None:
    total = 0
    for expr, dtype in parts:
        t = ctx.world.actor(t.id)
        if not t.alive:
            break
        o, r = fx.damage_to(t, expr, dtype, crit, ctx.dice, half)
        dice.append(r)
        total += o["damage"]
        row.setdefault("damage_types", []).append(dtype)
        if o.get("defenses"):
            row["defenses"] = o["defenses"]
        row["target_status"] = o["status"]
        if o.get("instant_death"):
            row["instant_death"] = True
    row["damage"] = total
    ctx.world.invalidate(t.id)
    t = ctx.world.actor(t.id)
    if t.hp.dead:
        row["killed"] = True
    conc = await concentration_check(ctx, t, total)
    if conc:
        row["concentration_check"] = conc


async def _heal(ctx: ToolContext, t: Actor, expr: str, kind: str | None, row: dict, dice: list) -> None:
    r = ctx.dice.roll(expr)
    dice.append(dice_json(r))
    amount = max(0, r.total)
    if kind == "temp_hp":
        engine.add_temp_hp(t.hp, amount)
        row["temp_hp"] = t.hp.temp
    else:
        before = t.hp.current
        engine.heal(t.hp, amount)
        row["healed"] = t.hp.current - before
        row["hp"] = [before, t.hp.current]
    t.save_hp()
    row["target_status"] = t.status()
    ctx.world.invalidate(t.id)


async def _after_cast(ctx: ToolContext, act: Actor, spell: dict, slot: int, tags: set[str], dice: list) -> list:
    """Цена силы мира после сотворения: триггеры ``spell_cast`` из записей spell_note (Перемена от сильных формул)."""
    out: list = []
    for note in ctx.world.catalog.by_kind("spell_note"):
        for trig in note.data.get("triggers") or []:
            if trig.get("on") not in ("spell_cast", "cast_spell"):
                continue
            cond = trig.get("if") or {}
            if "spell_level_gte" in cond and slot < int(cond["spell_level_gte"]):
                continue
            if cond.get("caster_tag") and cond["caster_tag"] not in tags:
                continue
            if cond.get("lineage"):
                lin = str((act.obj.sheet or {}).get("lineage_id") or "") if isinstance(act.obj, Character) else ""
                if not lin.endswith(str(cond["lineage"])):
                    continue
            ops = _bind(trig.get("do") or [], {"spell_level": slot})
            r = await fx.run_ops(ctx, note.id, ops, ctx.world.actor(act.id), {})
            dice += r.pop("dice")
            out.append({"rule": note.name, **r})
    return out


def _bind(ops: Any, params: dict[str, int]) -> Any:
    """Формулы сложности вроде «10 + spell_level» — в числа."""
    if isinstance(ops, list):
        return [_bind(x, params) for x in ops]
    if isinstance(ops, dict):
        out = {k: _bind(v, params) for k, v in ops.items()}
        dc = out.get("dc")
        if isinstance(dc, str):
            m = re.fullmatch(r"\s*(\d+)\s*\+\s*(\w+)\s*", dc)
            if m and m.group(2) in params:
                out["dc"] = int(m.group(1)) + params[m.group(2)]
        return out
    return ops
