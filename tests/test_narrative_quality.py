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
