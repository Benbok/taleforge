"""Moderately roomier templates keep authored props at their original scale."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
CATALOG = ROOT / "experiments/location-layout-templates/templates"
BEFORE = ROOT / "experiments/location-layout-templates/quality-v3/before"
TEMPLATES = sorted(path.parent.name for path in BEFORE.glob("*/intent.json"))
ALL_TEMPLATES = sorted(path.parent.name for path in CATALOG.glob("*/intent.json"))


def read_intent(directory, template):
    return json.loads((directory / template / "intent.json").read_text(encoding="utf-8"))


def footprint(detail):
    rects = detail["cells"]
    x0, y0 = min(r[0] for r in rects), min(r[1] for r in rects)
    return [[x1 - x0, y1 - y0, x2 - x0, y2 - y0] for x1, y1, x2, y2 in rects]


@pytest.mark.parametrize("template", TEMPLATES)
def test_all_templates_gain_room_without_enlarging_furniture(template):
    previous = read_intent(BEFORE, template)
    current = read_intent(CATALOG, template)
    assert current["entry"] == previous["entry"]
    for old, new in zip(previous["parts"], current["parts"], strict=True):
        assert old["part_ref"] == new["part_ref"]
        for axis in ("cols", "rows"):
            narrow_pier = template == "port_quay_warehouse" and axis == "cols" and old[axis] == 4
            if old[axis] < 4 or narrow_pier:
                assert new[axis] == old[axis]
            else:
                assert old[axis] < new[axis] <= old[axis] * 1.25 + 0.5, (template, old["part_ref"], axis)
        for field in ("secret", "required", "anchors", "connects_to", "side", "passage_kind", "passage_state"):
            assert new[field] == old[field]
        assert len(new["details"]) >= len(old["details"])
        for detail in old["details"]:
            updated = next(d for d in new["details"] if d["detail_ref"] == detail["detail_ref"])
            assert footprint(updated) == footprint(detail), (template, detail["detail_ref"])
            assert updated["solid"] == detail["solid"]
    resource = json.loads((ROOT / "app/content/layout_templates" / f"{template}.json").read_text(encoding="utf-8"))
    assert resource["version"] == (
        "1.3.0" if template in {"tavern_roadside", "cave_passages_grotto", "port_quay_warehouse"} else "1.2.0"
    )


@pytest.mark.parametrize("template", ALL_TEMPLATES)
@pytest.mark.parametrize("seed", [1, 7, 42])
def test_roomier_templates_compile_with_reachable_exits(template, seed):
    from app.core.layout.geometry import build_area
    from app.core.layout.intent import LayoutIntent
    from app.core.layout.provider import DeterministicLayoutProvider
    from app.core.layout.validation import validate

    intent = LayoutIntent.model_validate(read_intent(CATALOG, template))
    blueprint = DeterministicLayoutProvider().propose(intent, seed=seed, root_id="test")
    assert not validate(blueprint)
    for area in blueprint.areas:
        # build_area checks connectivity of all exits after solid furniture is placed.
        build_area(blueprint, area)
        authored = next(p for p in intent.parts if p.part_ref == area.area_ref)
        assert {d.detail_ref for d in authored.details} <= {d.detail_ref for d in area.details}


def test_attached_slots_move_with_their_furniture_and_keep_bindings():
    from app.core.layout.intent import DetailIntent, LayoutIntent, ObjectSlotIntent, PartIntent

    spec = importlib.util.spec_from_file_location(
        "build_templates", ROOT / "experiments/location-layout-templates/scripts/build_templates.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    part = PartIntent(
        part_ref="store",
        name="Store",
        public_name="Store",
        cols=10,
        rows=8,
        required=True,
        anchors=["clue"],
        details=[DetailIntent(detail_ref="shelf", name="Shelf", cells=[[8, 1, 9, 1]])],
        object_slots=[
            ObjectSlotIntent(
                slot_ref="supplies", role="container", detail_ref="shelf", cells=[[8, 1, 9, 1]], max_cols=2
            )
        ],
    )
    intent = LayoutIntent(entry="store", parts=[part])
    builder.author_quality_v3({"id": "test", "version": "1.1.0"}, intent)
    assert part.cols == 12 and part.rows == 10
    assert part.details[0].cells == part.object_slots[0].cells
    assert part.details[0].cells != [[8, 1, 9, 1]]
    assert part.object_slots[0].detail_ref == "shelf"
    assert part.object_slots[0].max_cols == 2
    assert part.required and part.anchors == ["clue"]


@pytest.mark.parametrize("seed", [1, 7, 42])
def test_port_generator_keeps_an_accessible_bound_cargo_chest(seed):
    from app.core import reach
    from app.core.layout.geometry import build_area
    from app.core.layout.provider import DeterministicLayoutProvider

    spec = importlib.util.spec_from_file_location(
        "build_templates", ROOT / "experiments/location-layout-templates/scripts/build_templates.py"
    )
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    meta, intent = builder.make_port_quay_warehouse()
    builder.author_quality_v2(meta, intent)
    builder.author_quality_v3(meta, intent)
    warehouse = next(p for p in intent.parts if p.part_ref == "harbor_warehouse")
    slot = next((s for s in warehouse.object_slots if s.slot_ref == "cargo_chest"), None)
    assert slot is not None, "the authoritative generator must retain the warehouse container binding"
    assert warehouse.scene_profile == "scene_profile.warehouse"
    assert slot.role == "container"
    detail = next(d for d in warehouse.details if d.detail_ref == slot.detail_ref)
    assert not detail.solid and detail.visual_key == "feature:chest"
    assert detail.cells == slot.cells
    blueprint = DeterministicLayoutProvider().propose(intent, seed=seed, root_id="test")
    area = blueprint.area("harbor_warehouse")
    actual_slot = next(s for s in area.object_slots if s.slot_ref == "cargo_chest")
    actual_detail = next(d for d in area.details if d.detail_ref == actual_slot.detail_ref)
    assert actual_slot.cells == actual_detail.cells == tuple(tuple(r) for r in detail.cells)
    sketch = build_area(blueprint, area)
    chest = next(f for f in sketch["features"] if f["visual_key"] == "feature:chest")
    assert reach.approach_cells(sketch, chest) & reach.walk_region(sketch, tuple(sketch["party"]))
