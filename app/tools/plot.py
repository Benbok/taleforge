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
from sqlalchemy import select

from app.core import plot, plot_anchors
from app.core.world import creature_hp, creature_stats
from app.db.models import CampaignSecret, Entity, PlotAnchorBinding
from app.tools import progress
from app.tools.registry import ToolContext, ToolError, tool

PLOT_TOOLS = ("get_plot", "advance_plot", "plot_reveal", "end_act", "develop", "threat_tick", "bind_plot_anchor")


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
    await plot_anchors.sync_bindings(ctx.session, ctx.campaign.id, new)  # носители зацепок следуют за каркасом
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
    "Отмечает ключевую точку сюжета пройденной или обойдённой, с итогом. Итог увидишь в следующих ходах. "
    "done допустим только после достижения цели узла, подтверждённого применёнными событиями: найденным "
    "предметом, раскрытым фактом или завершённым действием. Вход в комнату, подготовка и намерение не "
    "завершают исследование её тайн; сверяй цель узла с get_plot. Не выдавай опыт за ещё не достигнутую цель.",
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

    out = await _change(
        ctx, "advance_plot", fn, payload={"node_id": a.node_id, "result": a.result, "outcome": a.outcome}
    )
    if a.result == "done":  # задача сюжета выполнена: опыт отряду (в кампании с опытом)
        xp = await progress.goal_reached(ctx, "task", "medium", "задача сюжета выполнена")
        if xp:
            out["xp"] = xp
    return out


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

    res = await _change(ctx, "plot_reveal", fn, payload={"reveal_id": a.reveal_id, "how": a.how})
    from app.db.models import NarrativeFact

    nf_stmt = select(NarrativeFact).where(
        NarrativeFact.campaign_id == ctx.campaign.id,
        NarrativeFact.subject_id == a.reveal_id,
    )
    for nf in (await ctx.session.scalars(nf_stmt)).all():
        nf.freedom = "committed"
    return res


class EndActArgs(BaseModel):
    outcome: str = Field(min_length=1, max_length=800, description="итог акта: к чему пришли герои и мир")


@tool(
    "end_act",
    "Закрывает текущий акт, когда выполнено его условие перехода, и открывает следующий. В кампании с опытом отряд "
    "получает опыт за квест сам; в кампании по вехам уровень выдай отдельно через grant_level.",
    EndActArgs,
    closes=False,
)
async def end_act(ctx: ToolContext, a: EndActArgs) -> dict:
    def fn(p: dict) -> dict:
        done, nxt = plot.end_act(p, a.outcome)
        out: dict[str, Any] = {"closed": done["title"]}
        if done.get("milestone_level") and progress.leveling(ctx.campaign) == "milestone":
            out["milestone"] = f"веха акта: подними героев до уровня {done['milestone_level']} через grant_level"
        if nxt is None:
            out["next"] = "актов больше нет: веди к финалу"
        else:
            out["next"] = {"id": nxt["id"], "title": nxt.get("title"), "goal": nxt.get("goal")}
            ctx.signals.add("replan")
        return out

    act = plot.active_act((await _secret(ctx)).plot)
    out = await _change(ctx, "end_act", fn, payload={"act_id": act["id"] if act else None, "outcome": a.outcome})
    xp = await progress.goal_reached(ctx, "quest", "hard", "квест сюжета завершён")
    if xp:
        out["xp"] = xp
    return out


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
    location_id: str | None = Field(
        None, description="для NPC при here: место, где стоят герои; нужно, только если отряд разделён"
    )


@tool(
    "develop",
    "Разворачивает набросок места или NPC каркаса, когда отряд до него дошёл: записывает детали и регистрирует "
    "сущность в реестре мира (после этого её можно размечать и с ней взаимодействовать).",
    DevelopArgs,
    ids={"sketch_id": "plot:sketches", "location_id": "places"},
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
    arrived: list = []
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
            from app.tools.master.places import relocate_scene

            arrived = await relocate_scene(ctx, en, inverse)
    else:
        rec = ctx.world.catalog.get(sketch["template_id"], "creature_template")
        creature_stats(rec.data)  # без блока статов существо в мир не выходит
        hp = creature_hp(rec.data, ctx.campaign.difficulty)
        from app.core.layout import store as layout_store

        home = layout_store.home_of(
            ctx.world.entities, plot.sketch_entity(p, sketch.get("location_id")), f"npc:{sketch['id']}"
        )
        en = Entity(
            campaign_id=ctx.campaign.id,
            kind="creature",
            name=sketch["name"],
            template_id=rec.id,
            description=sketch.get("look") or "",  # карточка для игроков; что он знает — в каркасе
            state={
                "hp": plot.start_hp(hp, sketch.get("condition")),
                "hp_max": hp,
                "attitude": a.attitude,
                "plot_id": sketch["id"],
            },
            location_id=ctx.world.place_arg(a.location_id, "появляется NPC") if a.here else home,
            zone="near",
        )
        ctx.session.add(en)
        await ctx.session.flush()
    ctx.world.entities[en.id] = en
    inverse.insert(0, {"table": "entities", "op": "delete", "id": en.id})

    def fn(p: dict) -> dict:
        plot.develop_sketch(p, a.sketch_id, a.details, en.id)
        return {"entity_id": en.id, "name": en.name, "kind": kind, "current": bool(a.here)}

    # каркас раньше подготовки: резерв места фиксирует носителей зацепок, привязанных к нему в _change
    result = await _change(ctx, "develop", fn, payload={"sketch_id": a.sketch_id, "entity_id": en.id}, target_id=en.id)
    if kind == "location" and (ctx.campaign.settings or {}).get("location_layouts"):
        from app.core.layout import plan as layout_plan
        from app.core.preparation import receipt
        from app.core.world_generation import storage

        row = await layout_plan.reserve_from_plan(ctx, en, sketch, inverse)
        if row is not None:
            storage.activate(row)
            ctx.operation_refs.add(row.id)  # ход и вступление дождутся структуры до описания
            result["layout"] = receipt(row.id)
    if arrived:  # отряд пришёл вместе со сценой — это вход в место, как при move
        from app.tools.master.places import request_preparation

        result |= await request_preparation(ctx, en, inverse)
    await ctx.record(
        "create_location" if kind == "location" else "spawn_entity",
        target_id=en.id,
        payload={"name": en.name, "plot_id": sketch["id"], "template": en.template_id},
        inverse=inverse,
    )
    return result


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

    mode = (ctx.campaign.settings or {}).get("narrative", {}).get("mode") or getattr(
        ctx.campaign, "narrative_mode", "strict"
    )

    if mode == "adaptive":
        from app.core.narrative.fronts import tick_fronts

        tick_result = tick_fronts(
            new,
            int(ctx.world.scene.game_time),
            length=length_of(ctx),
            mode="adaptive",
        )
        new = tick_result.next_plan
        if new == before:
            return []
        secret.plot = new
        ctx.world.plot = copy.deepcopy(new)
        notes = [
            f"{ev.get('antagonist_id', ev.get('front_id'))} сделал шаг угрозы: {ev.get('step', ev.get('progress'))}"
            for ev in tick_result.progress_events
        ]
        if tick_result.progress_events:
            await ctx.record(
                "threat_clock",
                payload={
                    "events": list(tick_result.progress_events),
                    "ready_intents": [i.model_dump() for i in tick_result.ready_intents],
                },
                hidden=True,
                inverse=[{"table": "campaign_secrets", "id": ctx.campaign.id, "field": "plot", "before": before}],
            )
        return notes

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


class BindAnchorArgs(BaseModel):
    anchor_id: str = Field(description="id зацепки каркаса (clue_…)")
    entity_id: str = Field(description="предмет или объект мира, который становится её носителем")


@tool(
    "bind_plot_anchor",
    "Команда ведущего: существующий предмет или объект мира становится носителем зацепки каркаса — без копии. "
    "Так привязывают зацепки старых каркасов и вещи, созданные вручную.",
    BindAnchorArgs,
    closes=False,
)
async def bind_plot_anchor(ctx: ToolContext, a: BindAnchorArgs) -> dict:
    secret = await _secret(ctx)
    found = plot_anchors.find_clue(secret.plot, a.anchor_id)
    if found is None:
        raise ToolError(f"в каркасе нет зацепки {a.anchor_id}")
    reveal, clue = found
    en = ctx.world.entities.get(a.entity_id)
    if en is None or en.campaign_id != ctx.campaign.id or en.kind != "object":
        raise ToolError("носителем может быть только предмет или объект этой кампании")
    q = select(PlotAnchorBinding).where(
        PlotAnchorBinding.campaign_id == ctx.campaign.id, PlotAnchorBinding.anchor_id == a.anchor_id
    )
    binding = await ctx.session.scalar(q)
    if binding is not None and binding.holder_entity_id not in (None, en.id):
        raise ToolError("у зацепки уже есть носитель в мире")
    if binding is None:
        binding = PlotAnchorBinding(campaign_id=ctx.campaign.id, anchor_id=a.anchor_id, plot_ref=reveal["id"])
        ctx.session.add(binding)
    snap = {
        "reveal_id": reveal["id"],
        "text": clue.get("text"),
        "carrier": {"name": en.name, "description": en.description or ""},
    }
    binding.source_snapshot = snap
    binding.plot_ref = reveal["id"]
    binding.holder_entity_id = en.id
    binding.target_location_id = en.location_id
    binding.state = "revealed" if reveal.get("revealed") else "materialized"
    before = copy.deepcopy(en.state)
    en.state = {**(en.state or {}), "plot_anchor": a.anchor_id}
    result = {"anchor_id": a.anchor_id, "entity_id": en.id, "state": binding.state}
    await ctx.record(
        "bind_plot_anchor",
        target_id=en.id,
        payload=result,
        hidden=True,
        inverse=[{"table": "entities", "id": en.id, "field": "state", "before": before}],
    )
    return result
