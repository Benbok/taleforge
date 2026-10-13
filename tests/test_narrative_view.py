"""Tests for unified narrative view (Task 4)."""

from app.core.narrative.contracts import (
    FactRef,
    FactState,
    SnapshotRef,
)
from app.core.narrative.view import compose_view
from tests.narrative_helpers import fact


def goal_ref() -> FactRef:
    return FactRef(
        campaign_id="camp-1",
        namespace="plan",
        subject_id="villain",
        key="motivation",
        version=1,
        snapshot_ref=SnapshotRef(kind="plan", source_id="villain", typed_address="plan:antagonists:villain:goal"),
    )


def plan_with_goal(goal: str) -> dict:
    return {
        "antagonists": [
            {
                "id": "villain",
                "goal": goal,
                "name": "Ирса",
            }
        ],
        "acts": [
            {
                "id": "act1",
                "goal": goal,
                "nodes": [],
            }
        ],
    }


def plan_fact_metadata() -> tuple[FactState, ...]:
    return (
        fact(
            ref=goal_ref(),
            value="старая_цель",
            freedom="draft",
        ),
    )


def test_plan_value_is_read_from_plan_not_stale_metadata():
    view = compose_view(plan_with_goal("перемирие"), plan_fact_metadata(), ())
    assert view.resolve(goal_ref()).value == "перемирие"


def test_campaign_fact_value_is_read_from_facts():
    camp_fact_ref = FactRef(
        campaign_id="camp-1",
        namespace="campaign",
        subject_id="npc-1",
        key="motivation",
        version=1,
        snapshot_ref=SnapshotRef(kind="event", source_id="e1", typed_address="c:1"),
    )
    f = fact(ref=camp_fact_ref, value="помочь героям", freedom="draft")
    view = compose_view(plan_with_goal("мир"), (f,), ())
    assert view.resolve(camp_fact_ref).value == "помочь героям"


def test_view_permitted_subjects():
    view = compose_view(plan_with_goal("перемирие"), plan_fact_metadata(), ())
    subjects = view.permitted_subjects()
    assert "villain" in subjects
    assert "act1" in subjects
