"""Детерминированный provider структуры (спецификация 2026-10-12, §3.2, §8): пилот храма и поля, fallback."""

import pytest
from pydantic import ValidationError

from app.core.layout.contracts import End, LayoutError, terrain_cells
from app.core.layout.intent import LayoutIntent
from app.core.layout.provider import DeterministicLayoutProvider
from app.core.layout.validation import validate
from tests.layout_pilot import pilot_intent

ALL = {"road", "brook", "narthex", "nave", "chapel", "sacristy", "vault", "crypt"}


def test_pilot_intent_gives_valid_stable_blueprint():
    p = DeterministicLayoutProvider()
    bp = p.propose(pilot_intent(), seed=42, root_id="en_temple")
    assert validate(bp) == []
    assert p.propose(pilot_intent(), seed=42, root_id="en_temple").to_json() == bp.to_json()
    assert {a.area_ref: a.offset for a in bp.areas} == {
        "road": (0, 0), "brook": (12, 0), "narthex": (3, -4), "nave": (2, -14), "chapel": (10, -12),
        "sacristy": (-2, -11), "vault": (-2, -14), "crypt": (2, -14),
    }  # fmt: skip
    assert bp.area("crypt").level == -1 and bp.passage("p_crypt").kind == "stairs"
    assert bp.passage("p_vault").hidden and bp.area("vault").secret
    assert bp.passage("p_narthex").state == "closed" and len(bp.area("nave").details) == 5
    assert bp.anchors == {"relic": "chapel"} and set(bp.required) == {"chapel", "crypt"}
    edge = bp.passage("p_brook")
    assert edge.kind == "edge" and edge.ends[0].width == 10
    gate = bp.passage("in_road_w")
    assert gate.ends[0] == End("road", "w", 3, 2) and gate.ends[1].place_id == "en_village"


def test_pilot_terrain_joins_and_edges():
    bp = DeterministicLayoutProvider().propose(pilot_intent(), seed=42, root_id="en_temple")
    road, brook = bp.area("road"), bp.area("brook")
    assert terrain_cells(road, "bridge") == {(6, 7)}
    assert {(11, 3), (11, 4)} <= terrain_cells(road, "road") and {(0, 3), (0, 4)} <= terrain_cells(brook, "road")
    assert (11, 7) in terrain_cells(road, "stream") and (0, 7) in terrain_cells(brook, "stream")
    west = [(g.start, g.length, g.meaning) for g in road.edges if g.side == "w"]
    assert west == [(0, 3, "obstacle"), (3, 2, "boundary"), (5, 5, "obstacle")]
    assert [(g.start, g.length, g.meaning) for g in brook.edges if g.side == "w"] == [(0, 10, "continuation")]


def test_fallback_chain_keeps_required_parts_and_anchors():
    bp = DeterministicLayoutProvider().propose(pilot_intent(), seed=42, root_id="en_temple", fallback=True)
    assert validate(bp) == []
    assert {a.area_ref for a in bp.areas} == ALL and bp.anchors == {"relic": "chapel"}
    assert bp.passage("p_vault").hidden


def test_required_secret_part_is_unsatisfiable():
    data = pilot_intent().model_dump()
    data["parts"][-1]["secret"] = True  # обязательная крипта только за тайным ходом
    intent = LayoutIntent.model_validate(data)
    for fallback in (False, True):
        with pytest.raises(LayoutError) as e:
            DeterministicLayoutProvider().propose(intent, seed=1, root_id="en_t", fallback=fallback)
        assert any("тайный проход" in m for m in e.value.errors)


def test_intent_rejects_forward_references_and_unknown_band():
    data = pilot_intent().model_dump()
    data["parts"][1]["connects_to"] = "crypt"
    with pytest.raises(ValidationError):
        LayoutIntent.model_validate(data)
    data = pilot_intent().model_dump()
    data["approaches"][0]["band"] = "river"
    with pytest.raises(ValidationError):
        LayoutIntent.model_validate(data)
