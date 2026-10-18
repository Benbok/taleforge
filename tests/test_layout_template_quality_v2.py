"""Authored prop scale, circulation and semantic artwork contracts."""

import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
CATALOG = ROOT / "experiments/location-layout-templates/templates"


def parts(template):
    data = json.loads((CATALOG / template / "intent.json").read_text(encoding="utf-8"))
    return {part["part_ref"]: part for part in data["parts"]}


def cells(detail):
    return {(x, y) for x1, y1, x2, y2 in detail["cells"] for x in range(x1, x2 + 1) for y in range(y1, y2 + 1)}


@pytest.mark.parametrize("path", sorted(CATALOG.glob("*/intent.json")), ids=lambda p: p.parent.name)
def test_authored_details_have_explicit_artwork(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    for part in data["parts"]:
        for detail in part["details"]:
            assert detail.get("visual_key", "").startswith("feature:"), detail["detail_ref"]


def test_tavern_has_paired_seating_and_a_wide_central_route():
    hall = parts("tavern_roadside")["common_room"]
    assert hall["cols"] >= 14 and hall["rows"] >= 12
    details = {d["detail_ref"]: d for d in hall["details"]}
    for suffix in ("north", "south"):
        table = cells(details[f"table_{suffix}"])
        benches = cells(details[f"benches_{suffix}"])
        assert len(table) >= 2
        assert len(benches) >= 4
        assert all(min(abs(x - a) + abs(y - b) for a, b in table) == 1 for x, y in benches)
    blocked = set().union(*(cells(d) for d in hall["details"] if d["solid"]))
    assert any(
        all((x, y) not in blocked for x in (col, col + 1) for y in range(1, hall["rows"]))
        for col in range(2, hall["cols"] - 2)
    )
    beds = [d for d in parts("tavern_roadside")["guest_rooms"]["details"] if "bunks" in d["detail_ref"]]
    assert all(d["solid"] and len(cells(d)) == 2 for d in beds)


def test_grotto_has_separated_rock_clusters_with_room_to_circle():
    grotto = parts("cave_passages_grotto")["great_grotto"]
    assert grotto["cols"] >= 17 and grotto["rows"] >= 14
    rocks = [d for d in grotto["details"] if d["solid"]]
    assert len(rocks) >= 3
    for detail in rocks:
        cluster = cells(detail)
        assert 1 <= len(cluster) <= 4
        assert all(1 < x < grotto["cols"] - 2 and 1 < y < grotto["rows"] - 2 for x, y in cluster)
        assert all(
            min(abs(x - a) + abs(y - b) for a, b in cells(other)) >= 3
            for x, y in cluster
            for other in rocks
            if other is not detail
        )


def test_cargo_pier_is_narrow_and_has_an_unobstructed_working_lane():
    port = parts("port_quay_warehouse")
    pier = port["cargo_pier"]
    assert 3 <= pier["cols"] <= 4
    assert pier["rows"] >= 12
    assert pier["material"] == "wood"
    blocked = set().union(*(cells(d) for d in pier["details"] if d["solid"]))
    assert any(all((x, y) not in blocked for y in range(pier["rows"])) for x in range(pier["cols"]))
    east_water = port["harbor_water_east"]
    assert east_water["connects_to"] == "cargo_pier" and east_water["side"] == "e"
    racks = next(d for d in port["harbor_warehouse"]["details"] if d["detail_ref"] == "storage_racks")
    assert racks["solid"] and len(racks["cells"]) >= 2


@pytest.mark.parametrize("path", sorted(CATALOG.glob("*/intent.json")), ids=lambda p: p.parent.name)
def test_production_intents_match_reviewed_catalog(path):
    resource = json.loads(
        (ROOT / "app/content/layout_templates" / (path.parent.name + ".json")).read_text(encoding="utf-8")
    )
    assert resource["intent"] == json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("template", ["tavern_roadside", "cave_passages_grotto", "port_quay_warehouse"])
@pytest.mark.parametrize("seed", [1, 7, 42, 99, 123])
def test_reviewed_prop_clusters_survive_actual_geometry(template, seed):
    from app.core.layout.geometry import build_area
    from app.core.layout.intent import LayoutIntent
    from app.core.layout.provider import DeterministicLayoutProvider

    intent = LayoutIntent.model_validate_json((CATALOG / template / "intent.json").read_text(encoding="utf-8"))
    blueprint = DeterministicLayoutProvider().propose(intent, seed=seed, root_id="tpl_" + template)
    for part in intent.parts:
        area = next(area for area in blueprint.areas if area.area_ref == part.part_ref)
        sketch = build_area(blueprint, area)
        # A shifted table or bench would break its authored seating cluster;
        # moving any island could remove the deliberately open path around it.
        for detail in part.details:
            actual = next(d for d in area.details if d.detail_ref == detail.detail_ref)
            assert [list(rect) for rect in actual.cells] == detail.cells
            feature = next(
                f for f in sketch["features"] if f["id"] == ("sf_" + part.part_ref + "_" + detail.detail_ref)[:32]
            )
            assert feature["visual_key"] == detail.visual_key


@pytest.mark.parametrize(
    "template,detail_ref,visual_key",
    [
        ("cave_passages_grotto", "glowing_lichen", "feature:lichen"),
        ("cave_passages_grotto", "shimmering_pool", "feature:glow"),
        ("cave_passages_grotto", "beast_bedding", "feature:nest"),
        ("cave_multilevel_grottos", "luminescent_spores", "feature:lichen"),
        ("cave_multilevel_grottos", "dry_nest", "feature:nest"),
        ("cave_multilevel_grottos", "torch_bracket", "feature:torch"),
        ("tavern_roadside", "bunks_north", "feature:bed"),
        ("forest_stream_crossing", "reeds_bed", "feature:reeds"),
    ],
)
def test_natural_lights_and_animal_bedding_use_matching_art(template, detail_ref, visual_key):
    detail = next(
        detail for part in parts(template).values() for detail in part["details"] if detail["detail_ref"] == detail_ref
    )
    assert detail["visual_key"] == visual_key
