# ruff: noqa: F811
"""Разворот места каркаса в комплекс (спецификация 2026-10-12, §3.1, §3.2, §8, §9)."""

import copy

from app.core.layout import store
from app.core.world_generation import storage
from app.db.models import Campaign, CampaignSecret, Entity, WorldGenerationState
from app.tools.registry import execute
from tests.game import import_base, party, quiet, run
from tests.layout_plan_pilot import TEMPLE_SPATIAL, temple_plan
from tests.test_adventure import publish_sample
from tests.test_lead import set_plan
from tests.test_map import _ok, _play
from tests.test_master import rows
from tests.test_world_generation import _fast_retry, _prepare, _row  # noqa: F401 — фикстура

WGS = WorldGenerationState


def _campaign(client, admin, settings, plan=None, names=None, **flags):
    import_base(settings)
    c, heads, hero = party(client, admin, names=names)
    quiet(client)
    set_plan(settings, c["id"], plan or temple_plan())

    async def go(s):
        campaign = await s.get(Campaign, c["id"])
        campaign.settings = {**(campaign.settings or {}), **flags}
        await s.commit()

    run(settings, go)
    return c["id"]


def _develop(settings, cid, sketch_id="loc_port", here=False):
    return _play(settings, cid, lambda ctx: _ok(ctx, "develop", {"sketch_id": sketch_id, "details": "-", "here": here}))


def test_develop_reserves_layout_with_mandate(client, admin, settings):
    cid = _campaign(client, admin, settings, location_layouts=True)
    out = _develop(settings, cid)
    ref = out["layout"]["operation_ref"]
    row = _row(settings, ref)
    assert row.phase == "location_layout" and row.requested_at is not None and row.target_entity_id == out["entity_id"]
    mandate = row.reservation["mandate"]
    assert mandate["place"] == "Старый храм" and [p["ref"] for p in mandate["spatial"]["parts"]][0] == "road"
    assert [h["name"] for h in mandate["anchors"]] == ["Журнал смотрителя"]
    assert [h["key"] for h in mandate["residents"]] == ["npc:npc_warden"]
    assert "Смотритель порта в культе" not in str(mandate)  # секрет места в мандат не попадает
    assert _prepare(settings, cid, ref) == "ready"
    assert len(rows(settings, Entity, Entity.location_id == out["entity_id"])) == 6


def test_no_layout_without_flag_or_for_modules(client, admin, settings):
    cid = _campaign(client, admin, settings)
    assert "layout" not in _develop(settings, cid)
    assert not rows(settings, WGS, WGS.phase == "location_layout")

    mid = publish_sample(settings)
    c, _heads, _hero = party(client, admin, module_id=mid, module_hook="board", names=["Фарамир"])
    quiet(client)

    async def flag(s):
        camp = await s.get(Campaign, c["id"])
        camp.settings = {**(camp.settings or {}), "location_layouts": True}
        sec = await s.get(CampaignSecret, c["id"])
        p = copy.deepcopy(sec.plot)
        target_loc = next(loc for loc in p["locations"] if not loc.get("entity_id"))
        target_loc["spatial"] = copy.deepcopy(TEMPLE_SPATIAL)
        sec.plot = p
        await s.commit()

    run(settings, flag)
    sketch_id = next(
        loc["id"]
        for loc in run(settings, lambda s: s.get(CampaignSecret, c["id"])).plot["locations"]
        if not loc.get("entity_id")
    )
    out = _develop(settings, c["id"], sketch_id=sketch_id)
    assert "layout" not in out
    assert not rows(settings, WGS, WGS.campaign_id == c["id"], WGS.phase == "location_layout")


def test_place_without_spatial_gets_single_part_plan(client, admin, settings):
    plan = temple_plan()
    for loc in plan["locations"]:
        loc.pop("spatial", None)
    cid = _campaign(client, admin, settings, plan=plan, location_layouts=True)
    out = _develop(settings, cid, sketch_id="loc_tavern")
    row = _row(settings, out["layout"]["operation_ref"])
    sp = row.reservation["mandate"]["spatial"]
    assert sp["environment"] == "indoor" and [p["name"] for p in sp["parts"]] == [out["name"]]
    assert sp["approaches"][0]["kind"] == "door"
    assert _prepare(settings, cid, row.id) == "ready"
    assert rows(settings, Entity, Entity.location_id == out["entity_id"])  # таверна стала комплексом из участка


def test_wild_place_without_spatial_is_outdoor(client, admin, settings):
    plan = temple_plan()
    for loc in plan["locations"]:
        loc.pop("spatial", None)
    cid = _campaign(client, admin, settings, plan=plan, location_layouts=True)
    out = _develop(settings, cid, sketch_id="loc_port")  # Старый храм на шаблоне руин: wild
    row = _row(settings, out["layout"]["operation_ref"])
    sp = row.reservation["mandate"]["spatial"]
    assert sp["environment"] == "outdoor" and sp["parts"][0]["outdoor"] and sp["approaches"][0]["kind"] == "path"
    assert _prepare(settings, cid, row.id) == "ready"


def test_root_preparation_waits_for_structure(client, admin, settings):
    cid = _campaign(client, admin, settings, location_layouts=True, scene_generation=True)
    out = _develop(settings, cid, here=True)
    root_id = out["entity_id"]
    initial = run(settings, lambda s: storage.find(s, cid, root_id, "location_initial"))
    assert initial is not None and initial.requested_at is not None
    assert _prepare(settings, cid, initial.id) == "ready"  # тянет за собой структуру
    layout = run(settings, lambda s: storage.find(s, cid, root_id, "location_layout"))
    assert layout.status == "ready"
    journal = [e for e in rows(settings, Entity, Entity.campaign_id == cid) if e.name == "Журнал смотрителя"]
    assert journal == []  # носитель ждёт часовню, а не лёг у корня


def test_flags_are_patchable_and_known(client, admin, settings):
    from app.config import CAMPAIGN_FLAGS

    assert {"location_layouts", "location_layouts_llm"} <= set(CAMPAIGN_FLAGS)
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    r = client.patch(
        f"/api/campaigns/{c['id']}",
        json={"location_layouts": True, "location_layouts_llm": True},
        headers=admin,
    )
    assert r.status_code == 200 and r.json()["settings"]["location_layouts"] is True
    r = client.patch(f"/api/campaigns/{c['id']}", json={"location_layouts": None}, headers=admin)
    assert r.json()["settings"]["location_layouts"] is True  # None не сбрасывает флаг, как scene_generation


def test_enabling_mid_campaign_keeps_developed_places(client, admin, settings):
    cid = _campaign(client, admin, settings)
    out = _develop(settings, cid, here=True)

    async def on(s):
        campaign = await s.get(Campaign, cid)
        campaign.settings = {**campaign.settings, "location_layouts": True}
        await s.commit()

    run(settings, on)

    async def again(ctx):
        return await execute(ctx, "develop", {"sketch_id": "loc_port", "details": "-"})

    assert not _play(settings, cid, again)["ok"]  # уже развёрнут: ничего не пересобирается
    assert not rows(settings, WGS, WGS.target_entity_id == out["entity_id"], WGS.phase == "location_layout")
    assert store.blueprint_of(run(settings, lambda s: s.get(Entity, out["entity_id"]))) is None


def test_create_location_refuses_plot_sketch_and_points_to_develop(client, admin, settings):
    cid = _campaign(client, admin, settings, location_layouts=True)

    async def go(ctx):
        r = await execute(ctx, "create_location", {"name": "«Старый  ХРАМ»", "make_current": True})
        return r, [e.name for e in ctx.world.entities.values() if e.kind == "location"]

    r, places = _play(settings, cid, go)
    assert not r["ok"] and "develop" in r["error"] and "loc_port" in r["error"]
    assert "Старый храм" not in " ".join(places)  # двойник наброска не появился
    out = _develop(settings, cid)  # развёрнутый набросок больше не мешает create_location
    assert out["name"] == "Старый храм"


def test_entering_developed_place_closes_hero_move(client, admin, settings):
    cid = _campaign(client, admin, settings, location_layouts=True)

    async def go(ctx):
        await _ok(ctx, "develop", {"sketch_id": "loc_port", "details": "-", "here": True})
        heroes = {c.id for c in ctx.world.characters.values()}
        return heroes, set(ctx.closed)

    heroes, closed = _play(settings, cid, go)
    assert heroes and heroes <= closed  # вход со сценой — обработанный переход, не автоотмена
