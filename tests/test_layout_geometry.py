"""Геометрия участка из blueprint (спецификация 2026-10-12, §3.3): эскиз, маска и связность проходов."""

from dataclasses import replace

import pytest

from app.core import sketch
from app.core.layout.contracts import Area, Blueprint, Detail, End, Passage
from app.core.layout.geometry import GeometryError, build_area
from tests.layout_pilot import two_rooms


def test_build_area_is_a_valid_sketch_with_passage_cells():
    bp = two_rooms()
    ids = {"hall": "en_hall", "cell": "en_cell"}
    sk = build_area(bp, bp.area("hall"), root_id="en_root", ids=ids)
    assert sketch.check(sk, {"en_cell", "en_outside"}) == []
    assert sk == build_area(bp, bp.area("hall"), root_id="en_root", ids=ids)
    assert sk["walls"] == [[2, 1]] and "mask" not in sk and sk["shape"] == "room"
    door = next(x for x in sk["exits"] if x["passage_ref"] == "p_cell")
    assert door["to"] == "en_cell" and door["cells"] == [[5, 2]] and door["state"] == "closed"
    gate = next(x for x in sk["exits"] if x["passage_ref"] == "in_hall_w")
    assert gate["to"] == "en_outside" and sk["party"] == gate["cells"][0] == [0, 1]
    assert sk["blueprint"] == {"root_id": "en_root", "area_ref": "hall", "rev": 1}


def test_solid_detail_on_a_door_is_rejected():
    bp = two_rooms()
    hall = replace(bp.area("hall"), details=(Detail("pillar", "Колонна", "cover", ((5, 2, 5, 2),), solid=True),))
    with pytest.raises(GeometryError) as e:
        build_area(replace(bp, areas=(hall, bp.area("cell"))), hall)
    assert any("загорожен" in m for m in e.value.errors)


def test_solid_detail_keeps_visual_identity_and_blocking_cells():
    from app.core import reach

    bp = two_rooms()
    sk = build_area(bp, bp.area("hall"))
    solid_features = [f for f in sk["features"] if f.get("solid")]
    assert solid_features
    for feature in solid_features:
        cells = reach.footprint(feature)
        assert cells <= sketch.solid_cells(sk)
        assert cells <= reach.blocked_cells(sk)
        assert feature["name"] and feature["kind"]
        assert feature["cover"] == "none"
    assert sketch.check(sk, {x["to"] for x in sk["exits"] if x["to"]}) == []


def test_rubble_cutting_the_room_is_rejected():
    bp = two_rooms()
    hall = replace(bp.area("hall"), details=(Detail("rubble", "Завал", "nature", ((3, 0, 3, 3),), solid=True),))
    with pytest.raises(GeometryError) as e:
        build_area(replace(bp, areas=(hall, bp.area("cell"))), hall)
    assert any("не пройти от входа" in m for m in e.value.errors)


def test_cave_keeps_passage_cells_and_is_deterministic():
    cave = Area("cave", "room", "Грот", "Грот", "indoor", "cave", 9, 7)
    bp = Blueprint(
        seed=11,
        entry="cave",
        areas=(cave,),
        passages=(
            Passage("in_cave_w", "gap", "Лаз", "Лаз", (End("cave", "w", 3, 1), End(place_id="en_out"))),
            Passage("in_cave_e", "gap", "Щель", "Щель", (End("cave", "e", 3, 1), End(place_id="en_out2"))),
        ),
    )
    a, b = build_area(bp, cave), build_area(bp, cave)
    assert a == b and "mask" in a and a["shape"] == "cave"
    floor = sketch.floor_cells(a)
    assert all(tuple(c) in floor for x in a["exits"] for c in x["cells"])
