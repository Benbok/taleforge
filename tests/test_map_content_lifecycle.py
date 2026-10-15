import copy
from types import SimpleNamespace

import pytest

from app.core import sketch
from app.gateway.protocol import MapSketchFeature
from tests.test_layout_furnish import FIELD


@pytest.fixture
def port(client, admin, settings):
    from app.core.layout.template_catalog import load_catalog
    from app.db.models import Entity
    from tests.game import run
    from tests.test_layout_preparation import _setup
    from tests.test_map import _ok, _play
    from tests.test_world_generation import _prepare

    cid, heads, hid = _setup(client, admin, settings)
    template = next(t for t in load_catalog() if t.id == "port_quay_warehouse")

    async def create(ctx):
        root = (await _ok(ctx, "create_location", {"name": "Port"}))["location_id"]
        out = await _ok(ctx, "prepare_complex", {"location_id": root,
            "intent": template.intent.model_dump(mode="json")})
        return root, out["operation_ref"]

    root, ref = _play(settings, cid, create)
    assert _prepare(settings, cid, ref) == "ready"
    areas = run(settings, lambda s: s.get(Entity, root)).state["areas"]

    def enter(ref):
        async def move(ctx):
            ctx.campaign.settings = {**ctx.campaign.settings, "scene_generation": True}
            return await _ok(ctx, "move", {"character_ids": [hid], "location_id": areas[ref]})
        out = _play(settings, cid, move)
        if out.get("operation_ref"):
            assert _prepare(settings, cid, out["operation_ref"]) == "ready"

    return cid, heads, hid, root, areas, enter


def test_pier_warehouse_loot_roundtrip_and_legacy_reservation(port, settings):
    from app.core.world_generation import storage
    from app.db.models import Entity
    from tests.game import run
    from tests.test_map import _ok, _play
    from tests.test_world_generation import _prepare, _row

    cid, _, hid, _, areas, enter = port
    enter("cargo_pier")
    enter("harbor_warehouse")
    room = run(settings, lambda s: s.get(Entity, areas["harbor_warehouse"]))
    chest = next(f["entity_id"] for f in room.state["sketch"]["features"] if f.get("slot_ref") == "cargo_chest")

    async def search(ctx):
        await _ok(ctx, "open_container", {"character_id": hid, "container_id": chest})
        return await _ok(ctx, "search_container", {"character_id": hid, "container_id": chest})

    out = _play(settings, cid, search)
    ref = out["operation_ref"]
    assert _prepare(settings, cid, ref) == "ready"
    manifest = copy.deepcopy(_row(settings, ref).result_manifest)
    found = _play(settings, cid, search)["contents"]
    assert found
    item = found[0]["id"]

    async def retrieve(ctx):
        await _ok(ctx, "retrieve_object", {"character_id": hid, "container_id": chest, "object_id": item})
        return copy.deepcopy(ctx.world.entities[areas["harbor_warehouse"]].state["sketch"])

    sketch_before = _play(settings, cid, retrieve)
    assert any(f.get("entity_id") == item for f in sketch_before["features"])
    enter("cargo_pier")
    enter("harbor_warehouse")
    assert _row(settings, ref).result_manifest == manifest
    assert run(settings, lambda s: s.get(Entity, areas["harbor_warehouse"])).state["sketch"] == sketch_before

    async def legacy(ctx):
        row = await storage.find(ctx.session, cid, chest, "container_contents")
        row.reservation = {k: v for k, v in row.reservation.items() if k != "profile_snapshot"}
        return row.id, copy.deepcopy(row.reservation)

    legacy_ref, reservation = _play(settings, cid, legacy)
    assert _prepare(settings, cid, legacy_ref) == "ready"
    assert _row(settings, legacy_ref).reservation == reservation
    assert _row(settings, legacy_ref).result_manifest == manifest


def test_pickup_binding_and_memory_roll_back_atomically(port, settings):
    from app.db.models import Campaign, Entity, PartyMapMemory
    from app.tools.runtime import open_context
    from tests.game import QueueDice, run
    from tests.test_map import _ok, _play

    cid, _, hid, root, areas, enter = port
    enter("harbor_warehouse")
    room_id = areas["harbor_warehouse"]

    async def put(ctx):
        item = await _ok(ctx, "place_item", {"item_template_id": "item.rope_hempen", "reason": "rollback test"})
        entity = ctx.world.entities[item["entity_id"]]
        from app.core.layout.furnish import sync_objects
        sync_objects(ctx, [], include={entity.id})
        await ctx.record("placed_for_rollback", target_id=entity.id)
        return entity.id

    eid = _play(settings, cid, put)
    before = copy.deepcopy(run(settings, lambda s: s.get(Entity, room_id)).state)
    memory_before = copy.deepcopy(run(settings, lambda s: s.get(PartyMapMemory, (cid, root, room_id))).snapshot)

    async def attempt(session):
        ctx = await open_context(session, await session.get(Campaign, cid), QueueDice([]), turn_id=None, seat_id=None)
        await _ok(ctx, "pick_up_item", {"character_id": hid, "entity_id": eid})
        assert not any(f.get("entity_id") == eid for f in ctx.world.entities[room_id].state["sketch"]["features"])
        assert any(d.get("table") == "entities" and d.get("id") == room_id for d in ctx.events[-1].inverse)
        await session.rollback()

    run(settings, attempt)
    assert run(settings, lambda s: s.get(Entity, room_id)).state == before
    assert run(settings, lambda s: s.get(PartyMapMemory, (cid, root, room_id))).snapshot == memory_before

    async def pickup(ctx):
        await _ok(ctx, "pick_up_item", {"character_id": hid, "entity_id": eid})
        return copy.deepcopy(ctx.events[-1].inverse)

    undo = _play(settings, cid, pickup)

    async def replay(session):
        from app.db.models import Character, InventoryItem, MapMemory, Scene

        tables = {"entities": Entity, "inventory": InventoryItem, "characters": Character,
                  "scenes": Scene, "map_memories": MapMemory, "party_map_memories": PartyMapMemory}
        for delta in reversed(undo):
            model = tables[delta["table"]]
            key = delta.get("id")
            row = delta.get("row")
            if delta.get("op") == "restore":
                data = dict(row)
                if model is Entity:
                    data["campaign_id"] = cid
                session.add(model(**data))
                continue
            obj = await session.get(model, tuple(key) if isinstance(key, list) else key)
            if delta.get("op") == "delete":
                if obj is not None:
                    await session.delete(obj)
            else:
                setattr(obj, delta["field"], delta["before"])
        await session.commit()

    run(settings, replay)
    assert run(settings, lambda s: s.get(Entity, eid)).location_id == room_id
    assert run(settings, lambda s: s.get(Entity, room_id)).state == before
    assert run(settings, lambda s: s.get(PartyMapMemory, (cid, root, room_id))).snapshot == memory_before


def test_blueprint_feature_matches_wire_contract_without_private_slot():
    raw = {**FIELD, "features": [{"id": "box", "name": "Box", "kind": "furniture",
                                "cells": [[2, 2, 2, 2]], "solid": False, "slot_ref": "cargo"}]}
    feature = sketch.project_for_viewer(raw, False, set(), {}, "room")["features"][0]
    assert "slot_ref" not in feature
    assert MapSketchFeature.model_validate(feature).solid is False


def test_scene_companion_link_matches_wire_contract():
    from app.gateway.protocol import MapSceneToken

    token = {"id": "npc", "name": "Guide", "type": "npc", "mine": False, "down": False,
             "zone": None, "bearing": None, "cell": None, "companion_of": "hero"}
    assert MapSceneToken.model_validate(token).companion_of == "hero"


def test_unrelated_event_does_not_search_or_relayout_world():
    from app.core.layout.furnish import sync_objects

    class Untouched(dict):
        def values(self):
            raise AssertionError("unrelated event scanned every entity")

    ctx = SimpleNamespace(world=SimpleNamespace(entities=Untouched()), signals=set())
    sync_objects(ctx, [], changed=set(), rooms=set())


@pytest.mark.parametrize("order", [("cargo_pier", "harbor_warehouse"), ("harbor_warehouse", "cargo_pier")])
def test_parallel_preparation_keeps_pinned_shares_and_single_manifest(port, settings, order):
    import asyncio

    from app.core.world_generation import storage
    from app.core.world_generation.service import Orchestrator
    from app.db.models import Entity
    from app.gateway.coordination import InMemoryCoordination
    from tests.game import run
    from tests.test_map import _play
    from tests.test_world_generation import _row, _with_maker

    cid, _, _, root, areas, _ = port
    reserve = copy.deepcopy(run(settings, lambda s: s.get(Entity, root)).state["content_reservation"])
    refs = []
    for area in order:
        async def request(ctx, area=area):
            row = await storage.reserve_root(ctx.session, ctx.campaign, ctx.world, ctx.world.entities[areas[area]])
            storage.activate(row)
            return row.id
        refs.append(_play(settings, cid, request))
    async def prepare(maker):
        orchestrator = Orchestrator(InMemoryCoordination())
        return await asyncio.gather(*(orchestrator.prepare(maker, cid, ref) for ref in [*refs, refs[0]]))

    assert _with_maker(settings, prepare) == ["ready"] * 3
    manifest = copy.deepcopy(_row(settings, refs[0]).result_manifest)
    assert _with_maker(settings, prepare) == ["ready"] * 3
    assert _row(settings, refs[0]).result_manifest == manifest
    assert run(settings, lambda s: s.get(Entity, root)).state["content_reservation"] == reserve


def test_destroyed_binding_is_removed_once(port, settings):
    from tests.test_map import _play

    cid, _, _, _, areas, enter = port
    enter("harbor_warehouse")

    async def destroy(ctx):
        room = ctx.world.entities[areas["harbor_warehouse"]]
        feature = next(f for f in room.state["sketch"]["features"] if f.get("entity_id"))
        entity = ctx.world.entities[feature["entity_id"]]
        inverse = [{"table": "entities", "id": entity.id, "field": "state", "before": copy.deepcopy(entity.state)}]
        entity.state = {**entity.state, "world_object": {**entity.state["world_object"], "physical": "destroyed"}}
        await ctx.record("destroy_object", target_id=entity.id, inverse=inverse)
        assert not any(f.get("entity_id") == entity.id for f in room.state["sketch"]["features"])
        revision = room.state["sketch"]["edit_rev"]
        await ctx.record("repeat_destroy", target_id=entity.id)
        assert room.state["sketch"]["edit_rev"] == revision
        assert "map.changed" in ctx.signals

    _play(settings, cid, destroy)


def test_unobserved_changes_stay_remembered_until_another_hero_observes(port, settings, client):
    import json

    from app.db.models import Character, PartyMapMemory
    from tests.game import run
    from tests.test_map import _map, _play

    cid, heads, hid, root, areas, enter = port
    enter("cargo_pier")
    packet = _map(client, heads[0], cid)
    outline = next(a for a in packet["location_map"]["areas"] if a["id"] == areas["harbor_warehouse"])
    assert outline["status"] == "prepared" and not outline["sketch"]["features"]
    assert "object_slots" not in json.dumps(packet) and "slot_ref" not in json.dumps(packet)
    enter("harbor_warehouse")
    enter("cargo_pier")
    key = (cid, root, areas["harbor_warehouse"])
    before = copy.deepcopy(run(settings, lambda s: s.get(PartyMapMemory, key)).snapshot)

    async def change(ctx):
        room = ctx.world.entities[areas["harbor_warehouse"]]
        raw = room.state["sketch"]
        features = [dict(f, name="New unseen sign") if not f.get("entity_id") else f for f in raw["features"]]
        inverse = [{"table": "entities", "id": room.id, "field": "state", "before": copy.deepcopy(room.state)}]
        room.state = {**room.state, "sketch": {**raw, "features": features}}
        await ctx.record("change_unobserved_room", target_id=room.id, inverse=inverse)

    _play(settings, cid, change)
    assert run(settings, lambda s: s.get(PartyMapMemory, key)).snapshot == before
    assert "New unseen sign" not in json.dumps(_map(client, heads[0], cid))

    async def second_hero(ctx):
        hero = Character(campaign_id=cid, name="Scout", status="approved", location_id=areas["harbor_warehouse"],
                         sheet=dict(ctx.world.characters[hid].sheet))
        ctx.session.add(hero)
        await ctx.session.flush()
        ctx.world.characters[hero.id] = hero
        await ctx.record("scout_observed")

    _play(settings, cid, second_hero)
    remembered = next(a for a in _map(client, heads[0], cid)["location_map"]["areas"]
                      if a["id"] == areas["harbor_warehouse"])
    assert remembered["status"] == "remembered" and "New unseen sign" in json.dumps(remembered)
    assert not any(f.get("entity_id") for f in remembered["sketch"]["features"])
