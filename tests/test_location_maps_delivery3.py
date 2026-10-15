# ruff: noqa: F811 — shared integration fixtures
"""Приёмочный пилот поставки 3 (спецификация 2026-10-12, §8, §10; docs/location-maps-delivery3.md):
генерация комплекса храма и поля из каркаса технической моделью, первая сцена, обход проходов,
подготовка вперёд, изоляция тайн и полный учёт расходов."""

import json

from sqlalchemy import select

from app.agents import layout_model, prelude
from app.agents.llm import LLMReply, ScriptedLLM, ToolCall
from app.core import preparation
from app.core.layout import store
from app.core.world_generation.service import Orchestrator
from app.db.models import Campaign, Character, Entity, LlmCall, MapMemory, Scene, WorldGenerationState
from app.gateway.coordination import InMemoryCoordination
from app.tools.registry import execute
from tests.game import party, run
from tests.layout_plan_pilot import model_layout, temple_plan
from tests.test_layout_transit import _go
from tests.test_lead import set_plan
from tests.test_map import _map, _ok, _play
from tests.test_master import admin_g, dice, game_client, llm, rows  # noqa: F401
from tests.test_world_generation import _fast_retry, _with_maker  # noqa: F401

WGS = WorldGenerationState


def _layout_answer(_messages, tools):
    keys = tools[0]["function"]["parameters"]["properties"]["parts"]["items"]["properties"]["anchors"]["items"]["enum"]
    return LLMReply(
        text="",
        tool_calls=[ToolCall("c", layout_model.TOOL, model_layout(keys))],
        model="tech",
        tokens_in=1200,
        tokens_out=800,
        reasoning_tokens=300,
        cost=0.004,
        latency_ms=50,
    )


def _start(game_client, admin_g, settings, **flags):
    c, heads, _ = party(game_client, admin_g)
    master = game_client.app.state.master
    game_client.portal.call(master.wait_idle, c["id"])
    plan = temple_plan()
    plan["acts"][0]["nodes"][0]["npc_ids"] = ["npc_warden"]
    set_plan(settings, c["id"], plan)

    async def on(s):
        campaign = await s.get(Campaign, c["id"])
        campaign.settings = {
            **(campaign.settings or {}),
            "location_layouts": True,
            **flags,
        }
        await s.commit()

    run(settings, on)
    return c["id"], master, plan["locations"][0], heads


def _root(settings, cid):
    async def go(s):
        found = await s.scalars(select(Entity).where(Entity.campaign_id == cid, Entity.kind == "location"))
        return next(e for e in found if (e.state or {}).get("blueprint") or (e.state or {}).get("plot_id"))

    return run(settings, go)


def test_pilot_opening_generates_temple_and_field_once(game_client, admin_g, settings):
    cid, master, where, _heads = _start(
        game_client, admin_g, settings, location_layouts_llm=True, scene_generation=True
    )
    scripted = ScriptedLLM([_layout_answer])
    master.preparer.llm = scripted

    assert game_client.portal.call(prelude._open_first_place, master, cid, where)

    root = _root(settings, cid)
    bp = store.blueprint_of(root)
    assert bp is not None
    areas = store.area_ids(root)
    assert len(areas) == 8
    assert set(areas.keys()) == {"road", "brook", "narthex", "nave", "chapel", "sacristy", "vault", "crypt"}
    assert bp.entry == "road"

    (scene,) = rows(settings, Scene, Scene.campaign_id == cid)
    heroes = rows(settings, Character, Character.campaign_id == cid)
    assert scene.location_id == areas["road"]
    assert all(h.location_id == areas["road"] for h in heroes if h.status in ("approved", "active"))

    road_entity = run(settings, lambda s: s.get(Entity, areas["road"]))
    road_terrain = [t["kind"] for t in (road_entity.state or {}).get("sketch", {}).get("terrain", [])]
    assert "road" in road_terrain and "stream" in road_terrain and "bridge" in road_terrain

    _with_maker(settings, lambda maker: Orchestrator(InMemoryCoordination()).run_due(maker))
    brook_entity = run(settings, lambda s: s.get(Entity, areas["brook"]))
    brook_terrain = [t["kind"] for t in (brook_entity.state or {}).get("sketch", {}).get("terrain", [])]
    assert "road" in brook_terrain and "stream" in brook_terrain

    (layout_row,) = rows(settings, WGS, WGS.campaign_id == cid, WGS.phase == "location_layout")
    assert layout_row.quality == "normal"

    calls = rows(settings, LlmCall, LlmCall.campaign_id == cid, LlmCall.purpose == layout_model.PURPOSE)
    assert len(calls) == 1 and calls[0].generation_id == layout_row.id

    memories = rows(settings, MapMemory)
    assert {m.entity_id for m in memories} == {areas["road"]}


def test_pilot_round_trip_keeps_structure_and_costs_nothing_new(game_client, admin_g, settings):
    cid, master, where, heads = _start(game_client, admin_g, settings, location_layouts_llm=True, scene_generation=True)
    master.preparer.llm = ScriptedLLM([_layout_answer])
    assert game_client.portal.call(prelude._open_first_place, master, cid, where)

    root = _root(settings, cid)
    bp_before = store.blueprint_of(root)
    areas_before = store.area_ids(root)

    east = _go(game_client, heads[0], cid, "p_brook")
    assert east["moved"] and east["area_id"] == areas_before["brook"]

    west = _go(game_client, heads[0], cid, "p_brook")
    assert west["moved"] and west["area_id"] == areas_before["road"]

    async def open_doors(ctx):
        await _ok(ctx, "edit_sketch", {"action": "open", "target": "Двери храма", "location_id": areas_before["road"]})

    _play(settings, cid, open_doors)

    narthex = _go(game_client, heads[0], cid, "p_narthex")
    assert narthex["moved"] and narthex["area_id"] == areas_before["narthex"]

    root_after = _root(settings, cid)
    bp_after = store.blueprint_of(root_after)
    assert bp_after.revision == bp_before.revision
    assert store.area_ids(root_after) == areas_before

    calls = rows(settings, LlmCall, LlmCall.campaign_id == cid, LlmCall.purpose == layout_model.PURPOSE)
    assert len(calls) == 1

    cost = run(settings, lambda s: preparation.location_cost(s, cid, root.id))
    assert cost["phases"]["location_layout"]["rows"] == 1
    assert cost["phases"]["location_geometry"]["rows"] >= 1
    assert cost["total"]["calls"] == sum(p["calls"] for p in cost["phases"].values())


def test_pilot_model_failure_falls_back_and_is_diagnosable(game_client, admin_g, settings):
    cid, master, where, _heads = _start(
        game_client, admin_g, settings, location_layouts_llm=True, scene_generation=True
    )

    def _invalid(_messages, _tools):
        return {"tool_calls": [(layout_model.TOOL, {"entry": "bad_entry"})]}

    master.preparer.llm = ScriptedLLM([_invalid, _invalid])
    assert game_client.portal.call(prelude._open_first_place, master, cid, where)

    root = _root(settings, cid)
    bp = store.blueprint_of(root)
    assert bp is not None
    areas = store.area_ids(root)
    (scene,) = rows(settings, Scene, Scene.campaign_id == cid)
    assert scene.location_id == areas[bp.entry]

    (layout_row,) = rows(settings, WGS, WGS.campaign_id == cid, WGS.phase == "location_layout")
    assert layout_row.quality == "fallback"
    assert any("fallback:invalid_proposal" in n for n in (layout_row.result_manifest.get("notes") or []))

    cost = run(settings, lambda s: preparation.location_cost(s, cid, root.id))
    layout_cost = cost["phases"]["location_layout"]
    assert layout_cost["calls"] == 2 and layout_cost["errors"] == 2


def test_pilot_secret_vault_is_not_disclosed_by_preparation(game_client, admin_g, settings):
    cid, master, where, heads = _start(game_client, admin_g, settings, location_layouts_llm=True, scene_generation=True)
    master.preparer.llm = ScriptedLLM([_layout_answer])
    assert game_client.portal.call(prelude._open_first_place, master, cid, where)
    root = _root(settings, cid)
    areas = store.area_ids(root)

    res = _play(settings, cid, lambda ctx: execute(ctx, "prepare_location", {"location_id": root.id, "furnish": True}))
    assert res["ok"]
    _with_maker(settings, lambda maker: Orchestrator(InMemoryCoordination()).run_due(maker))

    vault_id, nave_id = areas["vault"], areas["nave"]
    secret_memories = rows(settings, MapMemory, MapMemory.entity_id.in_([vault_id, nave_id]))
    assert len(secret_memories) == 0

    view = _map(game_client, heads[0], cid)
    packet = json.dumps(view, ensure_ascii=False)
    assert vault_id not in packet and "Тайник" not in packet
    nave = next(a for a in view["location_map"]["areas"] if a["id"] == nave_id)
    assert nave["status"] == "prepared" and not nave["sketch"]["features"] and not nave["sketch"]["exits"]


def test_pilot_brief_has_no_plot_secrets(game_client, admin_g, settings):
    cid, master, where, _heads = _start(
        game_client, admin_g, settings, location_layouts_llm=True, scene_generation=True
    )
    scripted = ScriptedLLM([_layout_answer])
    master.preparer.llm = scripted
    assert game_client.portal.call(prelude._open_first_place, master, cid, where)

    assert len(scripted.requests) >= 1
    req_text = json.dumps(scripted.requests[0], ensure_ascii=False)
    assert "Смотритель порта в культе" not in req_text
    assert "Мать Ирса" not in req_text
    assert "Страницы вырваны" not in req_text
    assert "Сама слышит голос" not in req_text
