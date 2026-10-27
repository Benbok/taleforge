"""Сцена и время: режим сцены, игровые часы, истечение эффектов."""

from __future__ import annotations

import copy
from typing import Literal

from pydantic import BaseModel, Field

from app.core.world import format_time
from app.tools import effects as fx
from app.tools.master.base import snapshot
from app.tools.registry import ToolContext, tool

# --- сцена и время ---


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
