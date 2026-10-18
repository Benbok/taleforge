"""New automatic plans leave room for furnishing without resizing authored geometry."""

import pytest

from app.core.layout import geometry
from app.core.layout.intent import LayoutIntent
from app.core.layout.provider import DeterministicLayoutProvider


@pytest.mark.parametrize(
    ("environment", "size", "dimensions"),
    [("indoor", "medium", (7, 8)), ("indoor", "large", (10, 12)), ("outdoor", "medium", (14, 12))],
)
def test_automatic_rooms_have_space_for_groups_and_aisles(environment, size, dimensions):
    intent = LayoutIntent.model_validate(
        {
            "entry": "main",
            "parts": [
                {"part_ref": "main", "name": "Место", "public_name": "Место", "environment": environment, "size": size}
            ],
        }
    )
    bp = DeterministicLayoutProvider().propose(intent, seed=7, root_id="root")
    area = bp.areas[0]
    assert (area.cols, area.rows) == dimensions
    geometry.build_area(bp, area)


def test_explicit_dimensions_and_narrow_corridors_are_preserved():
    for extra, expected in [({"cols": 6, "rows": 5}, (6, 5)), ({"shape": "corridor"}, (2, 8))]:
        intent = LayoutIntent.model_validate(
            {
                "entry": "main",
                "parts": [{"part_ref": "main", "name": "Место", "public_name": "Место", **extra}],
            }
        )
        area = DeterministicLayoutProvider().propose(intent, seed=7, root_id="root").areas[0]
        assert (area.cols, area.rows) == expected


@pytest.mark.parametrize("scale", ["small", "medium", "large"])
def test_default_road_tracks_the_center_of_the_larger_outdoor_area(scale):
    from app.core.layout.spatial import Mandate, SpatialPlan, intent_candidates

    mandate = Mandate(
        place="Road",
        spatial=SpatialPlan.model_validate(
            {
                "environment": "outdoor",
                "scale": scale,
                "parts": [{"ref": "entry", "name": "Road", "outdoor": True}],
                "approaches": [{"name": "West road", "kind": "road"}],
            }
        ),
    )
    intent = intent_candidates(mandate)[0]
    area = DeterministicLayoutProvider().propose(intent, seed=7, root_id="root").areas[0]
    assert intent.bands[0].at == area.rows // 2 - 1
