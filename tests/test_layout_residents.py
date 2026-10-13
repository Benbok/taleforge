# ruff: noqa: F811
"""Жители и носители каркаса в своих участках (спецификация 2026-10-12, §3.1, §10: NPC и носители по каркасу)."""

from app.core.layout import store
from app.db.models import Entity
from app.tools.master.places import request_preparation
from tests.game import run
from tests.test_layout_develop import _campaign, _develop
from tests.test_layout_preparation import _areas
from tests.test_map import _ok, _play
from tests.test_master import rows
from tests.test_world_generation import _fast_retry, _prepare, _row  # noqa: F401 — фикстура


def test_resident_developed_before_structure_moves_in_on_publish(client, admin, settings):
    cid = _campaign(client, admin, settings, location_layouts=True)
    place = _develop(settings, cid)
    npc = _play(
        settings,
        cid,
        lambda ctx: _ok(ctx, "develop", {"sketch_id": "npc_warden", "details": "-", "here": False}),
    )
    assert run(settings, lambda s: s.get(Entity, npc["entity_id"])).location_id == place["entity_id"]
    ref = place["layout"]["operation_ref"]
    assert _prepare(settings, cid, ref) == "ready"
    areas = _areas(settings, place["entity_id"])
    assert run(settings, lambda s: s.get(Entity, npc["entity_id"])).location_id == areas["road"].id
    assert _row(settings, ref).result_manifest["residents"] == [npc["entity_id"]]


def test_resident_developed_after_structure_goes_home(client, admin, settings):
    cid = _campaign(client, admin, settings, location_layouts=True)
    place = _develop(settings, cid)
    _prepare(settings, cid, place["layout"]["operation_ref"])
    npc = _play(
        settings,
        cid,
        lambda ctx: _ok(ctx, "develop", {"sketch_id": "npc_warden", "details": "-", "here": False}),
    )
    root = run(settings, lambda s: s.get(Entity, place["entity_id"]))
    home = store.area_ids(root)[store.blueprint_of(root).anchors["npc:npc_warden"]]
    assert run(settings, lambda s: s.get(Entity, npc["entity_id"])).location_id == home


def test_carrier_appears_in_its_area_not_at_root(client, admin, settings):
    cid = _campaign(client, admin, settings, location_layouts=True)
    place = _develop(settings, cid)
    _prepare(settings, cid, place["layout"]["operation_ref"])
    root = run(settings, lambda s: s.get(Entity, place["entity_id"]))
    chapel_ref = store.blueprint_of(root).anchors[
        next(k for k in store.blueprint_of(root).anchors if not k.startswith("npc:"))
    ]
    chapel_id = store.area_ids(root)[chapel_ref]

    async def enter(ctx):
        return await request_preparation(ctx, ctx.world.entities[chapel_id], [])

    out = _play(settings, cid, enter)
    assert _prepare(settings, cid, out["operation_ref"]) == "ready"
    journal = [e for e in rows(settings, Entity, Entity.campaign_id == cid) if e.name == "Журнал смотрителя"]
    assert len(journal) == 1 and journal[0].location_id == chapel_id
