"""Tests for durable director jobs, leases, and state machine (spec §15, Task 12)."""

import asyncio

import pytest
from sqlalchemy import select

from app.core import world_tx
from app.core.narrative.contracts import (
    AdaptationResult,
    LeaseLost,
    WorkClaim,
)
from app.db.models import Campaign, NarrativeWork, User, as_utc
from app.db.narrative_jobs import SqlNarrativeJobs
from app.db.session import make_sessionmaker
from tests.game import import_base, party
from tests.narrative_helpers import FakeClock, boundary, proposal


@pytest.fixture
def session_maker(client):
    return make_sessionmaker(client.app.state.engine)


@pytest.fixture
def campaign_fixture(settings, client, admin):
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    return c


async def _ensure_campaigns(session_maker, *cids: str) -> None:
    async with session_maker() as session:
        user = await session.scalar(select(User).where(User.id == "job-test-user"))
        if not user:
            user = User(id="job-test-user", name="tester", password_hash="hash")
            session.add(user)
            await session.flush()
        for cid in cids:
            camp = await session.scalar(select(Campaign).where(Campaign.id == cid))
            if not camp:
                camp = Campaign(id=cid, name=f"Camp {cid}", owner_id=user.id, ruleset_version="1.0.0")
                session.add(camp)
        await session.commit()



def lease_takeover_scenario(settings, client, admin) -> dict:
    """Simulates a slow worker whose lease expires and gets taken over by a second worker."""
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    cid = c["id"]

    maker = make_sessionmaker(client.app.state.engine)
    clock = FakeClock()
    jobs = SqlNarrativeJobs(maker, max_author_slots=2)

    b = boundary(campaign_id=cid, source_id="takeover-1")

    async def _run():
        await jobs.enqueue(b)

        # Worker 1 claims job
        claim1 = await jobs.claim(clock())
        assert claim1 is not None
        assert claim1.phase == "author"

        # Worker 1 reserves 1st LLM call
        reserved1 = await jobs.reserve_call(claim1, clock())
        assert reserved1 is not None
        assert reserved1.llm_calls == 1

        # Time passes beyond 120s lease duration
        clock.advance(150)

        # Worker 2 claims the same job whose lease expired
        claim2 = await jobs.claim(clock())
        assert claim2 is not None
        assert claim2.work_id == claim1.work_id
        assert claim2.lease_token != claim1.lease_token

        # Worker 2 reserves 2nd LLM call
        reserved2 = await jobs.reserve_call(claim2, clock())
        assert reserved2 is not None
        assert reserved2.llm_calls == 2

        # Worker 2 successfully saves draft
        prop2 = proposal(summary="Новый владелец")
        await jobs.save_draft(claim2, prop2, clock())

        # Worker 1 wakes up late and attempts to save draft
        old_save_rejected = False
        try:
            prop1 = proposal(summary="Старый владелец")
            await jobs.save_draft(claim1, prop1, clock())
        except LeaseLost:
            old_save_rejected = True

        # Read active job from DB
        async with maker() as session:
            work = await session.scalar(
                select(NarrativeWork).where(NarrativeWork.id == claim1.work_id)
            )
            assert work is not None
            active_draft_summary = work.draft.get("summary") if work.draft else None
            llm_calls = work.llm_calls

        return {
            "old_save_rejected": old_save_rejected,
            "active_draft_summary": active_draft_summary,
            "llm_calls": llm_calls,
        }

    return asyncio.run(_run())


def test_old_lease_cannot_replace_saved_draft(settings, client, admin):
    report = lease_takeover_scenario(settings, client, admin)
    assert report["old_save_rejected"]
    assert report["active_draft_summary"] == "Новый владелец"
    assert report["llm_calls"] <= 2


def test_duplicate_enqueue_returns_same_job_id(session_maker):
    async def _test():
        await _ensure_campaigns(session_maker, "camp-dup")
        jobs = SqlNarrativeJobs(session_maker, max_author_slots=2)
        b = boundary(campaign_id="camp-dup", source_id="src-dup")

        job_id_1 = await jobs.enqueue(b)
        job_id_2 = await jobs.enqueue(b)

        assert job_id_1 == job_id_2
        async with session_maker() as session:
            records = (
                await session.scalars(
                    select(NarrativeWork).where(NarrativeWork.campaign_id == "camp-dup")
                )
            ).all()
            assert len(records) == 1
            assert records[0].status == "pending"

    asyncio.run(_test())


def test_claim_author_capacity_slots_limit(session_maker):
    async def _test():
        await _ensure_campaigns(session_maker, "camp-c1", "camp-c2", "camp-c3")
        clock = FakeClock()
        jobs = SqlNarrativeJobs(session_maker, max_author_slots=2)

        # 3 different campaigns
        b1 = boundary(campaign_id="camp-c1", source_id="src-1")
        b2 = boundary(campaign_id="camp-c2", source_id="src-2")
        b3 = boundary(campaign_id="camp-c3", source_id="src-3")

        await jobs.enqueue(b1)
        await jobs.enqueue(b2)
        await jobs.enqueue(b3)

        claim1 = await jobs.claim(clock())
        assert claim1 is not None
        assert claim1.capacity_slot == 0
        assert claim1.phase == "author"

        claim2 = await jobs.claim(clock())
        assert claim2 is not None
        assert claim2.capacity_slot == 1
        assert claim2.phase == "author"

        # Both slots are occupied: 3rd claim returns None
        claim3 = await jobs.claim(clock())
        assert claim3 is None

        # Enqueue a second job for camp-c1
        b1_next = boundary(campaign_id="camp-c1", source_id="src-1-next")
        await jobs.enqueue(b1_next)

        # Finish claim2 (frees slot 1)
        prop2 = proposal(summary="Завершено c2")
        await jobs.save_draft(claim2, prop2, clock())

        # Claim prepared camp-c2 for apply and finish it
        claim2_apply = await jobs.claim(clock())
        assert claim2_apply is not None
        assert claim2_apply.phase == "apply"
        await jobs.finish(
            claim2_apply,
            AdaptationResult(status="applied", reason_code="ok"),
            clock(),
        )

        # Now slot 1 is free, but camp-c1 is already preparing (claim1 is active)!
        # Trying to claim should skip camp-c1 and claim camp-c3 for authoring
        claim3_now = await jobs.claim(clock())
        assert claim3_now is not None
        assert claim3_now.campaign_id == "camp-c3"
        assert claim3_now.capacity_slot == 1
        assert claim3_now.phase == "author"

    asyncio.run(_test())


def test_reserve_call_budget_limit(session_maker):
    async def _test():
        await _ensure_campaigns(session_maker, "camp-calls")
        clock = FakeClock()
        jobs = SqlNarrativeJobs(session_maker, max_author_slots=2)

        b = boundary(campaign_id="camp-calls", source_id="src-calls")
        await jobs.enqueue(b)

        claim = await jobs.claim(clock())
        assert claim is not None

        r1 = await jobs.reserve_call(claim, clock())
        assert r1 is not None
        assert r1.llm_calls == 1

        r2 = await jobs.reserve_call(claim, clock())
        assert r2 is not None
        assert r2.llm_calls == 2

        # 3rd call exceeds budget limit (max 2)
        r3 = await jobs.reserve_call(claim, clock())
        assert r3 is None

    asyncio.run(_test())


def test_claim_attempts_limit_and_rejected_status(session_maker):
    async def _test():
        await _ensure_campaigns(session_maker, "camp-attempts")
        clock = FakeClock()
        jobs = SqlNarrativeJobs(session_maker, max_author_slots=2)

        b = boundary(campaign_id="camp-attempts", source_id="src-attempts")
        await jobs.enqueue(b)

        # 6 allowed claim attempts
        for i in range(1, 7):
            c = await jobs.claim(clock())
            assert c is not None, f"Claim attempt {i} should succeed"
            assert c.attempts == i
            # Expire lease and advance past max retry backoff (60s): 120s lease + 80s = 200s
            clock.advance(200)

        # 7th claim: exceeds max 6 attempts -> transitions to rejected, returns None
        c7 = await jobs.claim(clock())
        assert c7 is None


        async with session_maker() as session:
            work = await session.scalar(
                select(NarrativeWork).where(NarrativeWork.campaign_id == "camp-attempts")
            )
            assert work is not None
            assert work.status == "rejected"

    asyncio.run(_test())


def test_resnapshot_limit(session_maker):
    async def _test():
        await _ensure_campaigns(session_maker, "camp-resnap")
        clock = FakeClock()
        jobs = SqlNarrativeJobs(session_maker, max_author_slots=2)

        b = boundary(campaign_id="camp-resnap", source_id="src-resnap")

        await jobs.enqueue(b)

        claim = await jobs.claim(clock())
        assert claim is not None
        old_prop_id = claim.proposal_id

        # 1st resnapshot succeeds
        updated_claim = await jobs.resnapshot(claim, clock())
        assert updated_claim is not None
        assert updated_claim.proposal_id != old_prop_id

        # 2nd resnapshot on the same job returns None (max 1 resnapshot per job)
        failed_claim = await jobs.resnapshot(claim, clock())
        assert failed_claim is None

    asyncio.run(_test())


def test_prepared_job_claimed_for_apply_phase(session_maker):
    async def _test():
        await _ensure_campaigns(session_maker, "camp-apply")
        clock = FakeClock()
        jobs = SqlNarrativeJobs(session_maker, max_author_slots=2)

        b = boundary(campaign_id="camp-apply", source_id="src-apply")
        await jobs.enqueue(b)

        author_claim = await jobs.claim(clock())
        assert author_claim is not None
        assert author_claim.phase == "author"

        prop = proposal(summary="Черновик для применения")
        await jobs.save_draft(author_claim, prop, clock())

        # Next claim should yield phase="apply"
        apply_claim = await jobs.claim(clock())
        assert apply_claim is not None
        assert apply_claim.phase == "apply"
        assert apply_claim.draft is not None
        assert apply_claim.draft.summary == "Черновик для применения"
        assert apply_claim.capacity_slot is None

    asyncio.run(_test())


def test_deferred_result_keeps_prepared_status_without_reauthoring(session_maker):
    async def _test():
        await _ensure_campaigns(session_maker, "camp-defer")
        clock = FakeClock()
        jobs = SqlNarrativeJobs(session_maker, max_author_slots=2)

        b = boundary(campaign_id="camp-defer", source_id="src-defer")
        await jobs.enqueue(b)

        claim_author = await jobs.claim(clock())
        prop = proposal(summary="Отложенное предложение")
        await jobs.save_draft(claim_author, prop, clock())

        claim_apply = await jobs.claim(clock())
        assert claim_apply is not None
        assert claim_apply.phase == "apply"

        # Finish with deferred result
        defer_res = AdaptationResult(
            status="deferred",
            reason_code="combat_active",
        )
        await jobs.finish(claim_apply, defer_res, clock())

        # Status remains prepared with retry_after
        async with session_maker() as session:
            work = await session.scalar(
                select(NarrativeWork).where(NarrativeWork.campaign_id == "camp-defer")
            )
            assert work is not None
            assert work.status == "prepared"
            assert work.retry_after is not None

        # Before retry_after: claim returns None
        claim_too_early = await jobs.claim(clock())
        assert claim_too_early is None

        # Advance clock past retry_after
        clock.advance(60)

        # Claim again: still in phase="apply" with same draft, without needing to author again
        claim_retry = await jobs.claim(clock())
        assert claim_retry is not None
        assert claim_retry.phase == "apply"
        assert claim_retry.draft is not None
        assert claim_retry.draft.summary == "Отложенное предложение"

    asyncio.run(_test())


def test_renew_extends_lease(session_maker):
    async def _test():
        await _ensure_campaigns(session_maker, "camp-renew")
        clock = FakeClock()
        jobs = SqlNarrativeJobs(session_maker, max_author_slots=2)

        b = boundary(campaign_id="camp-renew", source_id="src-renew")

        await jobs.enqueue(b)

        claim = await jobs.claim(clock())
        assert claim is not None
        orig_lease_until = claim.lease_until

        clock.advance(30)
        renewed = await jobs.renew(claim, clock())
        assert renewed is True

        async with session_maker() as session:
            work = await session.scalar(
                select(NarrativeWork).where(NarrativeWork.id == claim.work_id)
            )
            assert work is not None
            assert as_utc(work.lease_until) > orig_lease_until

        # Renew with invalid token fails
        fake_claim = WorkClaim(
            work_id=claim.work_id,
            campaign_id=claim.campaign_id,
            source=claim.source,
            proposal_id=claim.proposal_id,
            lease_token="invalid-token",
            lease_until=clock(),
            session_budget_ref="sess-1",
        )
        renewed_fake = await jobs.renew(fake_claim, clock())
        assert renewed_fake is False

    asyncio.run(_test())


def test_job_operations_do_not_increase_world_revision(
    session_maker, campaign_fixture
):
    cid = campaign_fixture["id"]
    clock = FakeClock()
    jobs = SqlNarrativeJobs(session_maker, max_author_slots=2)

    async def _test():
        async with session_maker() as session:
            rev_start = await world_tx.read_revision(session, cid)

        b = boundary(campaign_id=cid, source_id="src-rev-test")
        await jobs.enqueue(b)

        async with session_maker() as session:
            assert await world_tx.read_revision(session, cid) == rev_start

        claim = await jobs.claim(clock())
        assert claim is not None

        async with session_maker() as session:
            assert await world_tx.read_revision(session, cid) == rev_start

        await jobs.reserve_call(claim, clock())

        async with session_maker() as session:
            assert await world_tx.read_revision(session, cid) == rev_start

        prop = proposal(summary="Черновик без ревизии мира")
        await jobs.save_draft(claim, prop, clock())

        async with session_maker() as session:
            assert await world_tx.read_revision(session, cid) == rev_start

        claim_apply = await jobs.claim(clock())
        assert claim_apply is not None

        res = AdaptationResult(
            status="no_change",
            reason_code="evaluated_no_change",
        )
        await jobs.finish(claim_apply, res, clock())

        async with session_maker() as session:
            rev_end = await world_tx.read_revision(session, cid)
            assert rev_end == rev_start

    asyncio.run(_test())
