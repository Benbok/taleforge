from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def test_context_experiment_config_accepts_only_declared_variants():
    from tools.context_eval_variants import ExperimentConfig

    assert ExperimentConfig(kind="context", variants=("legacy", "v1", "revised")).variants == (
        "legacy",
        "v1",
        "revised",
    )
    with pytest.raises(ValueError, match="variant"):
        ExperimentConfig(kind="context", variants=("optimized",))


def test_context_variants_change_the_captured_assembler_package():
    from tools.context_eval_variants import package_for_variant

    source = {
        "messages": [{"role": "system", "content": "rules"}, {"role": "user", "content": "request"}],
        "tools": [{"function": {"name": "resolve_attack"}}],
    }
    legacy = package_for_variant("legacy", source)
    v1 = package_for_variant("v1", source)
    revised = package_for_variant("revised", source)

    assert len({legacy["digest"], v1["digest"], revised["digest"]}) == 3
    assert legacy["variant"] == "legacy" and revised["messages"] == source["messages"]


def test_context_run_scripted_passes_effective_variant_to_child_and_reports_it(tmp_path):
    from tools import eval_turn_efficiency as runner
    from tools.context_eval_variants import ExperimentConfig

    case = {
        "id": "probe",
        "nodeid": "tests/test_turn_efficiency.py::test_paired_scripted_turn[attack]",
        "tags": ["mechanics"],
        "scope": "full_turn",
    }

    def execute(command, **options):
        env = options["env"]
        assert env["TALEFORGE_EVAL_EXPERIMENT"] == "context"
        variant = env["TALEFORGE_EVAL_CONTEXT_VARIANT"]
        Path(env["TALEFORGE_EVAL_RESULT"]).write_text(
            json.dumps(
                [
                    {
                        "nodeid": case["nodeid"],
                        "status": "passed",
                        "model_calls": {},
                        "fallback": 0,
                        "unknown_usage": 0,
                        "snapshot": {},
                        "effective_context_variant": variant,
                        "context_package_digest": f"digest:{variant}",
                    }
                ]
            ),
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    report = runner.run_scripted(
        [case],
        execute=execute,
        experiment=ExperimentConfig(kind="context", variants=("legacy", "revised")),
    )

    assert set(report["variants"]) == {"legacy", "revised"}
    assert report["variants"]["legacy"]["cases"][0]["effective_context_variant"] == "legacy"
    assert report["variants"]["revised"]["cases"][0]["context_package_digest"] == "digest:revised"


def test_context_run_scripted_records_child_crash_as_failed_variant(tmp_path):
    from tools import eval_turn_efficiency as runner
    from tools.context_eval_variants import ExperimentConfig

    case = {
        "id": "probe",
        "nodeid": "tests/test_turn_efficiency.py::test_paired_scripted_turn[attack]",
        "tags": ["mechanics"],
        "scope": "full_turn",
    }

    def execute(command, **options):
        return SimpleNamespace(returncode=7, stdout="child failed", stderr="trace")

    report = runner.run_scripted(
        [case], execute=execute, experiment=ExperimentConfig(kind="context", variants=("revised",))
    )

    variant = report["variants"]["revised"]
    assert variant["exit_code"] == 7
    assert variant["summary"]["failed"] == 1
    assert variant["cases"][0]["failure_phase"] == "collection"

