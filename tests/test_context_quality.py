# ruff: noqa: F811

import json
from pathlib import Path

import pytest

from tests.context_scenarios import execute_context_scenario
from tests.test_tools import game, play  # noqa: F401


def _manifest():
    return json.loads(Path("tests/fixtures/context_quality.json").read_text(encoding="utf-8"))

def test_context_quality_manifest_has_required_scenarios():
    data = _manifest()
    assert data["version"] == 1
    assert len(data["scenarios"]) == 12
    for scenario in data["scenarios"]:
        assert {
            "id",
            "requests",
            "required_facts",
            "forbidden_facts",
            "expected_outcomes",
            "rubric",
        } <= scenario.keys()


def test_context_quality_manifest_has_no_duplicate_ids():
    data = _manifest()
    ids = [scenario["id"] for scenario in data["scenarios"]]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("scenario", _manifest()["scenarios"], ids=lambda item: item["id"])
def test_context_quality_scenario_exercises_production_assembly(game, scenario):
    settings, cid, _hero = game

    async def check(ctx):
        report = await execute_context_scenario(ctx, scenario)
        assert report["id"] == scenario["id"]
        assert report["baseline_assembly_path"] == "legacy"
        assert report["revised_estimated_tokens"] > 0 and report["baseline_estimated_tokens"] > 0

    play(settings, cid, [], check)
