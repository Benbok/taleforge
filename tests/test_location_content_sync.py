from dataclasses import replace
from types import SimpleNamespace

import pytest

from app.core.layout import furnish
from app.core.layout.contracts import Blueprint
from app.core.world_generation.profiles import profile_ref_for
from tests.test_layout_furnish import FIELD
from tests.test_world_generation import _catalog, _generated, _prepare, _profile, _row


def test_role_selects_available_profile_and_explicit_wins():
    catalog = _catalog(replace(_profile(), id="scene_profile.warehouse"))
    location = SimpleNamespace(state={"role": "warehouse"}, template_id=None)
    assert profile_ref_for(location, catalog) == "scene_profile.warehouse"
    location.state["scene_profile"] = "minimal"
    assert profile_ref_for(location, catalog) == "minimal"


def test_existing_feature_footprints_are_reserved():
    feature = {"id": "old", "kind": "furniture", "name": "Table", "cells": [[1, 1, 4, 3]]}
    for seed in range(20):
        sk, _ = furnish.place({**FIELD, "features": [feature]}, [("new", "Chest")], seed)
        for item in sk["features"][1:]:
            c, r = item["cells"][0][:2]
            assert not (1 <= c <= 4 and 1 <= r <= 3)


def test_blueprint_preserves_explicit_object_slots():
    raw = {"schema_version": 1, "seed": 1, "entry": "room", "passages": [], "areas": [
        {"area_ref": "room", "name": "Room", "cols": 6, "rows": 5,
         "scene_profile": "minimal", "object_slots": [
             {"slot_ref": "chest", "role": "container", "cells": [[2, 2, 2, 2]], "detail_ref": "box"}]}]}
    area = Blueprint.from_json(raw).to_json()["areas"][0]
    assert area["scene_profile"] == "minimal"
    assert area["object_slots"][0]["slot_ref"] == "chest"


def test_container_binds_existing_detail_without_duplicate():
    feature = {"id": "box", "kind": "furniture", "name": "Box", "cells": [[2, 2, 2, 2]]}
    slots = [{"slot_ref": "chest", "role": "container", "detail_ref": "box",
              "cells": [[2, 2, 2, 2]], "max_cols": 1, "max_rows": 1}]
    sk, unplaced = furnish.place({**FIELD, "features": [feature]}, [("new", "Chest")], 3,
                                slots=slots, roles={"new": "container"})
    assert unplaced == []
    assert len(sk["features"]) == 1
    assert sk["features"][0]["entity_id"] == "new"
    assert sk["features"][0]["slot_ref"] == "chest"
    assert "entity_id" not in feature


def test_complex_allocation_is_stable_and_conserves_budget():
    from app.core.world_generation.policy import allocate_complex

    profiles = {"b": 2, "a": 1, "c": 1}
    assert allocate_complex(7, profiles) == {"a": 2, "b": 4, "c": 1}
    assert allocate_complex(7, dict(reversed(list(profiles.items())))) == allocate_complex(7, profiles)
    assert sum(allocate_complex(7, profiles).values()) == 7
    assert allocate_complex(0, profiles) == {"a": 0, "b": 0, "c": 0}


def test_reserved_profile_roundtrip_keeps_old_catalog_rules():
    from app.core.world_generation.profiles import freeze_profile, parse_profile, restore_profile

    profile = parse_profile(_profile(), _catalog())
    assert restore_profile(freeze_profile(profile)) == profile
    assert restore_profile(freeze_profile(profile)).cost_of("item.good") == 2


def test_warehouse_template_declares_container_slot():
    from app.core.layout.template_catalog import load_catalog

    template = next(t for t in load_catalog() if t.id == "port_quay_warehouse")
    warehouse = next(p for p in template.intent.parts if p.role == "warehouse")
    assert any(s.role == "container" and s.detail_ref for s in warehouse.object_slots)


def test_duplicate_slots_and_void_cells_are_rejected():
    from dataclasses import replace

    import pytest

    from app.core.layout.contracts import Area, ObjectSlot
    from app.core.layout.geometry import GeometryError, build_area

    slot = ObjectSlot("chest", "container", ((2, 2, 2, 2),))
    area = Area("room", "warehouse", "Room", "Room", "indoor", "rect", 6, 5, object_slots=(slot, slot))
    bp = Blueprint(1, "room", (area,), ())
    with pytest.raises(GeometryError):
        build_area(bp, area)
    with pytest.raises(GeometryError):
        build_area(bp, replace(area, object_slots=(replace(slot, cells=((6, 2, 6, 2),)),)))


def test_generated_item_move_updates_both_sketches_with_inverse():
    from app.core.layout.furnish import sync_objects
    from app.db.models import Entity

    old = Entity(id="old", kind="location", state={"sketch": {**FIELD, "blueprint": {"root_id": "root"},
        "features": [{"id": "sf_item", "entity_id": "item", "name": "Rope", "kind": "object",
                      "cells": [[2, 2, 2, 2]]}]}})
    new = Entity(id="new", kind="location", state={"sketch": {**FIELD, "blueprint": {"root_id": "root"}}})
    item = Entity(id="item", kind="object", name="Rope", location_id="new", state={"world_object": {
        "role": "item", "generation_ref": "g", "container_id": None}})
    ctx = SimpleNamespace(world=SimpleNamespace(entities={e.id: e for e in (old, new, item)}), signals=set())
    inverse = []
    sync_objects(ctx, inverse)
    assert not old.state["sketch"]["features"]
    assert any(f.get("entity_id") == "item" for f in new.state["sketch"]["features"])
    assert len(inverse) == 2 and "map.changed" in ctx.signals
    again = []
    sync_objects(ctx, again)
    assert again == []


def test_wide_object_respects_slot_size_and_keeps_footprint():
    slots = [{"slot_ref": "small", "role": "container", "cells": [[2, 2, 2, 2]],
              "max_cols": 1, "max_rows": 1}]
    sk, unplaced = furnish.place({**FIELD, "exits": []}, [("wide", "Wide chest")], 1,
                                slots=slots, roles={"wide": "container"}, sizes={"wide": (2, 1)})
    assert unplaced == []
    feature = sk["features"][0]
    assert feature.get("slot_ref") != "small"
    c0, _, c1, _ = feature["cells"][0]
    assert c1 - c0 == 1


def test_market_and_cache_receive_explicit_generated_slots():
    from app.core.layout.provider import DeterministicLayoutProvider
    from app.core.layout.template_catalog import load_catalog
    from app.core.layout.template_selection import adapt_template_hybrid
    from tests.test_layout_template_catalog import _greihall_port

    template = next(t for t in load_catalog() if t.id == "port_quay_warehouse")
    intent, _ = adapt_template_hybrid(template, _greihall_port())
    bp = DeterministicLayoutProvider().propose(intent, seed=22325528, root_id="root")
    assert all(bp.area(ref).object_slots for ref in ("part_market", "part_cache"))


def test_new_port_reserves_shared_budget_and_binds_warehouse(client, admin, settings):
    from app.core.layout.template_catalog import load_catalog
    from app.core.world_generation import storage
    from app.db.models import Entity
    from tests.game import run
    from tests.test_layout_preparation import _setup
    from tests.test_map import _ok, _play

    cid, _, hid = _setup(client, admin, settings)
    template = next(t for t in load_catalog() if t.id == "port_quay_warehouse")

    async def create(ctx):
        root = (await _ok(ctx, "create_location", {"name": "Port"}))["location_id"]
        out = await _ok(ctx, "prepare_complex", {"location_id": root,
            "intent": template.intent.model_dump(mode="json")})
        return root, out["operation_ref"]

    root_id, layout_ref = _play(settings, cid, create)
    assert _prepare(settings, cid, layout_ref) == "ready"
    root = run(settings, lambda s: s.get(Entity, root_id))
    reserve = root.state["content_reservation"]
    assert sum(r["budget"] for r in reserve["areas"].values()) <= reserve["random_budget"]
    for key, limit in reserve["limits"].items():
        assert sum(r["limits"][key] for r in reserve["areas"].values()) <= limit
    warehouse_id = root.state["areas"]["harbor_warehouse"]

    async def reserve_root_shell(ctx):
        row = await storage.reserve_root(ctx.session, ctx.campaign, ctx.world, ctx.world.entities[root_id])
        assert row.reservation["budget"] == 0
        assert row.reservation["limits"]["containers"] == 0
        return row.id

    _play(settings, cid, reserve_root_shell)

    async def prepare(ctx):
        ctx.campaign.settings = {**(ctx.campaign.settings or {}), "scene_generation": True}
        row = await storage.reserve_root(ctx.session, ctx.campaign, ctx.world, ctx.world.entities[warehouse_id])
        storage.activate(row)
        return row.id

    ref = _play(settings, cid, prepare)
    assert _prepare(settings, cid, ref) == "ready"
    assert _row(settings, ref).profile_ref == "scene_profile.warehouse"
    warehouse = run(settings, lambda s: s.get(Entity, warehouse_id))
    bound = [f for f in warehouse.state["sketch"]["features"] if f.get("slot_ref") == "cargo_chest"]
    assert len(bound) == 1 and bound[0].get("entity_id")
    assert len({e.id for e in _generated(settings, ref)}) == len(_generated(settings, ref))
    before = warehouse.state
    assert _prepare(settings, cid, ref) == "ready"
    assert run(settings, lambda s: s.get(Entity, warehouse_id)).state == before
    chest_id = bound[0]["entity_id"]

    async def open_chest(ctx):
        from app.tools.master.places import relocate_scene
        await relocate_scene(ctx, ctx.world.entities[warehouse_id], [])
        await _ok(ctx, "open_container", {"character_id": hid, "container_id": chest_id})
        out = await _ok(ctx, "search_container", {"character_id": hid, "container_id": chest_id})
        return out["operation_ref"]

    child_ref = _play(settings, cid, open_chest)
    assert _prepare(settings, cid, child_ref) == "ready"
    child = _row(settings, child_ref)
    assert child.reservation["budget"] <= _row(settings, ref).reservation["budget"]
    nested = _generated(settings, child_ref)
    warehouse = run(settings, lambda s: s.get(Entity, warehouse_id))
    linked = {f.get("entity_id") for f in warehouse.state["sketch"]["features"]}
    assert not {e.id for e in nested} & linked

    async def retrieve(ctx):
        for entity in nested:
            await _ok(ctx, "retrieve_object", {"character_id": hid, "container_id": chest_id,
                                                "object_id": entity.id})
        return ctx.world.entities[warehouse_id].state["sketch"]

    sk = _play(settings, cid, retrieve)
    assert {e.id for e in nested} <= {f.get("entity_id") for f in sk["features"]}

    async def split_observation(ctx):
        from app.db.models import Character, PartyMapMemory
        from app.tools.master.places import relocate_scene

        await relocate_scene(ctx, ctx.world.entities[root_id], [])
        watcher = Character(campaign_id=cid, name="Watcher", status="approved", location_id=warehouse_id,
                            sheet=dict(ctx.world.characters[hid].sheet))
        ctx.session.add(watcher)
        await ctx.session.flush()
        ctx.world.characters[watcher.id] = watcher
        room = ctx.world.entities[warehouse_id]
        raw = room.state["sketch"]
        features = [dict(f, name="Observed change") if f.get("id", "").endswith("overseer_des") else f
                    for f in raw["features"]]
        room.state = {**room.state, "sketch": {**raw, "features": features}}
        await ctx.record("test_observation")
        memory = await ctx.session.get(PartyMapMemory, (cid, root_id, warehouse_id))
        assert any(f["name"] == "Observed change" for f in memory.snapshot["geometry"]["features"])

    _play(settings, cid, split_observation)


@pytest.mark.parametrize("status", ["preparing", "ready"])
def test_publication_accounts_for_existing_root_reservation(client, admin, settings, status):
    from app.core.layout.template_catalog import load_catalog
    from app.core.world_generation import storage
    from app.db.models import Entity
    from tests.game import run
    from tests.test_layout_preparation import _setup
    from tests.test_map import _ok, _play

    cid, _, _ = _setup(client, admin, settings)
    template = next(t for t in load_catalog() if t.id == "port_quay_warehouse")

    async def create(ctx):
        root_id = (await _ok(ctx, "create_location", {"name": "Port", "template_id": "location.port",
                                                      "make_current": True}))["location_id"]
        await _ok(ctx, "place_item", {"item_template_id": "item.rope_hempen", "qty": 1,
                                       "location_id": root_id, "reason": "authored cargo"})
        root = ctx.world.entities[root_id]
        initial = await storage.reserve_root(ctx.session, ctx.campaign, ctx.world, root)
        initial.status = status
        initial.lease_token = "old-claim" if status == "preparing" else None
        out = await _ok(ctx, "prepare_complex", {"location_id": root_id,
            "intent": template.intent.model_dump(mode="json")})
        return root_id, initial.id, out["operation_ref"]

    root_id, initial_ref, layout_ref = _play(settings, cid, create)
    assert _prepare(settings, cid, layout_ref) == "ready"
    root = run(settings, lambda s: s.get(Entity, root_id))
    reservation = root.state["content_reservation"]
    initial = _row(settings, initial_ref)
    if status == "preparing":
        assert initial.reservation["budget"] == 0
        assert initial.status == "unprepared" and initial.lease_token is None
        assert reservation["authored_cost"] == 2
    else:
        assert reservation["random_budget"] == 0
        assert reservation["authored_cost"] == 16
        assert all(value == 0 for value in reservation["limits"].values())
