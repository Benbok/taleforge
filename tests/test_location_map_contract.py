import pytest
from pydantic import ValidationError

from app.gateway.protocol import (
    MapKnownArea,
    MapLocationPlan,
    MapSketchEdge,
    MapSketchTerrain,
    MapTraverseResult,
)


def test_location_plan_contract_accepts_offsets_and_memory():
    plan = MapLocationPlan.model_validate(
        {
            "root_id": "complex-1",
            "here_id": "area-2",
            "areas": [
                {
                    "id": "area-2",
                    "name": "Внутренний двор",
                    "offset": [-6, -4],
                    "level": -1,
                    "status": "remembered",
                    "revision": 2,
                    "observed_at": None,
                    "sketch": {
                        "shape": "room",
                        "cols": 3,
                        "rows": 3,
                        "party": [1, 1],
                        "walls": [],
                        "exits": [],
                        "features": [],
                    },
                    "disclosed_to": [],
                }
            ],
        }
    )
    assert plan.areas[0].offset == (-6, -4)
    assert MapLocationPlan.model_validate(plan.model_dump(exclude_none=True)) == plan


@pytest.mark.parametrize(
    ("model", "payload"),
    [
        (MapSketchEdge, {"side": "n", "start": 0, "length": 1, "meaning": "fog"}),
        (MapSketchTerrain, {"kind": "lava", "cells": [[0, 0]]}),
        (MapSketchEdge, {"side": "up", "start": 0, "length": 1, "meaning": "wall"}),
    ],
)
def test_typed_map_fields_reject_invalid_values(model, payload):
    with pytest.raises(ValidationError):
        model.model_validate(payload)


def test_traverse_result_models_failed_finish():
    result = MapTraverseResult.model_validate(
        {"request_id": "t1", "ok": True, "moved": False, "reason": "дверь закрыта"}
    )
    assert result.moved is False and result.reason == "дверь закрыта"
