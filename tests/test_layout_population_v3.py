"""Automatic dressing follows stable roles while keeping authored maps and circulation intact."""

from types import SimpleNamespace

import pytest

from app.content.catalog import Catalog, Entry
from app.core import reach, sketch
from app.core.layout import furnish
from app.core.layout.contracts import rect_cells
from app.core.layout.geometry import build_area
from app.core.layout.intent import DETAIL_VISUAL_KEYS, LayoutIntent
from app.core.layout.provider import DeterministicLayoutProvider
from app.core.layout.spatial import Mandate, default_spatial, intent_candidates
from app.core.world_generation.profiles import profile_ref_for


def _layout(role="room", *, cols=12, rows=12, **part):
    intent = LayoutIntent.model_validate(
        {
            "entry": "room",
            "parts": [
                {"part_ref": "room", "name": "A", "public_name": "A", "role": role, "cols": cols, "rows": rows, **part}
            ],
            "approaches": [{"part_ref": "room", "side": "w", "kind": "door", "public_name": "Entry"}],
        }
    )
    return DeterministicLayoutProvider().propose(intent, seed=7, root_id="root")


@pytest.mark.parametrize(
    "role,want",
    [
        ("common_room", {"feature:table", "feature:bench", "feature:hearth"}),
        ("bedroom", {"feature:bed", "feature:chest"}),
        ("warehouse", {"feature:crate", "feature:barrel", "feature:shelf"}),
        ("chapel", {"feature:altar", "feature:bench"}),
        ("pier", {"feature:net", "feature:mooring"}),
    ],
)
def test_empty_rooms_gain_role_specific_art_and_reachable_passages(role, want):
    bp = _layout(role)
    area = bp.area("room")
    assert 3 <= len(area.details) <= 16
    assert sum(d.kind != "light" for d in area.details) <= 8
    keys = {d.visual_key for d in area.details}
    assert want <= keys <= set(DETAIL_VISUAL_KEYS)
    sk = build_area(bp, area)
    assert reach.reach_errors(sk) == []
    assert all(tuple(c) not in reach.blocked_cells(sk) for x in sk["exits"] for c in x["cells"])


def test_seating_is_a_group_and_middle_aisles_stay_open():
    bp = _layout("common_room")
    area = bp.area("room")
    table = next(d for d in area.details if d.visual_key == "feature:table")
    benches = [d for d in area.details if d.visual_key == "feature:bench"]
    assert len(rect_cells(table.cells)) >= 2 and len(benches) >= 2
    for bench in benches:
        assert all(
            min(abs(x - a) + abs(y - b) for a, b in rect_cells(table.cells)) == 1 for x, y in rect_cells(bench.cells)
        )
    occupied = set().union(*(rect_cells(d.cells) for d in area.details))
    assert not any(x in (5, 6) or y in (5, 6) for x, y in occupied)


def test_dressing_scales_with_floor_and_ignores_localized_names():
    small = _layout("warehouse", cols=8, rows=8).area("room")
    large = _layout("warehouse", cols=20, rows=18).area("room")
    assert 3 <= len(small.details) < len(large.details) <= 8
    renamed = _layout("warehouse", cols=20, rows=18, name="Грот", public_name="Tavern").area("room")
    assert renamed.details == large.details


def test_natural_cave_uses_natural_art_and_corridor_stays_clear():
    cave = _layout("grotto", shape="cave").area("room")
    assert len(cave.details) >= 3
    assert {d.visual_key for d in cave.details} <= {
        "feature:rock",
        "feature:rubble",
        "feature:lichen",
        "feature:crystal",
        "feature:glow",
    }
    assert all(d.kind in {"nature", "light", "cover"} for d in cave.details)
    corridor = _layout("corridor", shape="corridor", cols=2, rows=12).area("room")
    assert len(corridor.details) <= 1


def test_sparse_authored_room_gets_infill_without_moving_or_replacing_authored_art():
    detail = {
        "detail_ref": "mark",
        "name": "Authored",
        "kind": "light",
        "cells": [[2, 2, 2, 2]],
        "visual_key": "feature:glow",
    }
    bp = _layout("warehouse", details=[detail])
    assert 3 <= len(bp.area("room").details) <= 8
    actual = next(d for d in bp.area("room").details if d.detail_ref == "mark")
    assert actual.cells == ((2, 2, 2, 2),) and actual.visual_key == "feature:glow"
    assert actual.name == "Authored" and actual.kind == "light"


@pytest.mark.parametrize(
    "template,role,want",
    [
        ("location.tavern", "common_room", {"feature:table", "feature:bench", "feature:hearth"}),
        ("location.cave", "grotto", {"feature:rock", "feature:rubble", "feature:lichen"}),
        ("location.port", "quay", {"feature:mooring", "feature:net", "feature:barrel"}),
    ],
)
def test_real_fallback_supplements_generator_placeholders_with_contextual_art(template, role, want):
    mandate = Mandate(place="Place", spatial=default_spatial("Place", template_id=template))
    intent = intent_candidates(mandate)[0]
    bp = DeterministicLayoutProvider().propose(intent, seed=7, root_id="root")
    entry = bp.area(intent.entry)
    generated = [d for d in entry.details if d.detail_ref.startswith("decor_")]
    assert len(generated) >= 3
    assert entry.role == role
    assert want <= {d.visual_key for d in generated} <= set(DETAIL_VISUAL_KEYS)
    for part in intent.parts:
        area = bp.area(part.part_ref)
        for original in part.details:
            actual = next(d for d in area.details if d.detail_ref == original.detail_ref)
            assert actual.name == original.name and actual.visual_key == original.visual_key
            assert actual.cells == tuple(tuple(rect) for rect in original.cells)
        build_area(bp, area)
    assert DeterministicLayoutProvider().propose(intent, seed=7, root_id="root") == bp


@pytest.mark.parametrize("template", ["location.cave", "location.mountain_pass"])
def test_generator_natural_landmarks_use_natural_art_without_name_matching(template):
    spatial = default_spatial("Place", template_id=template)
    for part in spatial.parts:
        part.name = "Warehouse"
        part.scenery = ["Cupboard", "Стойка"]
    intent = intent_candidates(Mandate(place="Place", spatial=spatial))[0]
    for part in intent.parts:
        assert [d.visual_key for d in part.details] == ["feature:rock", "feature:rubble"]
        assert all(d.kind == "nature" for d in part.details)


def test_infill_preserves_explicit_art_on_scenery_named_authored_detail():
    bp = _layout(
        "warehouse",
        details=[
            {"detail_ref": "scenery_0", "name": "Authored", "cells": [[2, 2, 2, 2]], "visual_key": "feature:glow"}
        ],
    )
    actual = next(d for d in bp.area("room").details if d.detail_ref == "scenery_0")
    assert actual.visual_key == "feature:glow" and actual.cells == ((2, 2, 2, 2),)


def test_tiny_authored_area_remains_valid_when_optional_infill_cannot_fit():
    bp = _layout(
        "warehouse",
        cols=3,
        rows=3,
        details=[
            {"detail_ref": "mark", "name": "Authored", "cells": [[2, 2, 2, 2]], "visual_key": "feature:torch"},
        ],
    )
    assert len(bp.area("room").details) == 1
    build_area(bp, bp.area("room"))


def test_fallback_containers_keep_wall_affinity_and_two_cell_aisle():
    sk = {
        "shape": "room",
        "cols": 12,
        "rows": 10,
        "party": [0, 5],
        "features": [],
        "walls": [],
        "exits": [{"name": "Exit", "side": "e", "at": 5, "kind": "door", "state": "open", "cells": [[11, 5]]}],
    }
    objects = [(f"en_{n}", "Chest") for n in range(5)]
    result, missing = furnish.place(sk, objects, 7, roles={key: "container" for key, _ in objects})
    assert missing == []
    assert all(any(x in (0, 11) or y in (0, 9) for x, y in reach.footprint(f)) for f in result["features"])
    assert not any(x in (5, 6) for f in result["features"] for x, _ in reach.footprint(f))
    assert reach.reach_errors(result) == []
    assert result == furnish.place(sk, objects, 7, roles={key: "container" for key, _ in objects})[0]


def test_container_fallback_clusters_near_storage_art():
    shelf = {
        "id": "shelf",
        "name": "Shelf",
        "kind": "furniture",
        "cells": [[1, 0, 2, 0]],
        "visual_key": "feature:shelf",
        "cover": "none",
        "hidden": False,
    }
    sk = {"shape": "room", "cols": 12, "rows": 10, "party": [6, 5], "features": [shelf], "walls": [], "exits": []}
    result, missing = furnish.place(sk, [("en_box", "Box")], 7, roles={"en_box": "container"})
    assert not missing
    box = next(f for f in result["features"] if f.get("entity_id") == "en_box")
    assert min(abs(x - a) + abs(y - b) for x, y in reach.footprint(box) for a, b in reach.footprint(shelf)) <= 2


def test_slot_binding_preserves_artwork_and_never_duplicates_existing_entity():
    mark = {
        "id": "sf_crate",
        "name": "Crate",
        "kind": "furniture",
        "cells": [[2, 1, 3, 1]],
        "visual_key": "feature:crate",
        "cover": "none",
        "hidden": False,
    }
    sk = {"shape": "room", "cols": 10, "rows": 8, "party": [0, 4], "features": [mark], "walls": [], "exits": []}
    slot = {
        "slot_ref": "cargo",
        "role": "container",
        "cells": mark["cells"],
        "feature_id": "sf_crate",
        "max_cols": 2,
        "max_rows": 1,
    }
    result, missing = furnish.place(
        sk,
        [("en_box", "Box"), ("en_box", "Box")],
        7,
        slots=[slot],
        roles={"en_box": "container"},
        sizes={"en_box": (2, 1)},
    )
    assert missing == [] and len(result["features"]) == 1
    assert result["features"][0] == {
        **mark,
        "name": "Box",
        "kind": "object",
        "entity_id": "en_box",
        "slot_ref": "cargo",
    }


def test_large_object_tries_valid_footprints_before_narrow_floor_edges():
    floor = (
        {(0, y) for y in range(30)}
        | {(x, 29) for x in range(30)}
        | {(x, y) for x in range(13, 17) for y in range(13, 17)}
        | {(x, 15) for x in range(14)}
    )
    sk = {
        "shape": "cave",
        "cols": 30,
        "rows": 30,
        "party": [0, 0],
        "features": [],
        "walls": [],
        "exits": [],
        "mask": sketch.encode_mask(floor, 30, 30),
    }
    result, missing = furnish.place(sk, [("en_table", "Worktable")], 7, sizes={"en_table": (3, 3)})
    assert missing == []
    assert reach.footprint(result["features"][0]) <= floor
    assert reach.reach_errors(result) == []


@pytest.mark.parametrize(
    "role,profile",
    [
        ("tavern", "tavern"),
        ("common_room", "tavern"),
        ("bedroom", "house"),
        ("kitchen", "house"),
        ("barracks", "barracks"),
        ("laboratory", "laboratory"),
        ("workshop", "workshop"),
        ("crypt", "crypt"),
        ("grotto", "cave"),
        ("storage", "warehouse"),
    ],
)
def test_stable_roles_select_existing_catalog_profiles(role, profile):
    ref = "scene_profile." + profile
    entry = Entry(ref, "scene_profile", "canon", "pack", {})
    catalog = Catalog({ref: entry}).view(allow_proposals=False)
    location = SimpleNamespace(state={"role": role}, template_id=None)
    assert profile_ref_for(location, catalog) == ref
    assert profile_ref_for(location, Catalog({}).view(allow_proposals=False)) == "minimal"
