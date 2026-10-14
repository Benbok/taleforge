"""Every base location gets a usable, populated map without a model."""

from pathlib import Path

import pytest
import yaml

from app.core.layout import geometry
from app.core.layout.contracts import Blueprint
from app.core.layout.provider import DeterministicLayoutProvider
from app.core.layout.spatial import Mandate, default_spatial, intent_candidates, obligations

RECORDS = []
for path in sorted((Path(__file__).parents[1] / "content").rglob("*.yaml")):
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and data.get("kind") == "location_template":
        RECORDS.extend(data["items"])


@pytest.mark.parametrize("record", RECORDS, ids=lambda r: r["id"])
def test_base_templates_have_populated_reachable_maps(record):
    sp = default_spatial(record["name"], record.get("tags", []), template_id=record["id"])
    assert len(sp.parts) >= 3
    mandate = Mandate(place=record["name"], spatial=sp)
    provider = DeterministicLayoutProvider()
    for seed in (1, 7, 42):
        intent = intent_candidates(mandate)[0]
        assert not obligations(intent, mandate)
        bp = provider.propose(intent, seed=seed, root_id="root")
        for area in bp.areas:
            assert len(area.details) >= 2
            geometry.build_area(bp, area)
        assert provider.propose(intent, seed=seed, root_id="root").to_json() == bp.to_json()
        restored = Blueprint.from_json(bp.to_json())
        assert restored == bp
        fallback = provider.propose(intent, seed=seed, root_id="root", fallback=True)
        for area in fallback.areas:
            assert len(area.details) >= 2
            geometry.build_area(fallback, area)
    if record["id"] in {"location.market", "location.port", "location.city_slums"}:
        assert sp.parts[0].outdoor
    if record["id"] == "location.cave":
        assert bp.areas[0].shape == "cave"
    if record["id"] == "location.ship":
        assert all(a.material == "wood" for a in bp.areas)
        assert all(not a.terrain for a in bp.areas)


def test_model_cannot_turn_outdoor_part_into_room():
    sp = default_spatial("Лес", ["wild"])
    mandate = Mandate(place="Лес", spatial=sp)
    intent = intent_candidates(mandate)[0]
    intent.parts[0].environment = "indoor"
    intent.parts[0].shape = "rect"
    assert any("окружение" in e for e in obligations(intent, mandate))


def test_detail_in_passage_is_relocated():
    from app.core.layout.intent import LayoutIntent

    intent = LayoutIntent.model_validate({
        "entry": "main", "parts": [{"part_ref": "main", "name": "Зал", "public_name": "Зал",
            "details": [{"detail_ref": "column", "name": "Колонна", "solid": True,
                         "cells": [[0, 2, 0, 2]]}]}],
        "approaches": [{"part_ref": "main", "side": "w", "public_name": "Вход"}],
    })
    bp = DeterministicLayoutProvider().propose(intent, seed=7, root_id="root")
    column = next(d for d in bp.areas[0].details if d.detail_ref == "column")
    assert column.cells != ((0, 2, 0, 2),)
    geometry.build_area(bp, bp.areas[0])


def test_optional_scenery_does_not_invalidate_a_full_authored_room():
    from app.core.layout.intent import LayoutIntent

    intent = LayoutIntent.model_validate({
        "entry": "main", "parts": [{"part_ref": "main", "name": "Зал", "public_name": "Зал",
            "details": [{"detail_ref": "tiles", "name": "Обстановка",
                         "cells": [[0, 0, 5, 2], [0, 4, 5, 5], [0, 3, 2, 3], [4, 3, 5, 3]]}]}],
    })
    bp = DeterministicLayoutProvider().propose(intent, seed=7, root_id="root")
    assert bp.areas[0].details[0].detail_ref == "tiles"
    assert bp.areas[0].details[0].cells == ((0, 0, 5, 2), (0, 4, 5, 5), (0, 3, 2, 3), (4, 3, 5, 3))
    geometry.build_area(bp, bp.areas[0])


def test_rock_between_full_width_edges_keeps_exits_reachable():
    from app.core.layout.intent import DetailIntent

    mandate = Mandate(place="Лес", spatial=default_spatial("Лес", ["wild"], template_id="location.forest"))
    intent = intent_candidates(mandate)[0]
    for part in intent.parts[1:]:
        part.side = "e"
    intent.parts[1].details.append(DetailIntent(
        detail_ref="rock", name="Валун", solid=True, cells=[[1, 1, 1, 1]],
    ))
    bp = DeterministicLayoutProvider().propose(intent, seed=7, root_id="root")
    middle = bp.areas[1]
    assert any(d.detail_ref == "rock" for d in middle.details)
    geometry.build_area(bp, middle)


def test_model_missing_details_is_populated_and_cave_shape_is_enforced():
    from app.agents import layout_model
    from app.core.world_generation.contracts import Blocked

    sp = default_spatial("Пещера", ["underground"], template_id="location.cave")
    mandate = Mandate(place="Пещера", spatial=sp)
    raw = intent_candidates(mandate)[0].model_dump(exclude={"schema_version"})
    for part in raw["parts"]:
        part["details"] = []
    intent = layout_model.to_intent(mandate, raw)
    bp = DeterministicLayoutProvider().propose(intent, seed=7, root_id="root")
    assert all(len(a.details) >= 2 for a in bp.areas)
    assert "форма — cave" in layout_model.brief(mandate)
    raw["parts"][0]["shape"] = "rect"
    with pytest.raises(Blocked, match="форма"):
        layout_model.to_intent(mandate, raw)


@pytest.mark.parametrize("template_id, outdoor", [
    ("location.whisperer_vault", False), ("location.whisperer_choirs", False),
    ("location.drowned_flooded_womb", False), ("location.old_mother_heart", False),
    ("location.hook_grey_field", True), ("location.hook_rim", True),
    ("location.city_gornilo", True),
])
def test_setting_environment_matches_public_location(template_id, outdoor):
    record = next(r for r in RECORDS if r["id"] == template_id)
    sp = default_spatial(record["name"], record.get("tags", []), template_id=template_id)
    assert all(p.outdoor == outdoor for p in sp.parts)
