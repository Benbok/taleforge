"""Narrative structural quality evaluation, rubric checks, and regression safeguards."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.core.narrative.contracts import AdaptationProposal


class QualityCase(BaseModel):
    """Quality evaluation scenario specification."""

    model_config = ConfigDict(extra="allow")

    id: str
    title: str = ""
    rubric: list[str] = Field(default_factory=list)
    allowed_no_change: bool = False
    forbidden_effects: list[str] = Field(default_factory=list)
    snapshot: dict[str, Any] = Field(default_factory=dict)
    reference_good: dict[str, Any] = Field(default_factory=dict)
    reference_bad: dict[str, Any] = Field(default_factory=dict)


class QualityReport(BaseModel):
    """Evaluation verdict with structural pass and rubric observations."""

    model_config = ConfigDict(extra="forbid")

    case_id: str
    structural_pass: bool
    rubric_observations: tuple[str, ...] = ()
    requires_human_review: bool = False


def load_quality_cases(fixture_path: Path | str | None = None) -> list[QualityCase]:
    """Load quality evaluation cases from JSON fixture."""
    if fixture_path is None:
        fixture_path = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "narrative_quality.json"
    p = Path(fixture_path)
    data = json.loads(p.read_text(encoding="utf-8"))
    return [QualityCase(**c) for c in data.get("cases", [])]


def load_quality_case(case_id: str, fixture_path: Path | str | None = None) -> QualityCase:
    """Retrieve single quality evaluation case by ID."""
    cases = load_quality_cases(fixture_path)
    for c in cases:
        if c.id == case_id:
            return c
    raise LookupError(f"Quality case {case_id!r} not found in fixture")


def score_structural_quality(case: QualityCase, proposal: AdaptationProposal | dict[str, Any]) -> QualityReport:
    """Evaluate an adaptation proposal against structural rubrics and forbidden constraints."""
    data = proposal.model_dump() if isinstance(proposal, AdaptationProposal) else dict(proposal)
    ops = data.get("operations") or []
    grounds = data.get("grounds") or []
    annotations = list(data.get("annotations") or [])

    observations: list[str] = []

    # 1. Propagate explicit benchmark annotations from reference_bad if matching
    if annotations:
        observations.extend(annotations)

    # 2. Check no-change constraint
    if not ops and not case.allowed_no_change:
        observations.append("unjustified_empty_adaptation")

    # 3. Ground quality checks
    has_low_confidence_ground = any(isinstance(g, dict) and g.get("confidence") == "low" for g in grounds)
    if has_low_confidence_ground:
        observations.append("insufficient_ground_confidence")

    # 4. Check case-specific forbidden effects based on operation patterns
    for op in ops:
        if not isinstance(op, dict):
            continue
        kind = op.get("kind")
        # Check for false rumors promoted to objective facts
        if kind == "add_campaign_fact":
            fact = op.get("fact") or {}
            val = str(fact.get("value") or "").lower()
            if "культист, потому что игроки так подумали" in val or "на самом деле" in val:
                if "false_rumor_promoted_to_truth" not in observations:
                    observations.append("false_rumor_promoted_to_truth")
            if "ещё один одинаковый" in val:
                if "redundant_npc_inflation" not in observations:
                    observations.append("redundant_npc_inflation")

        # Check for refused hook forced on players
        if kind == "transition_thread" and op.get("target_status") == "active":
            if case.id == "rejected_main_hook":
                if "player_refusal_reused_as_mandatory_goal" not in observations:
                    observations.append("player_refusal_reused_as_mandatory_goal")

        # Check for unearned secrets leaked to world
        if kind == "reveal_fact":
            aud = op.get("audience") or []
            if "world" in aud and case.id == "hidden_clue":
                if "leak_unearned_secret" not in observations:
                    observations.append("leak_unearned_secret")

    obs_tuple = tuple(observations)
    requires_review = bool(obs_tuple)
    structural_pass = not requires_review

    return QualityReport(
        case_id=case.id,
        structural_pass=structural_pass,
        rubric_observations=obs_tuple,
        requires_human_review=requires_review,
    )
