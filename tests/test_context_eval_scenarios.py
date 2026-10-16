"""Evaluator entry point: shared mechanics oracle, separately reported role quality."""
# ruff: noqa: F811 -- shared integration fixtures

import json
import os
from pathlib import Path

import pytest

from tests.test_master import dice, game_client, llm  # noqa: F401


def _cases():
    path = os.environ.get("TALEFORGE_EVAL_CONTEXT_CASES", "tests/fixtures/context_quality.json")
    return json.loads(Path(path).read_text(encoding="utf-8"))["scenarios"]


@pytest.mark.parametrize("scenario", _cases(), ids=lambda case: case["id"])
def test_context_evaluator_scenario(request, game_client, settings, scenario):
    if os.environ.get("TALEFORGE_EVAL_EXPERIMENT") != "context":
        pytest.skip("isolated context evaluator child only")
    from tests.context_scenario_assertions import assert_scenario
    from tests.context_scenario_worlds import build_scenario, run_scenario
    from tools.context_eval_variants import context_quality
    from tools.eval_turn_efficiency import _RESULTS

    world = build_scenario(scenario["id"], game_client, settings, case=scenario)
    result = run_scenario(scenario, world, game_client, world.llm)
    row = _RESULTS[request.node.nodeid]
    row["context_quality"] = context_quality(scenario, result.prompt_packets)
    violations = any(
        not quality["called"] or quality["missing_required"] or quality["present_forbidden"]
        for quality in row["context_quality"].values()
    )
    row["context_quality_status"] = (
        "baseline_violations"
        if violations and row["effective_context_variant"] != "revised"
        else "violations"
        if violations
        else "passed"
    )
    # World, dice, action provenance and persisted outcomes use the same oracle.
    # Historical role visibility/recall is an observation, not a mechanics failure.
    mechanical_case = {**scenario, "required_facts_by_role": {}, "forbidden_facts_by_role": {}}
    # The old assemblers have no selector diagnostics; world effects and refs
    # must still pass exactly the same persisted-outcome assertions.
    assert_scenario(mechanical_case, result, check_context_diagnostics=False)
    if row["effective_context_variant"] == "revised":
        assert_scenario(scenario, result)
