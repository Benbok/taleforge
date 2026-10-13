"""Tests for narrative creative quality rubrics and structural review (Task 21)."""

from __future__ import annotations

from app.core.narrative.quality import load_quality_case, load_quality_cases, score_structural_quality


def test_valid_continuation_can_still_require_quality_review():
    case = load_quality_case("rejected_main_hook")
    report = score_structural_quality(case, case.reference_bad)
    assert report.requires_human_review
    assert "player_refusal_reused_as_mandatory_goal" in report.rubric_observations


def test_all_reference_good_cases_pass_structural_evaluation():
    cases = load_quality_cases()
    assert len(cases) == 8
    for case in cases:
        report = score_structural_quality(case, case.reference_good)
        assert report.structural_pass, f"Case {case.id} good reference failed: {report.rubric_observations}"
        assert not report.requires_human_review
        assert len(report.rubric_observations) == 0


def test_all_reference_bad_cases_trigger_review_observations():
    cases = load_quality_cases()
    assert len(cases) == 8
    for case in cases:
        report = score_structural_quality(case, case.reference_bad)
        assert not report.structural_pass, f"Case {case.id} bad reference unexpectedly passed"
        assert report.requires_human_review
        assert len(report.rubric_observations) > 0


def test_mistaken_guess_does_not_mutate_objective_truth():
    case = load_quality_case("mistaken_guess")
    bad_report = score_structural_quality(case, case.reference_bad)
    assert "false_rumor_promoted_to_truth" in bad_report.rubric_observations

    good_report = score_structural_quality(case, case.reference_good)
    assert good_report.structural_pass


def test_quiet_scene_does_not_mandate_violent_complication():
    case = load_quality_case("quiet_scene")
    bad_report = score_structural_quality(case, case.reference_bad)
    assert "forced_complication_in_quiet_scene" in bad_report.rubric_observations

    good_report = score_structural_quality(case, case.reference_good)
    assert good_report.structural_pass


def test_live_quality_eval_reports_unavailable_model_as_skipped(capsys):
    from pathlib import Path

    from tools.eval_narrative import run_evaluation

    report = run_evaluation(Path("tests/fixtures/narrative_quality.json"), "live")

    assert report["passed"] == 0
    assert report["failed"] == 0
    assert report["skipped"] == len(load_quality_cases())
    assert all(result["status"] == "skipped_no_model" for result in report["results"])
    output = capsys.readouterr().out
    assert "Summary: 0/8 passed, 0 failed, 8 skipped" in output
    assert "[PASS]" not in output
    assert "api_key" not in repr(report).lower()
    assert "password" not in repr(report).lower()
