import json
from pathlib import Path


def test_context_quality_manifest_has_required_scenarios():
    data = json.loads(Path("tests/fixtures/context_quality.json").read_text(encoding="utf-8"))
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
    data = json.loads(Path("tests/fixtures/context_quality.json").read_text(encoding="utf-8"))
    ids = [scenario["id"] for scenario in data["scenarios"]]
    assert len(ids) == len(set(ids))
