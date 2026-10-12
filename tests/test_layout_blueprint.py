"""Контракты blueprint и формы участков (спецификация 2026-10-12, §3.3, §4)."""

import json

import pytest

from app.core.layout import shapes
from app.core.layout.contracts import Blueprint, LayoutError, boundary_cells, runs
from tests.layout_pilot import two_rooms


def test_blueprint_json_round_trip_and_version():
    bp = two_rooms()
    data = bp.to_json()
    assert json.loads(json.dumps(data)) == data
    assert Blueprint.from_json(data) == bp
    with pytest.raises(LayoutError):
        Blueprint.from_json({**data, "schema_version": 2})
    with pytest.raises(LayoutError):
        Blueprint.from_json({"seed": 1})
    door = bp.passage("p_cell")
    assert bp.other(door, door.ends[0]).area_ref == "cell"
    assert [p.passage_ref for p, _ in bp.ends_of("hall")] == ["p_cell", "in_hall_w"]


@pytest.mark.parametrize("payload", [[1], "x", None])
def test_from_json_rejects_non_object_payload(payload):
    with pytest.raises(LayoutError):
        Blueprint.from_json(payload)


def test_from_json_rejects_non_numeric_schema_version():
    with pytest.raises(LayoutError):
        Blueprint.from_json({**two_rooms().to_json(), "schema_version": "abc"})


def test_from_json_rejects_malformed_nested_element():
    data = two_rooms().to_json()
    data["passages"][0]["ends"][0] = None
    with pytest.raises(LayoutError):
        Blueprint.from_json(data)


def test_boundary_and_runs():
    hall = two_rooms().area("hall")
    assert boundary_cells(hall, "e", 1, 2) == [(5, 1), (5, 2)]
    assert boundary_cells(hall, "n", 0, 2) == [(0, 0), (1, 0)]
    assert runs({(0, 0), (1, 0), (3, 0), (2, 1)}) == [(0, 0, 1, 0), (3, 0, 3, 0), (2, 1, 2, 1)]


def test_shapes_are_deterministic_masks():
    assert shapes.floor("rect", 3, 2, 0) == {(c, r) for c in range(3) for r in range(2)}
    ell = shapes.floor("l_shape", 4, 4, 0)
    assert (3, 0) not in ell and (0, 0) in ell and (3, 3) in ell and len(ell) == 12
    circle = shapes.floor("circle", 7, 7, 0)
    assert (0, 0) not in circle and (3, 3) in circle and (0, 3) in circle
    keep = frozenset({(0, 4)})
    cave = shapes.floor("cave", 10, 8, 5, keep)
    assert cave == shapes.floor("cave", 10, 8, 5, keep) and (0, 4) in cave
    assert cave <= shapes.floor("circle", 10, 8, 5)
    with pytest.raises(ValueError):
        shapes.floor("star", 3, 3, 0)


def test_inner_cell_walks_inward_to_floor():
    ell = shapes.floor("l_shape", 4, 4, 0)
    assert shapes.inner_cell(ell, 4, 4, "n", 3) == (3, 2)
    assert shapes.inner_cell(ell, 4, 4, "w", 1) == (0, 1)
    assert shapes.inner_cell(set(), 4, 4, "e", 0) is None
