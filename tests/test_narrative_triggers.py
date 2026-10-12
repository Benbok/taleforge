"""Tests for narrative boundary triggers, deduplication, and coalescing (Task 15 / Gate B)."""

import asyncio
from datetime import UTC, datetime
from typing import Any

import pytest
from sqlalchemy import select

from app.core.narrative.contracts import (
    BoundaryRecord,
    EvidenceRecord,
    EvidenceRef,
    NarrativePolicy,
    TurnBoundaryState,
)
from app.core.narrative.triggers import derive_boundaries, enqueue_boundaries
from app.db.models import Campaign, NarrativeState, NarrativeWork, User
from app.db.narrative import ensure_state
from app.db.session import make_sessionmaker
from app.tools.registry import ToolContext
from tests.game import QueueDice, import_base, party
from tests.narrative_helpers import policy


def adaptation_evidence(**overrides: Any) -> EvidenceRecord:
    defaults: dict[str, Any] = {
        "ref": EvidenceRef(campaign_id="camp-1", kind="event", source_id="evt-adapt-1"),
        "status": "applied",
        "subject_refs": ("npc-1",),
        "audience": ("party",),
        "game_time": 100,
        "applied_result": "adapt_story",
    }
    defaults.update(overrides)
    return EvidenceRecord(**defaults)


def turn_boundary(**overrides: Any) -> TurnBoundaryState:
    defaults: dict[str, Any] = {
        "id": "turn-1",
        "phase": "turn",
        "session_id": "sess-1",
        "focus": None,
        "audience": ("party",),
        "external_boundary": False,
    }
    defaults.update(overrides)
    return TurnBoundaryState(**defaults)


def _make_ctx(session, campaign, call_key="k1") -> ToolContext:
    return ToolContext(
        session=session,
        campaign=campaign,
        world=None,
        dice=QueueDice([20]),
        game_session_id="sess-1",
        turn_id="turn-1",
        actor_seat_id=None,
        call_key=call_key,
    )


def test_adaptation_events_do_not_spawn_recursive_director_jobs():
    boundaries = derive_boundaries(
        (adaptation_evidence(),),
        turn_boundary(external_boundary=False),
        policy(),
    )
    assert boundaries == ()


def test_derive_boundaries_deduplicates_same_boundary():
    ev1 = EvidenceRecord(
        ref=EvidenceRef(campaign_id="camp-1", kind="event", source_id="evt-rel-1"),
        status="applied",
        subject_refs=("npc-1",),
        audience=("party",),
        game_time=100,
        applied_result="alliance_formed",
    )
    ev2 = EvidenceRecord(
        ref=EvidenceRef(campaign_id="camp-1", kind="event", source_id="evt-rel-2"),
        status="applied",
        subject_refs=("npc-1",),
        audience=("party",),
        game_time=100,
        applied_result="alliance_formed",
    )
    boundaries = derive_boundaries(
        (ev1, ev2),
        turn_boundary(external_boundary=False),
        policy(),
    )
    assert len(boundaries) == 1
    b = boundaries[0]
    assert b.kind == "relationship"
    assert b.source_id == "npc-1"
    assert len(b.evidence_refs) == 2
    assert {r.source_id for r in b.evidence_refs} == {"evt-rel-1", "evt-rel-2"}


def test_player_rejection_of_main_hook_triggers_choice_boundary():
    ev = EvidenceRecord(
        ref=EvidenceRef(campaign_id="camp-1", kind="event", source_id="evt-choice-1"),
        status="rejected",
        subject_refs=("main_hook",),
        audience=("party",),
        game_time=200,
        applied_result="transition_thread",
    )
    boundaries = derive_boundaries(
        (ev,),
        turn_boundary(external_boundary=False),
        policy(),
    )
    assert len(boundaries) == 1
    assert boundaries[0].kind == "choice"
    assert boundaries[0].source_id == "main_hook"


def test_situation_closed_triggers_boundary():
    ev = EvidenceRecord(
        ref=EvidenceRef(campaign_id="camp-1", kind="event", source_id="evt-sit-1"),
        status="applied",
        subject_refs=("node_1",),
        audience=("party",),
        game_time=300,
        applied_result="advance_plot",
    )
    boundaries = derive_boundaries(
        (ev,),
        turn_boundary(external_boundary=False),
        policy(),
    )
    assert len(boundaries) == 1
    assert boundaries[0].kind == "situation_closed"
    assert boundaries[0].source_id == "node_1"


def test_act_closed_triggers_act_boundary():
    ev = EvidenceRecord(
        ref=EvidenceRef(campaign_id="camp-1", kind="event", source_id="evt-act-1"),
        status="applied",
        subject_refs=("act_1",),
        audience=("party",),
        game_time=400,
        applied_result="end_act",
    )
    boundaries = derive_boundaries(
        (ev,),
        turn_boundary(external_boundary=False),
        policy(),
    )
    assert len(boundaries) == 1
    assert boundaries[0].kind == "act_closed"


def test_session_closed_and_front_threshold_boundaries():
    ev_front = EvidenceRecord(
        ref=EvidenceRef(campaign_id="camp-1", kind="event", source_id="evt-front-1"),
        status="applied",
        subject_refs=("antagonist_1",),
        audience=("party",),
        game_time=500,
        applied_result="front_threshold",
    )
    boundaries_front = derive_boundaries(
        (ev_front,),
        turn_boundary(external_boundary=False),
        policy(),
    )
    assert len(boundaries_front) == 1
    assert boundaries_front[0].kind == "front_threshold"

    boundaries_session = derive_boundaries(
        (),
        turn_boundary(phase="session_closed", external_boundary=True),
        policy(),
    )
    assert len(boundaries_session) == 1
    assert boundaries_session[0].kind == "session_closed"


def test_enqueue_boundaries_replan_false_skips_enqueuing(settings, client, admin):
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    cid = c["id"]

    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            camp.settings = {**(camp.settings or {}), "replan": False}
            n_state = await ensure_state(s, cid)
            n_state.mode = "adaptive"
            await s.commit()

        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = _make_ctx(s, camp, call_key="k1")
            b = BoundaryRecord(
                campaign_id=cid,
                kind="choice",
                source_id="c1",
                scope="future",
                session_budget_ref="sess-1",
            )
            enqueued = await enqueue_boundaries(ctx, (b,))
            assert enqueued == ()
            # Verify no work row
            works = (await s.scalars(select(NarrativeWork).where(NarrativeWork.campaign_id == cid))).all()
            assert len(works) == 0

    asyncio.run(_run())


def test_enqueue_boundaries_coalesces_pending_jobs(settings, client, admin):
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    cid = c["id"]

    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        async with maker() as s:
            n_state = await ensure_state(s, cid)
            n_state.mode = "adaptive"
            await s.commit()

        # Step 1: Enqueue first boundary
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = _make_ctx(s, camp, call_key="k1")
            b1 = BoundaryRecord(
                campaign_id=cid,
                kind="relationship",
                source_id="rel-1",
                scope="future",
                evidence_refs=(EvidenceRef(campaign_id=cid, kind="event", source_id="evt-1"),),
                session_budget_ref="sess-1",
            )
            ids1 = await enqueue_boundaries(ctx, (b1,))
            await s.commit()
            assert len(ids1) == 1

        first_job_id = ids1[0]

        # Step 2: Enqueue second boundary while first is pending -> coalesce
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = _make_ctx(s, camp, call_key="k2")
            b2 = BoundaryRecord(
                campaign_id=cid,
                kind="choice",
                source_id="choice-2",
                scope="future",
                evidence_refs=(EvidenceRef(campaign_id=cid, kind="event", source_id="evt-2"),),
                session_budget_ref="sess-1",
            )
            ids2 = await enqueue_boundaries(ctx, (b2,))
            await s.commit()
            assert len(ids2) == 1

        new_job_id = ids2[0]
        assert new_job_id != first_job_id

        # Verify old job is superseded and grounds are preserved in new job
        async with maker() as s:
            old_work = await s.get(NarrativeWork, first_job_id)
            new_work = await s.get(NarrativeWork, new_job_id)
            assert old_work.status == "superseded"
            assert (old_work.draft or {}).get("superseded_by") == new_job_id
            assert new_work.status == "pending"
            # Grounds (evidence_refs) from both b1 and b2 are preserved
            refs = {r["source_id"] for r in new_work.evidence_refs}
            assert "evt-1" in refs
            assert "evt-2" in refs

    asyncio.run(_run())


def test_enqueue_boundaries_does_not_modify_preparing_job(settings, client, admin):
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    cid = c["id"]

    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        now_utc = datetime.now(UTC)
        async with maker() as s:
            n_state = await ensure_state(s, cid)
            n_state.mode = "adaptive"
            work = NarrativeWork(
                campaign_id=cid,
                source_key="choice:c1",
                scope="future",
                kind="choice",
                source_id="c1",
                session_budget_ref="sess-1",
                status="preparing",
                capacity_slot=1,
                lease_token="lease-1",
                proposal_id="prop-1",
                created_at=now_utc,
                updated_at=now_utc,
            )
            s.add(work)
            await s.commit()

        # Enqueue new boundary while another job is preparing -> does not supersede claimed work
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = _make_ctx(s, camp, call_key="k1")
            b = BoundaryRecord(
                campaign_id=cid,
                kind="relationship",
                source_id="r1",
                scope="future",
                session_budget_ref="sess-1",
            )
            enqueued = await enqueue_boundaries(ctx, (b,))
            await s.commit()
            assert len(enqueued) == 1

        async with maker() as s:
            claimed = (await s.scalars(select(NarrativeWork).where(NarrativeWork.source_key == "choice:c1"))).one()
            assert claimed.status == "preparing"
            assert claimed.capacity_slot == 1

    asyncio.run(_run())


def test_session_budget_ref_preserved_across_pause(settings, client, admin):
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    cid = c["id"]

    maker = make_sessionmaker(client.app.state.engine)

    async def _run():
        async with maker() as s:
            camp = await s.get(Campaign, cid)
            camp.settings = {**(camp.settings or {}), "paused": True}
            n_state = await ensure_state(s, cid)
            n_state.mode = "adaptive"
            await s.commit()

        async with maker() as s:
            camp = await s.get(Campaign, cid)
            ctx = _make_ctx(s, camp, call_key="k1")
            b = BoundaryRecord(
                campaign_id=cid,
                kind="choice",
                source_id="c1",
                scope="future",
                session_budget_ref="stable-session-budget-123",
            )
            enqueued = await enqueue_boundaries(ctx, (b,))
            await s.commit()
            assert len(enqueued) == 1

        async with maker() as s:
            work = await s.get(NarrativeWork, enqueued[0])
            assert work.session_budget_ref == "stable-session-budget-123"

    asyncio.run(_run())
