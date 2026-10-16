# ruff: noqa: F811

import json
from pathlib import Path

import pytest

from tests.context_scenario_assertions import assert_scenario
from tests.context_scenario_worlds import build_scenario, run_scenario
from tests.test_master import dice, game_client, llm  # noqa: F401


def _manifest():
    return json.loads(Path("tests/fixtures/context_quality.json").read_text(encoding="utf-8"))

def test_context_quality_manifest_has_required_scenarios():
    data = _manifest()
    assert data["version"] == 2
    assert len(data["scenarios"]) == 12
    for scenario in data["scenarios"]:
        assert {
            "id",
            "fixture",
            "requests",
            "parser_script",
            "model_script",
            "dice",
            "required_facts_by_role",
            "forbidden_facts_by_role",
            "expected_world",
            "rubric",
        } <= scenario.keys()


def test_context_quality_manifest_has_no_duplicate_ids():
    data = _manifest()
    ids = [scenario["id"] for scenario in data["scenarios"]]
    assert len(ids) == len(set(ids))


@pytest.mark.parametrize("scenario", _manifest()["scenarios"], ids=lambda item: item["id"])
def test_context_quality_scenario_executes_complete_game_turn(game_client, settings, scenario):
    world = build_scenario(scenario["id"], game_client, settings, case=scenario)
    result = run_scenario(scenario, world, game_client, world.llm)
    assert_scenario(scenario, result)
    assert result.refs
    assert result.turns or result.rejections
