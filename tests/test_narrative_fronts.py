"""Tests for campaign fronts, clock thresholds, and dramatic questions (Task 19)."""

import copy

import pytest

from app.core import plot
from app.core.narrative.contracts import (
    FactRef,
    FrontRef,
    FrontView,
    Ground,
)
from app.core.narrative.fronts import (
    advance_front,
    iter_fronts,
    tick_fronts,
)


def hourly_plan() -> dict:
    return {
        "campaign_id": "c1",
        "clock_at": 0,
        "fronts": [{"id": "watch", "period": 3600, "clock_at": 0, "progress": 0, "maximum": 6}],
    }


def test_explicit_front_ticks_on_its_own_clock_without_duplicates():
    original = hourly_plan()
    plan = original
    for now, expected in ((3599, 0), (3600, 1), (3600, 1), (7200, 2)):
        result = tick_fronts(plan, now, mode="adaptive")
        assert result.next_plan["fronts"][0]["progress"] == expected
        assert result.next_plan["fronts"][0]["clock_at"] == expected * 3600
        plan = result.next_plan
    assert original == hourly_plan()


def test_explicit_fronts_have_independent_periods_and_persist_remainder():
    plan = hourly_plan()
    plan["fronts"].append({"id": "siege", "period": 7200, "clock_at": 0, "progress": 0, "maximum": 6})
    result = tick_fronts(plan, 7500, mode="adaptive")
    assert [f["progress"] for f in result.next_plan["fronts"]] == [2, 1]
    # Simulate a restart with only the persisted plan; the leftover 300 seconds survive.
    restarted = copy.deepcopy(result.next_plan)
    result = tick_fronts(restarted, 10800, mode="adaptive")
    assert [f["progress"] for f in result.next_plan["fronts"]] == [3, 1]
    assert [f["clock_at"] for f in result.next_plan["fronts"]] == [10800, 7200]


@pytest.mark.parametrize("status", ["stopped", "completed", "paused"])
def test_inactive_explicit_front_does_not_tick(status):
    plan = hourly_plan()
    plan["fronts"][0]["status"] = status
    result = tick_fronts(plan, 3 * 86400, mode="adaptive")
    assert result.next_plan["fronts"] == plan["fronts"]
    assert not result.progress_events
    assert not result.ready_intents


def test_new_front_clock_starts_at_first_tick_without_retroactive_progress():
    plan = hourly_plan()
    del plan["clock_at"]
    del plan["fronts"][0]["clock_at"]
    result = tick_fronts(plan, 10000)
    assert result.next_plan["fronts"][0]["clock_at"] == 10000
    assert not result.progress_events
    result = tick_fronts(result.next_plan, 13600)
    assert result.next_plan["fronts"][0]["progress"] == 1


def test_explicit_zero_clock_survives_global_initialization_and_view():
    plan = hourly_plan()
    del plan["clock_at"]
    result = tick_fronts(plan, 3600)
    assert result.next_plan["fronts"][0]["progress"] == 1
    plan["clock_at"] = 9000
    assert iter_fronts(plan)[0].clock_at == 0


def test_explicit_front_completion_caps_progress_and_emits_intent_once():
    plan = hourly_plan()
    plan["fronts"][0]["maximum"] = 2
    result = tick_fronts(plan, 20000, mode="adaptive")
    assert result.next_plan["fronts"][0]["progress"] == 2
    assert result.next_plan["fronts"][0]["status"] == "completed"
    assert len(result.progress_events) == 2
    repeated = tick_fronts(result.next_plan, 30000, mode="adaptive")
    assert not repeated.progress_events
    assert not repeated.ready_intents


@pytest.mark.parametrize("length", ["oneshot", "short", "long", "module"])
def test_legacy_strict_clock_matches_existing_plot_clock(length):
    plan = plan_with_front_near_threshold()
    for now in (3599, 3 * 86400, 3 * 86400, 7 * 86400):
        expected = copy.deepcopy(plan)
        plot.clock(expected, now, length)
        result = tick_fronts(plan, now, length=length, mode="strict")
        assert result.next_plan == expected
        assert not result.ready_intents
        plan = result.next_plan


def plan_with_front_near_threshold() -> dict:
    """Factory creating a campaign plan with an antagonist near readiness threshold."""
    return {
        "title": "Оборона Вестгейта",
        "campaign_id": "c_front_1",
        "clock_at": 0,
        "antagonists": [
            {
                "id": "cult_leader",
                "name": "Малакор Тёмный",
                "goal": "Открыть портал Бездны",
                "threat": [
                    "Захватить ритуальный клинок",
                    "Подготовить ритуальный круг",
                    "Призвать легион теней",
                ],
                "threat_step": 1,
            }
        ],
    }


def test_progress_readiness_does_not_materialize_an_army():
    """Clock ticking near threshold triggers a typed intent without freeform entity materialization."""
    plan = plan_with_front_near_threshold()
    result = tick_fronts(plan, game_time=86400 * 3, length="short", mode="adaptive")
    assert result.ready_intents
    assert all(intent.kind != "entity_created" for intent in result.ready_intents)
    assert any(intent.kind == "front_threshold_reached" for intent in result.ready_intents)


def test_clock_does_not_tick_twice_on_same_interval():
    """Ticking twice within the same or smaller time interval does not advance front again."""
    plan = plan_with_front_near_threshold()
    res1 = tick_fronts(plan, game_time=86400 * 3, length="short", mode="adaptive")
    assert len(res1.progress_events) == 1

    # Same game time: no second tick
    res2 = tick_fronts(res1.next_plan, game_time=86400 * 3, length="short", mode="adaptive")
    assert len(res2.progress_events) == 0
    assert res2.next_plan["antagonists"][0]["threat_step"] == res1.next_plan["antagonists"][0]["threat_step"]


def test_iter_fronts_adapts_antagonists_without_double_progress():
    """iter_fronts converts antagonists and fronts into consistent FrontViews."""
    plan = plan_with_front_near_threshold()
    fronts = iter_fronts(plan)
    assert len(fronts) == 1
    fv = fronts[0]
    assert fv.ref.id == "cult_leader"
    assert fv.progress == 1
    assert fv.maximum == 3
    assert fv.status == "active"
    assert "Призвать легион теней" in fv.milestones


def test_advance_front_deduplicates_transition_key():
    """advance_front rejects duplicate application of the same transition key."""
    fv = FrontView(
        ref=FrontRef(campaign_id="c1", source_kind="antagonist", source_id="cult_leader"),
        owner_ref="cult_leader",
        goal="Открыть портал",
        progress=1,
        maximum=3,
        status="active",
        milestones=("Шаг 1", "Шаг 2", "Шаг 3"),
    )
    ground = Ground(kind="consequence", evidence_refs=())
    trans1 = advance_front(fv, ground, transition_key="trans_step_2")
    assert trans1.violation is None
    assert trans1.new_progress == 2

    # Second advance with identical transition key is rejected
    fv2 = FrontView(
        ref=fv.ref,
        owner_ref=fv.owner_ref,
        goal=fv.goal,
        progress=trans1.new_progress,
        maximum=fv.maximum,
        status=trans1.new_status,
        milestones=fv.milestones,
    )
    trans2 = advance_front(fv2, ground, transition_key="trans_step_2", processed_keys={"trans_step_2"})
    assert trans2.violation == "duplicate_transition_key"
    assert trans2.new_progress == fv2.progress


def test_conversation_alone_does_not_stop_front_but_alliance_can():
    """Conversation without verified agreement does not halt a front, but formal alliance can stop it."""
    fv = FrontView(
        ref=FrontRef(campaign_id="c1", source_kind="antagonist", source_id="inquisitor"),
        owner_ref="inquisitor",
        goal="Искоренить ересь",
        progress=2,
        maximum=4,
        status="active",
    )
    # 1. Casual talk (interest) does not halt the front
    talk_ground = Ground(kind="interest", evidence_refs=())
    res_talk = advance_front(fv, talk_ground, transition_key="talk_1")
    assert res_talk.new_status == "active"

    # 2. Alliance agreement with halted intent stops the front
    alliance_ground = Ground(kind="relationship", evidence_refs=())
    res_alliance = advance_front(fv, alliance_ground, transition_key="alliance_1", stop=True)
    assert res_alliance.new_status == "stopped"


def test_secret_alliance_not_known_to_inquisition():
    """A secret pact fact carries restricted audience preventing leaks to inquisition."""
    from app.core.narrative.contracts import FactState, SnapshotRef

    secret_alliance_fact = FactState(
        ref=FactRef(
            campaign_id="c1",
            namespace="campaign",
            subject_id="npc.rebel_leader",
            key="relationship",
            version=1,
            snapshot_ref=SnapshotRef(
                kind="event", source_id="evt-1", typed_address="campaign:npc.rebel_leader:relationship"
            ),
        ),
        kind="truth",
        temporal_semantics="current_state",
        freedom="committed",
        value="Тайный пакт с повстанцами против культа",
        audience=("party", "npc.rebel_leader"),
    )
    assert "party" in secret_alliance_fact.audience
    assert "npc.rebel_leader" in secret_alliance_fact.audience
    assert "inquisition" not in secret_alliance_fact.audience
