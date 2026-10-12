"""Проверка blueprint (спецификация 2026-10-12, §3.2, §4, §5): лимиты, стыки, края, достижимость и обязательства."""

from dataclasses import replace

from app.core.layout.contracts import Area, Blueprint, Edge, End
from app.core.layout.validation import validate
from tests.layout_pilot import two_fields, two_rooms


def test_pilots_are_valid():
    assert validate(two_rooms()) == []
    assert validate(two_fields()) == []


def test_misaligned_door_and_overlap():
    bp = two_rooms()
    shifted = replace(bp.area("cell"), offset=(6, 1))
    assert any("не совпадают на плане" in e for e in validate(replace(bp, areas=(bp.area("hall"), shifted))))
    inside = replace(bp.area("cell"), offset=(5, 0))
    assert any("пересекаются" in e for e in validate(replace(bp, areas=(bp.area("hall"), inside))))


def test_limits_and_wide_door():
    many = tuple(Area(f"a{i}", "room", "A", "A", "indoor", "rect", 2, 2, (i * 2, 0)) for i in range(13))
    assert any("от 1 до 12" in e for e in validate(Blueprint(seed=1, entry="a0", areas=many, passages=())))
    bp = two_rooms()
    wide = replace(bp.passage("p_cell"), ends=(End("hall", "e", 1, 2), End("cell", "w", 1, 2)))
    assert any("шире одной клетки" in e for e in validate(replace(bp, passages=(wide, bp.passage("in_hall_w")))))


def test_vertical_passage_needs_two_levels():
    bp = two_rooms()
    stairs = replace(bp.passage("p_cell"), kind="stairs")
    assert any("разные уровни" in e for e in validate(replace(bp, passages=(stairs, bp.passage("in_hall_w")))))


def test_open_edges_must_be_covered_and_match_passages():
    bp = two_fields()
    west = replace(bp.area("west"), edges=bp.area("west").edges[:-1])  # нет отрезка w 4..5
    assert any("без пропусков" in e for e in validate(replace(bp, areas=(west, bp.area("east")))))
    wrong = tuple(Edge(g.side, g.start, g.length, "obstacle") if g.meaning == "continuation" else g
                  for g in bp.area("east").edges)  # fmt: skip
    east = replace(bp.area("east"), edges=wrong)
    assert any("p_east" in e for e in validate(replace(bp, areas=(bp.area("west"), east))))


def test_stream_must_join_across_the_edge():
    errors = validate(two_fields(stream_shift=1))
    assert any("«stream» обрывается" in e for e in errors)


def test_required_area_behind_secret_and_orphans():
    bp = two_rooms(required=("cell",))
    secret = replace(bp.passage("p_cell"), hidden=True)
    errors = validate(replace(bp, passages=(secret, bp.passage("in_hall_w"))))
    assert any("только через тайный проход" in e for e in errors)
    lonely = replace(bp, passages=(bp.passage("in_hall_w"),), required=())
    assert any("cell не связан с входом" in e for e in validate(lonely))
    assert any("нет участка crypt" in e for e in validate(two_rooms(anchors={"relic": "crypt"})))


def test_obstacle_edge_cannot_extend_past_its_side():
    bp = two_fields()
    west = bp.area("west")
    edges = tuple(replace(g, length=g.length + 1) if g.side == "n" else g for g in west.edges)
    invalid = replace(bp, areas=(replace(west, edges=edges), bp.area("east")))
    assert any("вне стороны" in e for e in validate(invalid))
