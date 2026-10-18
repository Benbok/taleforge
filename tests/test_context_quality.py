# ruff: noqa: F811

import json
from copy import deepcopy
from dataclasses import replace
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
    original_complete = world.llm.complete
    original_ask = game_client.app.state.master._ask
    original_dice = game_client.app.state.master.dice_factory
    result = run_scenario(scenario, world, game_client, world.llm)
    assert world.llm.complete == original_complete
    assert game_client.app.state.master._ask == original_ask
    assert game_client.app.state.master.dice_factory == original_dice
    assert_scenario(scenario, result)
    assert result.refs
    assert result.turns or result.rejections
    # Removing the intended persisted action must invalidate each family's oracle.
    broken_world = deepcopy(result.world)
    if scenario["id"] == "speech_npc":
        broken_world["message_rows"] = []
    elif scenario["id"] == "unknown_parser":
        broken_world["message_rows"] = []
        with pytest.raises(AssertionError):
            assert_scenario(scenario, replace(result, world=broken_world))
        return
    else:
        baseline_ids = {event["id"] for event in result.world["baseline"]["events"]}
        corrupted = replace(result, events=tuple(e for e in result.events if e["id"] in baseline_ids))
        with pytest.raises(AssertionError):
            assert_scenario(scenario, corrupted)
        return
    with pytest.raises(AssertionError):
        assert_scenario(scenario, replace(result, world=broken_world))


@pytest.mark.parametrize("failure", ["empty", "error", "timeout"])
@pytest.mark.parametrize("recover_success", [False, True])
def test_unknown_parser_recovery_variants(game_client, settings, failure, recover_success):
    case = deepcopy(next(c for c in _manifest()["scenarios"] if c["id"] == "unknown_parser"))
    if recover_success:
        case["dice"] = [19]
        case["required_facts_by_role"].update(decide=["request"], narrate=[])
        case["expected_world"] = {"min_turns": 1, "rejections": 0, "min_messages": 2}
    world = build_scenario(case["id"], game_client, settings, case=case)
    world.observations.update(parser_failure=failure, recover_success=recover_success)
    result = run_scenario(case, world, game_client, world.llm)
    assert_scenario(case, result)
    # При сохранении исходной заявки в нейтральном fallback повторная попытка парсинга не нужна.
    assert sum(p["purpose"] == "parse" for p in result.prompt_packets) == 1
