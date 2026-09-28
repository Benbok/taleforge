"""Инструменты мастера для ведения по каркасу (проект «Подготовка кампании», раздел 3).

Каркас живёт в ``campaign_secrets.plot`` и виден только мастеру. Мастер отмечает пройденные узлы и раскрытые тайны,
закрывает акты, разворачивает наброски мест и NPC в записи реестра, когда отряд до них доходит, и двигает планы
злодеев. Часы угроз сервер двигает сам по игровым дням (``run_clock``). События этих инструментов скрыты от игроков.
"""

from __future__ import annotations

import copy
from collections.abc import Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.core import plot
from app.core.world import creature_stats
from app.db.models import CampaignSecret, Entity
from app.tools.registry import ToolContext, ToolError, tool

PLOT_TOOLS = ("get_plot", "advance_plot", "plot_reveal", "end_act", "develop", "threat_tick")


def length_of(ctx: ToolContext) -> str:
    return (ctx.campaign.brief or {}).get("length") or "short"


async def _secret(ctx: ToolContext) -> CampaignSecret:
    secret = await ctx.session.get(CampaignSecret, ctx.campaign.id)
    if secret is None or not plot.has_plan(secret.plot):
        raise ToolError("у кампании нет каркаса сюжета: веди игру по вводной")
    return secret


async def _change(
    ctx: ToolContext, name: str, fn: Callable[[dict], Any], *, payload: dict, target_id: str | None = None
) -> Any:
    """Меняет каркас функцией ``fn`` и пишет скрытое событие с прежней версией каркаса для отката."""
    secret = await _secret(ctx)
    before = copy.deepcopy(secret.plot)
    new = copy.deepcopy(secret.plot)
    try:
        result = fn(new)
    except plot.PlotError as e:
        raise ToolError(str(e)) from e
    secret.plot = new
    ctx.world.plot = copy.deepcopy(new)
    await ctx.record(
        name,
        target_id=target_id,
        payload=payload,
        hidden=True,
        inverse=[{"table": "campaign_secrets", "id": ctx.campaign.id, "field": "plot", "before": before}],
    )
    return result


class NoArgs(BaseModel):
    pass


@tool(
    "get_plot",
    "Весь каркас сюжета: все акты, места, NPC, тайны и финалы с отметками прогресса. Только для мастера.",
    NoArgs,
    mutating=False,
    closes=False,
)
async def get_plot(ctx: ToolContext, a: NoArgs) -> dict:
    return {"plan": plot.render((await _secret(ctx)).plot)}


class AdvanceArgs(BaseModel):
    node_id: str
    result: Literal["done", "skipped"] = Field(
        "done", description="done — узел случился; skipped — отряд обошёл его, и он больше не нужен"
    )
    outcome: str = Field(min_length=1, max_length=500, description="чем кончилось: кто что решил, что изменилось")


@tool(
    "advance_plot",
    "Отмечает ключевую точку сюжета пройденной или обойдённой, с итогом. Итог увидишь в следующих ходах.",
    AdvanceArgs,
    ids={"node_id": "plot:nodes"},
    closes=False,
)
async def advance_plot(ctx: ToolContext, a: AdvanceArgs) -> dict:
    def fn(p: dict) -> dict:
        n = plot.close_node(p, a.node_id, a.result, a.outcome)
        act = plot.node_act(p, a.node_id)
        left = [x["id"] for x in act["nodes"] if x.get("status") not in plot.CLOSED]
        out = {"node": n["title"], "result": a.result, "act": act["id"], "open_nodes": left}
        if not left and act.get("status") == "active":
            out["hint"] = f"все узлы акта закрыты. Когда выполнено условие перехода ({act.get('exit')}), вызови end_act"
        return out

    return await _change(
        ctx, "advance_plot", fn, payload={"node_id": a.node_id, "result": a.result, "outcome": a.outcome}
    )


class RevealPlotArgs(BaseModel):
    reveal_id: str
    how: str = Field(min_length=1, max_length=500, description="как герои это узнали")


@tool(
    "plot_reveal",
    "Отмечает тайну каркаса раскрытой: герои узнали правду. Не путай с reveal_knowledge (знания о сущности).",
    RevealPlotArgs,
    ids={"reveal_id": "plot:reveals"},
    closes=False,
)
async def plot_reveal(ctx: ToolContext, a: RevealPlotArgs) -> dict:
    def fn(p: dict) -> dict:
        r = plot.mark_revealed(p, a.reveal_id, a.how)
        return {"reveal": r["id"], "truth": r.get("truth"), "leads_to": r.get("node_id")}

    return await _change(ctx, "plot_reveal", fn, payload={"reveal_id": a.reveal_id, "how": a.how})


class EndActArgs(BaseModel):
    outcome: str = Field(min_length=1, max_length=800, description="итог акта: к чему пришли герои и мир")


@tool(
    "end_act",
    "Закрывает текущий акт, когда выполнено его условие перехода, и открывает следующий. Веху уровня выдай "
    "отдельно через grant_level.",
    EndActArgs,
    closes=False,
)
async def end_act(ctx: ToolContext, a: EndActArgs) -> dict:
    def fn(p: dict) -> dict:
        done, nxt = plot.end_act(p, a.outcome)
        out: dict[str, Any] = {"closed": done["title"]}
        if done.get("milestone_level"):
            out["milestone"] = f"веха акта: подними героев до уровня {done['milestone_level']} через grant_level"
        if nxt is None:
            out["next"] = "актов больше нет: веди к финалу"
        else:
            out["next"] = {"id": nxt["id"], "title": nxt.get("title"), "goal": nxt.get("goal")}
            ctx.signals.add("replan")
        return out

    act = plot.active_act((await _secret(ctx)).plot)
    return await _change(ctx, "end_act", fn, payload={"act_id": act["id"] if act else None, "outcome": a.outcome})


class DevelopArgs(BaseModel):
    sketch_id: str
    details: str = Field(
        min_length=1,
        max_length=1500,
        description="детали, которые ты придумал сейчас: как выглядит, кто там, что можно найти; для NPC — голос, "
        "манеры, что он знает",
    )
    here: bool = Field(True, description="место — сделать текущей сценой; NPC — поставить в текущую сцену")
    attitude: Literal["hostile", "neutral", "friendly"] = Field("neutral", description="только для NPC")


@tool(
    "develop",
    "Разворачивает набросок места или NPC каркаса, когда отряд до него дошёл: записывает детали и регистрирует "
    "сущность в реестре мира (после этого её можно размечать и с ней взаимодействовать).",
    DevelopArgs,
    ids={"sketch_id": "plot:sketches"},
    closes=False,
)
async def develop(ctx: ToolContext, a: DevelopArgs) -> dict:
    p = (await _secret(ctx)).plot
    kind, sketch = next(
        (
            (k, x)
            for k, key in (("location", "locations"), ("npc", "npcs"))
            for x in p.get(key) or []
            if x["id"] == a.sketch_id
        ),
        (None, None),
    )
    if sketch is None:
        raise ToolError(f"нет наброска {a.sketch_id}")
    inverse: list[dict] = []
    if kind == "location":
        tid = sketch.get("template_id")
        rec = ctx.world.catalog.find(tid, "location_template") if tid else None
        en = Entity(
            campaign_id=ctx.campaign.id,
            kind="location",
            name=sketch["name"],
            template_id=rec.id if rec else None,
            description=sketch.get("mood") or "",  # карточка для игроков; детали и секрет остаются в каркасе
            state={"dc": rec.data["dc"], "plot_id": sketch["id"]}
            if rec and rec.data.get("dc") is not None
            else {"plot_id": sketch["id"]},
        )
        ctx.session.add(en)
        await ctx.session.flush()
        if a.here:
            inverse.append(
                {
                    "table": "scenes",
                    "id": ctx.campaign.id,
                    "field": "location_id",
                    "before": ctx.world.scene.location_id,
                }
            )
            ctx.world.scene.location_id = en.id
    else:
        rec = ctx.world.catalog.get(sketch["template_id"], "creature_template")
        creature_stats(rec.data)  # без блока статов существо в мир не выходит
        hp = int((rec.data.get("hp") or {}).get("average", 1))
        home = plot.sketch_entity(p, sketch.get("location_id"))
        en = Entity(
            campaign_id=ctx.campaign.id,
            kind="creature",
            name=sketch["name"],
            template_id=rec.id,
            description=sketch.get("look") or "",  # карточка для игроков; что он знает — в каркасе
            state={"hp": hp, "hp_max": hp, "attitude": a.attitude, "plot_id": sketch["id"]},
            location_id=ctx.world.scene.location_id if a.here else home,
            zone="near",
        )
        ctx.session.add(en)
        await ctx.session.flush()
    ctx.world.entities[en.id] = en
    inverse.insert(0, {"table": "entities", "op": "delete", "id": en.id})
    await ctx.record(
        "create_location" if kind == "location" else "spawn_entity",
        target_id=en.id,
        payload={"name": en.name, "plot_id": sketch["id"], "template": en.template_id},
        inverse=inverse,
    )

    def fn(p: dict) -> dict:
        plot.develop_sketch(p, a.sketch_id, a.details, en.id)
        return {"entity_id": en.id, "name": en.name, "kind": kind, "current": bool(a.here)}

    return await _change(ctx, "develop", fn, payload={"sketch_id": a.sketch_id, "entity_id": en.id}, target_id=en.id)


class ThreatArgs(BaseModel):
    antagonist_id: str
    reason: str = Field(min_length=1, max_length=500, description="почему злодей сделал шаг сейчас")


@tool(
    "threat_tick",
    "Антагонист делает следующий шаг своего плана угрозы: герои медлят, провалили задачу или сыграли ему на руку.",
    ThreatArgs,
    ids={"antagonist_id": "plot:antagonists"},
    closes=False,
)
async def threat_tick(ctx: ToolContext, a: ThreatArgs) -> dict:
    def fn(p: dict) -> dict:
        who, step, nxt = plot.threat_step(p, a.antagonist_id, a.reason)
        return {"antagonist": who["name"], "step": step, "next": nxt or "план исполнен: пора к развязке"}

    return await _change(ctx, "threat_tick", fn, payload={"antagonist_id": a.antagonist_id, "reason": a.reason})


async def run_clock(ctx: ToolContext) -> list[str]:
    """Часы угроз по игровому времени. Возвращает заметки для мастера о шагах злодеев."""
    secret = await ctx.session.get(CampaignSecret, ctx.campaign.id)
    if secret is None or not plot.has_plan(secret.plot):
        return []
    before = copy.deepcopy(secret.plot)
    new = copy.deepcopy(secret.plot)
    ticks = plot.clock(new, int(ctx.world.scene.game_time), length_of(ctx))
    if new == before:
        return []
    secret.plot = new
    ctx.world.plot = copy.deepcopy(new)
    notes = [f"{who['name']} сделал шаг угрозы, пока герои были заняты: {step}" for who, step, _ in ticks]
    if ticks:
        await ctx.record(
            "threat_clock",
            payload={"ticks": [{"antagonist_id": w["id"], "step": s} for w, s, _ in ticks]},
            hidden=True,
            inverse=[{"table": "campaign_secrets", "id": ctx.campaign.id, "field": "plot", "before": before}],
        )
    return notes
