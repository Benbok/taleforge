# ruff: noqa: F811 — shared integration fixtures
"""Первая сцена внутри комплекса (спецификация 2026-10-12, §6, §8): вход фиксируется до вступления."""

from sqlalchemy import select

from app.agents import prelude
from app.core.layout import spatial, store
from app.db.models import Campaign, Character, Entity, Event, LlmCall, MapMemory, Scene, WorldGenerationState
from tests.game import party, run
from tests.layout_plan_pilot import temple_plan
from tests.test_lead import set_plan
from tests.test_master import admin_g, dice, game_client, llm, rows  # noqa: F401

WGS = WorldGenerationState


def _start(game_client, admin_g, settings, **flags):
    c, _, _ = party(game_client, admin_g)
    master = game_client.app.state.master
    game_client.portal.call(master.wait_idle, c["id"])
    plan = temple_plan()
    plan["acts"][0]["nodes"][0]["npc_ids"] = ["npc_warden"]
    set_plan(settings, c["id"], plan)

    async def on(s):
        campaign = await s.get(Campaign, c["id"])
        campaign.settings = {**campaign.settings, "location_layouts": True, **flags}
        await s.commit()

    run(settings, on)
    return c["id"], master, plan["locations"][0]


def _root(settings, cid):
    async def go(s):
        found = await s.scalars(select(Entity).where(Entity.campaign_id == cid, Entity.kind == "location"))
        return next(e for e in found if (e.state or {}).get("blueprint") or (e.state or {}).get("plot_id"))

    return run(settings, go)


def test_opening_walks_into_entry_before_intro(game_client, admin_g, llm, settings):
    cid, master, where = _start(game_client, admin_g, settings)
    assert game_client.portal.call(prelude._open_first_place, master, cid, where)
    root = _root(settings, cid)
    areas = store.area_ids(root)
    entry = areas[store.blueprint_of(root).entry]
    (scene,) = rows(settings, Scene, Scene.campaign_id == cid)
    heroes = rows(settings, Character, Character.campaign_id == cid)
    assert scene.location_id == entry and all(
        h.location_id == entry for h in heroes if h.status in ("approved", "active")
    )
    memories = rows(settings, MapMemory)
    assert memories and {m.entity_id for m in memories} == {entry}  # открыт только входной участок
    warden = next(e for e in rows(settings, Entity, Entity.campaign_id == cid) if e.name == "Бертольд")
    assert warden.location_id == entry
    initial = rows(settings, WGS, WGS.phase == "location_initial")
    assert {r.target_entity_id for r in initial} <= {root.id, entry}  # соседей не наполняли


def test_second_opening_does_not_enter_again(game_client, admin_g, llm, settings):
    cid, master, where = _start(game_client, admin_g, settings)
    assert game_client.portal.call(prelude._open_first_place, master, cid, where)
    before = (len(rows(settings, WGS)), len(rows(settings, Event, Event.tool == "traverse_passage")))
    assert game_client.portal.call(prelude._open_first_place, master, cid, where)
    assert (len(rows(settings, WGS)), len(rows(settings, Event, Event.tool == "traverse_passage"))) == before
    assert not rows(settings, LlmCall, LlmCall.purpose == "location_layout")


def test_blocked_structure_keeps_heroes_outside(game_client, admin_g, llm, settings, monkeypatch):
    cid, master, where = _start(game_client, admin_g, settings)
    monkeypatch.setattr(spatial, "intent_candidates", lambda m: [])
    assert game_client.portal.call(prelude._open_first_place, master, cid, where)
    root = _root(settings, cid)
    (scene,) = rows(settings, Scene, Scene.campaign_id == cid)
    assert scene.location_id == root.id and store.blueprint_of(root) is None
    assert not rows(settings, Entity, Entity.location_id == root.id, Entity.kind == "location")
    assert not rows(settings, MapMemory)


def test_intro_text_is_written_after_entry(game_client, admin_g, llm, settings, monkeypatch):
    cid, master, _where = _start(game_client, admin_g, settings)
    seen = []

    async def write(svc, campaign, *_args, **_kwargs):
        async with svc.maker() as s:
            seen.append((await s.get(Scene, campaign.id)).location_id)
        return "Дорога у храма."

    monkeypatch.setattr(prelude, "_intro_text", write)
    game_client.portal.call(prelude.introduce_campaign, master, cid)
    root = _root(settings, cid)
    assert seen == [store.area_ids(root)[store.blueprint_of(root).entry]]
