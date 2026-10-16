from __future__ import annotations

from dataclasses import replace

import pytest

from tests.context_scenario_assertions import assert_scenario
from tests.context_scenario_worlds import ScenarioResult, build_scenario


@pytest.mark.parametrize("mutation", ["missing_role", "missing_fact", "leaked_fact", "wrong_role"])
def test_role_oracle_rejects_missing_or_misrouted_evidence(mutation):
    case = {
        "id": "probe",
        "requests": [],
        "expected_world": {},
        "required_facts_by_role": {"decide": ["PRIVATE_MOTIVE"], "narrate": ["PUBLIC_REACTION"]},
        "forbidden_facts_by_role": {"narrate": ["PRIVATE_MOTIVE"]},
    }
    packets = [
        {"purpose": "decide", "messages": [{"content": "PRIVATE_MOTIVE"}]},
        {"purpose": "narrate", "messages": [{"content": "PUBLIC_REACTION"}]},
    ]
    if mutation == "missing_role":
        packets.pop()
    elif mutation == "missing_fact":
        packets[0]["messages"] = [{"content": "nothing"}]
    elif mutation == "leaked_fact":
        packets[1]["messages"].append({"content": "PRIVATE_MOTIVE"})
    else:
        packets[0]["purpose"] = "parse"
    result = ScenarioResult("probe", (), (), ("real-id",), {}, (), tuple(packets))
    with pytest.raises(AssertionError):
        assert_scenario(case, result)


def test_manifest_v2_has_executable_scripts_and_role_oracles():
    from tests.test_context_quality import _manifest

    data = _manifest()
    assert data["version"] == 2
    assert len(data["scenarios"]) == 12
    for case in data["scenarios"]:
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
        } <= case.keys()
        assert all(isinstance(request, dict) and {"actor", "text"} <= request.keys() for request in case["requests"])
        roles = {"parse"} if case["id"] == "unknown_parser" else {"decide", "narrate"}
        assert set(case["required_facts_by_role"]) >= roles
        assert set(case["forbidden_facts_by_role"]) >= roles


def test_scenario_assertions_do_not_use_expected_input_as_oracle():
    case = {
        "id": "speech_npc",
        "requests": [{"actor": "hero", "text": "Поговорить"}],
        "expected_world": {"world_contains": {"messages": ["SPEECH_EVENT"]}},
        "required_facts_by_role": {},
        "forbidden_facts_by_role": {},
    }
    result = ScenarioResult(
        case_id="speech_npc",
        events=(),
        messages=("SPEECH_EVENT",),
        refs=("msg-real-1",),
        world={"messages": ("SPEECH_EVENT",)},
        requests=("Поговорить",),
        prompt_packets=(),
    )

    assert_scenario(case, result)

    corrupted = replace(result, world={"messages": ()})
    with pytest.raises(AssertionError):
        assert_scenario(case, corrupted)


def test_run_scenario_rejects_a_world_built_from_expected_outcomes():
    source = {
        "id": "speech_npc",
        "fixture": "mechanics",
        "requests": [{"actor": "hero", "text": "Поговорить"}],
        "parser_script": "speech_npc",
        "model_script": "speech_npc",
        "dice": [],
        "required_facts_by_role": {"decide": [], "narrate": []},
        "forbidden_facts_by_role": {"decide": [], "narrate": []},
        "expected_world": {},
        "rubric": [],
        "expected_outcomes": ["this must not become an input"],
    }

    with pytest.raises((AssertionError, ValueError), match="expected_outcomes|oracle|fixture"):
        build_scenario("speech_npc", None, None, case=source)
