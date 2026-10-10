"""Сцена и время: режим сцены, игровые часы, истечение эффектов."""

from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field

from app.core import audio, combat
from app.core.world import PLAYABLE, format_time
from app.tools import effects as fx
from app.tools.master.base import snapshot
from app.tools.master.checks import _deploy, roll_initiative
from app.tools.registry import ToolContext, ToolError, tool

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
    elif not any(
        (en := w.entities.get(i)) is not None
        and en.kind == "creature"
        and not (en.state or {}).get("dead")
        and (en.state or {}).get("attitude", "hostile") == "hostile"
        for i in ids
    ):
        # без врагов бой закончился бы тем же ходом «победой», а повествование описало бы битву, которой не было
        raise ToolError(
            "в бою нет врагов: существ, названных в тексте, в реестре нет. Сначала заведи их spawn_entity, "
            "потом начни бой"
        )
    entries, dice = roll_initiative(ctx, ids)
    if joining:
        combat.insert(ctx, entries)
        _deploy(ctx, [e["id"] for e in entries], inverse)
        names = [f"{w.actor(e['id']).name} ({e['initiative']})" for e in entries]
        await ctx.record("set_scene_mode", payload={"mode": "combat", "joined": names}, dice=dice, inverse=inverse)
        return {"mode": "combat", "round": sc.round, "joined": names}
    sc.mode, sc.round = "combat", 1
    sc.turn_order = entries
    combat.start_combat(ctx)
    audio.on_mode(ctx, "combat")
    placed, gridded = _deploy(ctx, [e["id"] for e in entries], inverse)
    names = [f"{w.actor(e['id']).name} ({e['initiative']})" for e in entries]
    await ctx.record("set_scene_mode", payload={"mode": "combat", "order": sc.turn_order}, dice=dice, inverse=inverse)
    out = {"mode": "combat", "round": 1, "initiative": names}
    notes = []
    if placed:
        notes.append(f"враги без стороны встали с одной стороны ({', '.join(placed)})")
    if gridded:
        notes.append("все участники встали на клетки (они в таблице сцены)")
    if notes:
        tail = "; если по сцене они стоят иначе, поправь reposition с cell"
        out["placed"] = "на схеме боя " + "; ".join(notes) + tail
    return out


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
        ench = (ch.resources or {}).get("shillelagh")
        if isinstance(ench, dict) and int(ench.get("expires_at") or 0) <= ctx.world.scene.game_time:
            inverse.append(
                {
                    "table": "characters",
                    "id": ch.id,
                    "field": "resources",
                    "before": copy.deepcopy(ch.resources),
                }
            )
            ch.resources = {k: v for k, v in (ch.resources or {}).items() if k != "shillelagh"}
            ctx.world.invalidate(ch.id)
            ctx.changed.add(ch.id)
            out.append(f"{ch.id}: заклинание «Дубинка» закончилось")
        conc = (ch.resources or {}).get("concentration")
        if isinstance(conc, dict) and conc.get("until") is not None and conc["until"] <= ctx.world.scene.game_time:
            inverse.append(snapshot(ctx.world.actor(ch.id)))
            ch.resources = {k: v for k, v in ch.resources.items() if k != "concentration"}
            out.append(f"{ch.id}: концентрация на «{conc.get('name')}» закончилась")
            ctx.world.invalidate(ch.id)
            ctx.changed.add(ch.id)
    await ctx.session.flush()
    return out
