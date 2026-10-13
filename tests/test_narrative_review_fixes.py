"""Regression coverage for review follow-ups A, B and C."""

import asyncio

import pytest
from sqlalchemy import select

from app.core.narrative.contracts import (
    EvidenceRecord,
    EvidenceRef,
    NarrativePolicy,
    TransitionThreadOp,
    WorkClaim,
)
from app.core.narrative.policy import admit_adaptation
from app.core.narrative.service import NarrativeService
from app.db.models import Campaign, Event, Message, NarrativeThread, NarrativeWork
from app.db.narrative import ensure_state
from app.db.narrative_jobs import SqlNarrativeJobs
from app.rules.dice import Dice
from app.tools.narrative.executor import apply_in_context
from app.tools.narrative.sources import bind_scene_sources
from app.tools.resolution.requests import bind_message_actions
from app.tools.runtime import open_context
from tests.game import import_base, party, run
from tests.narrative_helpers import FakeClock, boundary, proposal, snapshot, thread
from tests.test_narrative_service import FakeApplier, FakeAuthor, FakeJobs, FakeReader


@pytest.fixture
def session_maker(client):
    from app.db.session import make_sessionmaker

    return make_sessionmaker(client.app.state.engine)


def test_master_event_cannot_activate_thread():
    ev = EvidenceRecord(
        ref=EvidenceRef(campaign_id="camp-1", kind="event", source_id="evt-master"),
        status="applied",
        applied_result="say",
        subject_refs=("npc-1",),
        audience=("party",),
    )
    snap = snapshot(evidence=(ev,), threads=(thread(id="th-1", status="offered", subject_refs=("npc-1",)),))
    prop = proposal(
        snap, ground_kind="consequence", operations=(TransitionThreadOp(thread_id="th-1", target_status="active"),)
    )
    result = admit_adaptation(snap, prop, NarrativePolicy(mode="adaptive"))
    assert result.status == "denied"
    assert result.reason_code == "player_choice_required"


@pytest.mark.parametrize(
    "variant",
    [
        "matching",
        "unrelated",
        "missing_message",
        "wrong_seat",
        "not_completed",
        "wrong_actor",
        "foreign_ref",
        "wrong_part",
        "denied_result",
        "ordinary",
        "unbound_event",
    ],
)
def test_persisted_player_action_controls_thread_activation(variant, settings, client, admin):
    import_base(settings)
    c, _, hero = party(client, admin, narrative_mode="adaptive")
    cid = c["id"]

    async def go(s):
        campaign = await s.get(Campaign, cid)
        ctx = await open_context(s, campaign, Dice(), turn_id=None, seat_id=None)
        player = ctx.world.characters[hero["id"]]
        msg = Message(
            campaign_id=cid,
            seq=1000,
            kind="action",
            seat_id=player.seat_id,
            content="Иду исследовать место",
            intent={"actions": [{"verb": "inspect", "target_id": "place-1"}]},
        )
        s.add(msg)
        await s.flush()
        ref = bind_message_actions(msg, player.id)[0]
        ev = Event(
            campaign_id=cid,
            tool="resolve_action",
            actor_id=player.id,
            payload={
                "ref": ref.model_dump(),
                "resolution": {"execution": "applied", "event_ids": [], "completed_parts": [0]},
            },
        )
        s.add(ev)
        await s.flush()
        msg.data = {
            **msg.data,
            "resolution_completed": {"0": {"execution": "applied", "event_ids": [ev.id], "completed_parts": [0]}},
        }
        if variant == "wrong_seat":
            msg.seat_id = None
        if variant == "not_completed":
            msg.data = {**msg.data, "resolution_completed": {}}
        if variant == "missing_message":
            ev.payload = {**ev.payload, "ref": {**ref.model_dump(), "source_id": "missing"}}
        if variant == "wrong_actor":
            ev.actor_id = "another-hero"
        if variant == "foreign_ref":
            ev.payload = {**ev.payload, "ref": {**ref.model_dump(), "campaign_id": "foreign-campaign"}}
        if variant == "wrong_part":
            ev.payload = {**ev.payload, "ref": {**ref.model_dump(), "part": 1}}
        if variant == "denied_result":
            msg.data = {**msg.data, "resolution_completed": {"0": {"execution": "denied"}}}
        if variant in ("ordinary", "unbound_event"):
            ev.tool = "roll_check"
            if variant == "ordinary":
                # Ordinary tools store the part as the dict key, without completed_parts.
                msg.data = {**msg.data, "resolution_completed": {"0": {"execution": "applied", "event_ids": [ev.id]}}}
            else:
                msg.data = {**msg.data, "resolution_completed": {"0": {"execution": "applied", "event_ids": []}}}
        s.add(
            NarrativeThread(
                campaign_id=cid,
                thread_id="th-review",
                status="offered",
                version=1,
                subject_refs=["unrelated-place" if variant == "unrelated" else "place-1"],
                audience=["party"],
            )
        )
        state = await ensure_state(s, cid)
        state.mode = "adaptive"
        await s.flush()
        source = (await bind_scene_sources(ctx))[0]
        from app.core.narrative.contracts import Ground, SnapshotRequest
        from app.tools.narrative.context import load_snapshot

        refs = (EvidenceRef(campaign_id=cid, kind="event", source_id=ev.id),)
        if variant in ("ordinary", "unbound_event"):
            refs += (EvidenceRef(campaign_id=cid, kind="message", source_id=msg.id),)
        req = SnapshotRequest(source=source, evidence_refs=refs)
        snap = await load_snapshot(ctx, req, policy=NarrativePolicy(mode="adaptive"))
        prop = proposal(
            snap,
            grounds=(Ground(kind="consequence", evidence_refs=req.evidence_refs),),
            operations=(TransitionThreadOp(thread_id="th-review", target_status="active"),),
        )
        result = await apply_in_context(ctx, prop, policy=NarrativePolicy(mode="adaptive"))
        await s.commit()
        row = await s.scalar(
            select(NarrativeThread).where(NarrativeThread.campaign_id == cid, NarrativeThread.thread_id == "th-review")
        )
        if variant in ("matching", "ordinary"):
            assert result.status == "applied"
            assert row.status == "active"
        else:
            assert result.status == "denied"
            assert result.reason_code == "player_choice_required"
            assert row.status == "offered"

    run(settings, go)


def author_claim():
    snap = snapshot()
    return WorkClaim(
        work_id="w-review",
        campaign_id="camp-1",
        source=snap.source,
        proposal_id=snap.proposal_id,
        lease_token="l-review",
        lease_until=FakeClock()(),
        session_budget_ref="sess-1",
        phase="author",
    )


@pytest.mark.parametrize("stage", ["snapshot", "reserve_call", "renew", "author", "save_draft"])
def test_failure_after_claim_is_recorded_without_exception_text(stage, caplog):
    class Reader(FakeReader):
        async def snapshot(self, request):
            if stage == "snapshot":
                raise RuntimeError("secret-test-marker")
            return await super().snapshot(request)

    class Jobs(FakeJobs):
        async def reserve_call(self, claim, now):
            if stage == "reserve_call":
                raise RuntimeError("secret-test-marker")
            return await super().reserve_call(claim, now)

        async def renew(self, claim, now):
            if stage == "renew":
                raise RuntimeError("secret-test-marker")
            return True

        async def save_draft(self, claim, prop, now):
            if stage == "save_draft":
                raise RuntimeError("secret-test-marker")
            await super().save_draft(claim, prop, now)

    class Author(FakeAuthor):
        async def propose(self, snapshot):
            if stage == "author":
                raise RuntimeError("secret-test-marker")
            return await super().propose(snapshot)

    jobs = Jobs([author_claim()])
    service = NarrativeService(Reader(), Author(), FakeApplier(), jobs, FakeClock())
    report = asyncio.run(service.prepare_once())
    assert report.work_id == "w-review"
    assert report.reason_code == f"{stage}_error"
    assert len(jobs.finished_results) == 1
    assert "secret-test-marker" not in repr(report)
    assert "secret-test-marker" not in repr(jobs.finished_results)
    assert "secret-test-marker" not in caplog.text
    assert jobs.reserved_calls == (0 if stage in ("snapshot", "reserve_call") else 1)


def test_failed_renew_does_not_call_model_or_finish_another_workers_job():
    class Jobs(FakeJobs):
        async def renew(self, claim, now):
            return False

    author = FakeAuthor()
    jobs = Jobs([author_claim()])
    service = NarrativeService(FakeReader(), author, FakeApplier(), jobs, FakeClock())
    report = asyncio.run(service.prepare_once())
    assert report.reason_code == "lease_lost"
    assert author.calls == 0
    assert not jobs.finished_results


def test_snapshot_failure_releases_sql_job_before_lease_expiry(session_maker):
    from tests.test_narrative_jobs import _ensure_campaigns

    class Reader(FakeReader):
        async def snapshot(self, request):
            raise RuntimeError("secret-test-marker")

    async def go():
        await _ensure_campaigns(session_maker, "camp-review")
        clock = FakeClock()
        jobs = SqlNarrativeJobs(session_maker)
        wid = await jobs.enqueue(boundary(campaign_id="camp-review"))
        author = FakeAuthor()
        service = NarrativeService(Reader(), author, FakeApplier(), jobs, clock)
        report = await service.prepare_once("camp-review")
        assert report.work_id == wid
        assert report.reason_code == "snapshot_error"
        async with session_maker() as s:
            row = await s.get(NarrativeWork, wid)
            assert row.status == "retry_wait"
            assert row.lease_token is None and row.lease_until is None
            assert row.capacity_slot is None
            assert row.llm_calls == 0
        assert author.calls == 0

    asyncio.run(go())


@pytest.mark.parametrize("stage", ["apply", "claim", "failure_recording", "lease_lost"])
def test_failure_reports_and_logs_remain_safe(stage, caplog):
    from app.core.narrative.contracts import LeaseLost

    class Jobs(FakeJobs):
        async def claim(self, now, *, campaign_id=None):
            if stage == "claim":
                raise RuntimeError("secret-test-marker")
            return await super().claim(now, campaign_id=campaign_id)

        async def finish(self, claim, result, now, *, feedback=None):
            if stage == "failure_recording":
                raise RuntimeError("secret-test-marker")
            if stage == "lease_lost":
                raise LeaseLost("secret-test-marker")
            await super().finish(claim, result, now, feedback=feedback)

    class Reader(FakeReader):
        async def snapshot(self, request):
            raise RuntimeError("secret-test-marker")

    class Applier(FakeApplier):
        async def apply(self, proposal, *, claim=None):
            raise RuntimeError("secret-test-marker")

    claim = author_claim()
    if stage == "apply":
        claim = claim.model_copy(update={"phase": "apply", "draft": proposal()})
    jobs = Jobs([claim])
    service = NarrativeService(Reader(), FakeAuthor(), Applier(), jobs, FakeClock())
    report = asyncio.run(service.run_due(limit=1))[0]
    assert (
        report.reason_code
        == {
            "apply": "apply_error",
            "claim": "batch_error",
            "failure_recording": "failure_recording_error",
            "lease_lost": "lease_lost",
        }[stage]
    )
    assert "secret-test-marker" not in repr(report)
    assert "secret-test-marker" not in caplog.text
    if stage != "claim":
        assert report.work_id == claim.work_id


def test_snapshot_failure_does_not_block_next_campaign():
    first = author_claim()
    second = first.model_copy(
        update={
            "work_id": "w-second",
            "campaign_id": "camp-2",
            "source": first.source.model_copy(update={"campaign_id": "camp-2"}),
        }
    )

    class Reader(FakeReader):
        async def snapshot(self, request):
            if request.source.campaign_id == first.campaign_id:
                raise RuntimeError("secret-test-marker")
            return snapshot(source=request.source)

    jobs = FakeJobs([first, second])
    service = NarrativeService(Reader(), FakeAuthor(), FakeApplier(), jobs, FakeClock())
    reports = asyncio.run(service.run_due(limit=2))
    assert [r.work_id for r in reports] == ["w-review", "w-second"]
    assert [r.status for r in reports] == ["failed", "prepared"]
    assert len(jobs.finished_results) == 1
    assert len(jobs.saved_drafts) == 1


@pytest.mark.parametrize("status", ["applied", "no_change"])
def test_transient_finish_failure_preserves_committed_result(status, session_maker):
    from app.core.narrative.contracts import AdaptationResult
    from tests.test_narrative_jobs import _ensure_campaigns

    class Jobs(SqlNarrativeJobs):
        failures_left = 1

        async def finish(self, claim, result, now=None, *, feedback=None):
            if self.failures_left:
                self.failures_left -= 1
                raise RuntimeError("secret-test-marker")
            await super().finish(claim, result, now, feedback=feedback)

    async def go():
        await _ensure_campaigns(session_maker, "camp-finish")
        clock = FakeClock()
        jobs = Jobs(session_maker)
        wid = await jobs.enqueue(boundary(campaign_id="camp-finish"))
        claim = await jobs.claim(clock())
        claim = await jobs.reserve_call(claim, clock())
        claim = await jobs.reserve_call(claim, clock())
        draft = proposal(snapshot(source=claim.source, proposal_id=claim.proposal_id), operations=())
        await jobs.save_draft(claim, draft, clock())
        async with session_maker() as s:
            ev = Event(campaign_id="camp-finish", tool="adapt_story", payload={"status": status})
            s.add(ev)
            await s.commit()
            receipt_id = ev.id
        author = FakeAuthor()
        service = NarrativeService(
            FakeReader(),
            author,
            FakeApplier(AdaptationResult(status=status, reason_code=status, event_ids=(receipt_id,))),
            jobs,
            clock,
        )
        report = await service.prepare_once("camp-finish")
        assert report.status == status
        async with session_maker() as s:
            row = await s.get(NarrativeWork, wid)
            assert row.status == status
            assert row.receipt_event_id == receipt_id
            assert row.draft == draft.model_dump(mode="json")
            assert row.llm_calls == 2
            assert row.lease_token is None
        clock.advance(6)
        assert await jobs.claim(clock(), campaign_id="camp-finish") is None
        assert author.calls == 0

    asyncio.run(go())


def test_transient_finish_failure_keeps_corrective_feedback():
    from app.core.narrative.contracts import AdaptationResult

    class Jobs(FakeJobs):
        failures_left = 1

        async def finish(self, claim, result, now=None, *, feedback=None):
            if self.failures_left:
                self.failures_left -= 1
                raise RuntimeError("secret-test-marker")
            await super().finish(claim, result, now, feedback=feedback)

    claim = author_claim().model_copy(update={"phase": "apply", "draft": proposal(), "llm_calls": 1})
    jobs = Jobs([claim])
    denied = AdaptationResult(status="denied", reason_code="novelty_exceeded")
    service = NarrativeService(FakeReader(), FakeAuthor(), FakeApplier(denied), jobs, FakeClock())
    report = asyncio.run(service.prepare_once())
    assert report.status == "retry_wait"
    assert jobs.finished_results == [denied]
    assert jobs.finished_feedbacks[0][0].code == "novelty_exceeded"
