"""Wall fixtures follow actual room walls; scene darkness is an explicit author choice."""

import pytest

from app.agents import layout_model
from app.core import reach
from app.core.layout import geometry
from app.core.layout.contracts import Blueprint, rect_cells
from app.core.layout.intent import LayoutIntent
from app.core.layout.provider import DeterministicLayoutProvider
from tests.layout_plan_pilot import temple_mandate


def plan(*, cols=12, rows=10, lighting="normal", shape="rect", details=None):
    return LayoutIntent.model_validate(
        {
            "entry": "hall",
            "parts": [
                {
                    "part_ref": "hall",
                    "name": "Hall",
                    "public_name": "Hall",
                    "cols": cols,
                    "rows": rows,
                    "shape": shape,
                    "lighting": lighting,
                    "details": details
                    if details is not None
                    else [
                        {
                            "detail_ref": "torch",
                            "name": "Wall torch",
                            "kind": "light",
                            "visual_key": "feature:torch",
                            "cells": [[cols // 2, rows // 2, cols // 2, rows // 2]],
                        },
                    ],
                }
            ],
            "approaches": [{"part_ref": "hall", "side": "w", "kind": "door", "public_name": "Entry"}],
        }
    )


def build(**kwargs):
    return DeterministicLayoutProvider().propose(plan(**kwargs), seed=7, root_id="root")


def torches(area):
    return [d for d in area.details if d.visual_key == "feature:torch" and not d.hidden]


@pytest.mark.parametrize("shape", ["rect", "l_shape", "cave"])
def test_wall_torches_follow_real_floor_boundary_and_keep_exits_free(shape):
    bp = build(shape=shape)
    area = bp.area("hall")
    floor = geometry.area_floor(bp, area)
    sources = torches(area)
    assert len(sources) >= 2
    for detail in sources:
        cells = rect_cells(detail.cells)
        assert len(cells) == 1
        assert all(
            any((c + dc, r + dr) not in floor for dc, dr in ((1, 0), (-1, 0), (0, 1), (0, -1))) for c, r in cells
        )
    sk = geometry.build_area(bp, area)
    assert reach.reach_errors(sk) == []
    assert not set().union(*(rect_cells(d.cells) for d in sources)) & {
        tuple(c) for exit_ in sk["exits"] for c in exit_["cells"]
    }


def test_larger_lit_room_gets_more_distributed_wall_lights():
    small = build(cols=7, rows=8).area("hall")
    large = build(cols=18, rows=14).area("hall")
    assert 2 <= len(torches(small)) < len(torches(large)) <= 8
    centers = [next(iter(rect_cells(d.cells))) for d in torches(large)]
    assert max(c for c, _ in centers) - min(c for c, _ in centers) >= 12
    assert max(r for _, r in centers) - min(r for _, r in centers) >= 9


def test_normal_scene_spreads_model_torches_clustered_in_the_middle():
    details = [
        {
            "detail_ref": f"torch_{c}",
            "name": "Torch",
            "kind": "light",
            "visual_key": "feature:torch",
            "cells": [[c, 5, c, 5]],
        }
        for c in (5, 6, 7)
    ]
    area = build(cols=12, rows=12, details=details).area("hall")
    cells = [next(iter(rect_cells(d.cells))) for d in torches(area)]
    assert max(c for c, _ in cells) - min(c for c, _ in cells) >= 8
    assert max(r for _, r in cells) - min(r for _, r in cells) >= 8


def test_wall_fixture_keeps_its_world_object_slot_attached():
    raw = plan(lighting="dim").model_dump()
    raw["parts"][0]["object_slots"] = [
        {"slot_ref": "sconce", "role": "prop", "detail_ref": "torch", "cells": [[6, 5, 6, 5]]}
    ]
    bp = DeterministicLayoutProvider().propose(LayoutIntent.model_validate(raw), seed=7, root_id="root")
    area = bp.area("hall")
    assert area.object_slots[0].cells == torches(area)[0].cells
    assert area.object_slots[0].cells != ((6, 5, 6, 5),)
    assert reach.reach_errors(geometry.build_area(bp, area)) == []


@pytest.mark.parametrize("slot_only", [False, True])
def test_mounting_does_not_cut_off_an_authored_object_in_a_narrow_pocket(slot_only):
    details = [
        {"detail_ref": "wall", "name": "Wall", "solid": True, "cells": [[1, 1, 5, 1]]},
        {"detail_ref": "box", "name": "Box", "cells": [[3, 0, 3, 0]]},
        {
            "detail_ref": "torch",
            "name": "Torch",
            "kind": "light",
            "visual_key": "feature:torch",
            "cells": [[1, 2, 1, 2]],
        },
    ]
    raw = plan(cols=6, rows=6, lighting="dim", details=details).model_dump()
    if slot_only:
        raw["parts"][0]["details"] = [d for d in raw["parts"][0]["details"] if d["detail_ref"] != "box"]
        raw["parts"][0]["object_slots"] = [{"slot_ref": "box", "role": "container", "cells": [[3, 0, 3, 0]]}]
    bp = DeterministicLayoutProvider().propose(LayoutIntent.model_validate(raw), seed=7, root_id="root")
    sk = geometry.build_area(bp, bp.area("hall"))
    box = {"cells": [[3, 0, 3, 0]]} if slot_only else next(f for f in sk["features"] if f["name"] == "Box")
    assert reach.approach_cells(sk, box) & reach.walk_region(sk, tuple(sk["party"]))


def test_hybrid_template_retains_authored_dim_lighting():
    from app.core.layout.spatial import Mandate, default_spatial
    from app.core.layout.template_catalog import load_catalog
    from app.core.layout.template_selection import adapt_template_hybrid

    template = next(t for t in load_catalog() if t.id == "port_quay_warehouse").model_copy(deep=True)
    next(p for p in template.intent.parts if p.role == "warehouse").lighting = "dim"
    mandate = Mandate(place="Port", spatial=default_spatial("Port", template_id="location.port"))
    intent, _ = adapt_template_hybrid(template, mandate)
    assert next(p for p in intent.parts if p.role == "warehouse").lighting == "dim"


@pytest.mark.parametrize("lighting", ["dim", "dark"])
def test_story_lighting_survives_model_fallback_and_cannot_be_overridden(lighting):
    from app.core.layout.spatial import Mandate, SpatialPlan, intent_candidates, obligations

    mandate = Mandate(
        place="Hall",
        spatial=SpatialPlan.model_validate(
            {
                "environment": "indoor",
                "parts": [{"ref": "hall", "name": "Hall", "lighting": lighting}],
                "approaches": [{"name": "Entry", "kind": "door"}],
            }
        ),
    )
    intent = intent_candidates(mandate)[0]
    assert intent.parts[0].lighting == lighting
    assert f"lighting={lighting}" in layout_model.brief(mandate)
    intent.parts[0].lighting = "normal"
    assert any("освещение" in error for error in obligations(intent, mandate))


@pytest.mark.parametrize("lighting", ["dim", "dark"])
def test_intentional_darkness_does_not_gain_extra_sources(lighting):
    bp = build(lighting=lighting)
    area = bp.area("hall")
    assert len(torches(area)) == 1
    assert not any(d.visual_key in {"feature:hearth", "feature:glow"} for d in area.details)
    assert area.lighting == lighting
    assert Blueprint.from_json(bp.to_json()).area("hall").lighting == lighting


def test_dark_empty_room_and_hidden_torch_never_trigger_extra_lights():
    bp = build(lighting="dark", details=[])
    assert not any(d.visual_key in {"feature:torch", "feature:hearth", "feature:glow"} for d in bp.area("hall").details)
    hidden = [
        {
            "detail_ref": "secret",
            "name": "Secret",
            "kind": "light",
            "hidden": True,
            "visual_key": "feature:torch",
            "cells": [[5, 5, 5, 5]],
        }
    ]
    bp = build(details=hidden, lighting="dim")
    assert torches(bp.area("hall")) == []
    assert next(d for d in bp.area("hall").details if d.detail_ref == "secret").cells == ((5, 5, 5, 5),)


def test_hearth_stays_on_floor_and_outdoor_torch_is_not_mounted_on_imaginary_wall():
    hearth = [{"detail_ref": "fire", "name": "Hearth", "visual_key": "feature:hearth", "cells": [[4, 4, 5, 4]]}]
    bp = build(details=hearth)
    assert next(d for d in bp.area("hall").details if d.detail_ref == "fire").cells == ((4, 4, 5, 4),)
    raw = plan().model_dump()
    raw["parts"][0].update(environment="outdoor", shape="open")
    outdoor = (
        DeterministicLayoutProvider().propose(LayoutIntent.model_validate(raw), seed=7, root_id="root").area("hall")
    )
    assert next(d for d in outdoor.details if d.detail_ref == "torch").cells == ((6, 5, 6, 5),)


def test_legacy_blueprint_defaults_to_normal_lighting_and_schema_accepts_dark_policy():
    raw = build(lighting="dim").to_json()
    raw["areas"][0].pop("lighting", None)
    assert Blueprint.from_json(raw).area("hall").lighting == "normal"
    properties = layout_model.spec(temple_mandate())["function"]["parameters"]["properties"]["parts"]["items"][
        "properties"
    ]
    assert set(properties["lighting"]["enum"]) == {"normal", "dim", "dark"}


def test_saved_blueprint_rejects_unknown_lighting_policy():
    from app.core.layout.validation import validate

    raw = build().to_json()
    raw["areas"][0]["lighting"] = "unknown"
    assert any("освещения" in error for error in validate(Blueprint.from_json(raw)))
