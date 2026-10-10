"""World object ↔ sketch feature bindings, authorization and map projections."""

from app.tools.registry import execute
from tests.game import import_base, party
from tests.test_map import _map, _ok, _play


def test_linked_sketch_object_uses_one_visual_marker_and_revisions(client, admin, settings):
    import_base(settings)
    campaign, (player,), _hero = party(client, admin)
    cid = campaign["id"]
    sketch_data = {
        "shape": "room",
        "cols": 7,
        "rows": 5,
        "party": [1, 2],
        "walls": [],
        "exits": [],
        "features": [
            {"name": "Оружейная стойка", "kind": "furniture", "cells": [[4, 1, 5, 1]]},
            {"name": "Тайная полка", "kind": "object", "cells": [[6, 4, 6, 4]], "hidden": True},
        ],
    }

    async def create(ctx):
        room = await _ok(ctx, "create_location", {"name": "Оружейная", "make_current": True})
        sword = await _ok(ctx, "place_item", {"item_template_id": "item.longsword", "reason": "находка"})
        await _ok(ctx, "sketch_place", sketch_data)
        stored = ctx.world.entities[room["location_id"]].state["sketch"]
        feature_id = stored["features"][0]["id"]
        assert stored["edit_rev"] == 1
        assert stored["features"][1]["id"] != feature_id
        bind = await _ok(
            ctx,
            "bind_sketch_feature",
            {"feature_id": feature_id, "entity_id": sword["entity_id"], "expected_revision": 1},
        )
        assert bind["revision"] == 2
        stale = await execute(
            ctx,
            "bind_sketch_feature",
            {"feature_id": feature_id, "entity_id": None, "expected_revision": 1},
        )
        assert not stale["ok"] and "устаревшая ревизия" in stale["error"]
        return sword["entity_id"], feature_id

    entity_id, fid = _play(settings, cid, create)
    view = _map(client, player, cid)
    assert {v["id"] for v in view["around"]} >= {entity_id}
    assert entity_id not in {v["id"] for v in view["scene_view"]}
    feat = next(f for f in view["sketch"]["features"] if f["id"] == fid)
    assert feat["entity_id"] == entity_id
    assert feat["visual_key"] == "item:weapon"
    assert feat["entity_type"] == "item"
    assert view["sketch"]["edit_rev"] == 2

    async def conceal(ctx):
        await _ok(
            ctx,
            "edit_sketch",
            {"action": "hide", "target": "Оружейная стойка", "expected_revision": 2},
        )
        return ctx.world.entities[entity_id].state["visual_key"]

    assert _play(settings, cid, conceal) == "item:weapon"
    hidden = _map(client, player, cid)
    assert entity_id not in {x["id"] for x in hidden["around"]}
    assert entity_id not in {x["id"] for x in hidden["scene_view"]}
    assert fid not in {x.get("id") for x in hidden["sketch"]["features"]}

    async def reveal(ctx):
        await _ok(
            ctx,
            "edit_sketch",
            {"action": "reveal", "target": "Оружейная стойка", "expected_revision": 3},
        )

    _play(settings, cid, reveal)
    revealed = _map(client, player, cid)
    assert entity_id in {x["id"] for x in revealed["around"]}
    assert entity_id not in {x["id"] for x in revealed["scene_view"]}
    assert fid in {x.get("id") for x in revealed["sketch"]["features"]}


def test_sketch_binding_rejects_nested_object_and_duplicate_reference(client, admin, settings):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid = campaign["id"]
    data = {
        "shape": "room",
        "cols": 7,
        "rows": 5,
        "party": [1, 2],
        "features": [
            {"name": "Полка", "cells": [[4, 1, 4, 1]]},
            {"name": "Стол", "cells": [[5, 1, 5, 1]]},
        ],
    }

    async def exercise(ctx):
        await _ok(ctx, "create_location", {"name": "Склад", "make_current": True})
        obj = await _ok(ctx, "place_item", {"item_template_id": "item.dagger", "reason": "находка"})
        await _ok(ctx, "sketch_place", data)
        sk = ctx.world.entities[ctx.world.home()].state["sketch"]
        first, second = (f["id"] for f in sk["features"])
        await _ok(
            ctx,
            "bind_sketch_feature",
            {"feature_id": first, "entity_id": obj["entity_id"], "expected_revision": 1},
        )
        duplicate = await execute(
            ctx,
            "bind_sketch_feature",
            {"feature_id": second, "entity_id": obj["entity_id"], "expected_revision": 2},
        )
        assert not duplicate["ok"] and "уже привязана" in duplicate["error"]
        stale = await execute(ctx, "sketch_place", {**data, "expected_revision": 1})
        assert not stale["ok"] and "устаревшая ревизия" in stale["error"]
        no_revision = await execute(ctx, "sketch_place", data)
        assert not no_revision["ok"] and "expected_revision" in no_revision["error"]

        chest = await _ok(ctx, "create_container", {"name": "Сундук"})
        await _ok(ctx, "open_container", {"character_id": hero["id"], "container_id": chest["container_id"]})
        await _ok(
            ctx,
            "store_object",
            {"character_id": hero["id"], "container_id": chest["container_id"], "object_id": obj["entity_id"]},
        )
        other = await execute(
            ctx,
            "bind_sketch_feature",
            {"feature_id": first, "entity_id": obj["entity_id"], "expected_revision": 2},
        )
        assert not other["ok"] and "не принадлежит" in other["error"]

    _play(settings, cid, exercise)
