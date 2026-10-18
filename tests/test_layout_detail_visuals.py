"""Decorative identity survives layout persistence without changing map mechanics."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from app.core import reach, sketch
from app.core.layout.contracts import Blueprint
from app.core.layout.geometry import build_area
from app.core.layout.intent import DetailIntent, LayoutIntent
from app.core.layout.provider import DeterministicLayoutProvider


def _blueprint(visual_key: str | None = None) -> Blueprint:
    details = [
        {"detail_ref": "pillar", "name": "Pillar", "kind": "cover", "cells": [[2, 2, 2, 2]], "solid": True},
        {"detail_ref": "secret", "name": "Secret marker", "cells": [[4, 2, 4, 2]], "hidden": True},
    ]
    if visual_key is not None:
        for detail in details:
            detail["visual_key"] = visual_key
    intent = LayoutIntent.model_validate(
        {
            "entry": "hall",
            "parts": [
                {"part_ref": "hall", "name": "Hall", "public_name": "Hall", "cols": 7, "rows": 6, "details": details}
            ],
            "approaches": [{"part_ref": "hall", "side": "w", "public_name": "Entrance"}],
        }
    )
    return DeterministicLayoutProvider().propose(intent, seed=7, root_id="root")


def test_detail_visual_identity_survives_persistence_and_viewer_privacy():
    bp = _blueprint("stone_pillar")
    persisted = bp.to_json()
    assert [detail["visual_key"] for detail in persisted["areas"][0]["details"]] == [
        "stone_pillar",
        "stone_pillar",
    ]
    restored = Blueprint.from_json(persisted)
    assert restored.to_json() == persisted
    sk = build_area(restored, restored.area("hall"))
    player = sketch.for_viewer(sk, master=False, visible_places=set())
    master = sketch.for_viewer(sk, master=True, visible_places=set())
    assert [(f["name"], f["visual_key"]) for f in player["features"]] == [("Pillar", "stone_pillar")]
    assert [(f["name"], f["visual_key"]) for f in master["features"]] == [
        ("Pillar", "stone_pillar"),
        ("Secret marker", "stone_pillar"),
    ]
    assert "Secret marker" not in str(player)
    assert player["exits"][0]["to"] is None


@pytest.mark.parametrize("visual_key", [None, ""])
def test_legacy_or_empty_detail_visual_key_does_not_add_sketch_metadata(visual_key):
    persisted = _blueprint(visual_key).to_json()
    if visual_key is None:
        for detail in persisted["areas"][0]["details"]:
            detail.pop("visual_key", None)
    restored = Blueprint.from_json(persisted)
    sk = build_area(restored, restored.area("hall"))
    assert all("visual_key" not in feature for feature in sk["features"])
    assert sk["walls"] == [[2, 2]]


def test_unknown_detail_visual_key_is_inert_metadata():
    plain = _blueprint()
    decorated = Blueprint.from_json(_blueprint("future_unregistered_art").to_json())
    plain_sk = build_area(plain, plain.area("hall"))
    decorated_sk = build_area(decorated, decorated.area("hall"))
    assert decorated_sk["features"][0]["visual_key"] == "future_unregistered_art"
    assert reach.blocked_cells(decorated_sk) == reach.blocked_cells(plain_sk)
    assert reach.walk_region(decorated_sk, tuple(decorated_sk["party"])) == reach.walk_region(
        plain_sk,
        tuple(plain_sk["party"]),
    )
    without_visuals = deepcopy(decorated_sk)
    for feature in without_visuals["features"]:
        feature.pop("visual_key", None)
    assert without_visuals == plain_sk


def test_detail_visual_key_length_is_bounded_at_input():
    with pytest.raises(ValidationError):
        DetailIntent(detail_ref="pillar", name="Pillar", cells=[[1, 1, 1, 1]], visual_key="x" * 65)
