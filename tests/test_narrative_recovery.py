"""Recovery tests for director narrative jobs across process restarts (Task 14)."""

import asyncio
from typing import Any

import pytest
from sqlalchemy import select

from app.agents.master.service import MasterService
from app.core.narrative.contracts import (
    AdaptationProposal,
    AdaptationResult,
    NarrativeSnapshot,
    SnapshotRequest,
)
from app.core.narrative.service import NarrativeService
from app.db.models import NarrativeWork
from app.db.narrative_jobs import SqlNarrativeJobs
from app.db.session import make_sessionmaker
from tests.game import import_base, party
from tests.narrative_helpers import FakeClock, boundary, op, proposal, snapshot


@pytest.fixture
def session_maker(client):
    return make_sessionmaker(client.app.state.engine)


class DirectReader:
    def __init__(self, snap: NarrativeSnapshot) -> None:
        self.snap = snap

    async def snapshot(self, request: SnapshotRequest) -> NarrativeSnapshot:
        return self.snap


class DirectAuthor:
    def __init__(self, prop: AdaptationProposal) -> None:
        self.prop = prop
        self.calls = 0

    async def propose(self, snap: NarrativeSnapshot) -> AdaptationProposal:
        self.calls += 1
        return self.prop


class DirectApplier:
    def __init__(self, result: AdaptationResult) -> None:
        self.result = result
        self.calls = 0

    async def apply(self, prop: AdaptationProposal, *, claim: Any = None) -> AdaptationResult:
        self.calls += 1
        return self.result


def test_recovery_picks_up_expired_preparing_job(session_maker, settings, client, admin):
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    cid = c["id"]

    clock = FakeClock()
    jobs = SqlNarrativeJobs(session_maker, max_author_slots=2)

    snap = snapshot(
        source=snapshot().source.model_copy(update={"campaign_id": cid}),
        proposal_id="prop-recov-1",
    )
    prop = proposal(
        snap,
        summary="Восстановленная нить",
        operations=(op("develop_actor_role", entity_id=_hero["id"], new_role="Лидер"),),
    )

    reader = DirectReader(snap)
    author = DirectAuthor(prop)
    applier = DirectApplier(AdaptationResult(status="applied", reason_code="ok"))
    service = NarrativeService(reader, author, applier, jobs, clock)

    async def _test():
        # Enqueue job
        b = boundary(campaign_id=cid, source_id="src-recov-1")
        work_id = await jobs.enqueue(b)

        # Worker 1 claims job
        claim1 = await jobs.claim(clock())
        assert claim1 is not None
        assert claim1.phase == "author"

        # Worker 1 dies, lease expires
        clock.advance(200)

        # Service recovers and runs through author -> apply
        reports = await service.run_due(limit=5)
        assert len(reports) == 2
        assert reports[0].work_id == work_id
        assert reports[0].status == "prepared"
        assert reports[1].work_id == work_id
        assert reports[1].status == "applied"
        assert author.calls == 1

        async with session_maker() as session:
            work = await session.scalar(select(NarrativeWork).where(NarrativeWork.id == work_id))
            assert work is not None
            assert work.status == "applied"

    asyncio.run(_test())


def test_recovery_picks_up_prepared_job_without_reauthoring(session_maker, settings, client, admin):
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    cid = c["id"]

    clock = FakeClock()
    jobs = SqlNarrativeJobs(session_maker, max_author_slots=2)

    snap = snapshot(
        source=snapshot().source.model_copy(update={"campaign_id": cid}),
    )
    prop = proposal(
        snap,
        summary="Сохраненный черновик",
        operations=(op("develop_actor_role", entity_id=_hero["id"], new_role="Кузнец"),),
    )

    reader = DirectReader(snap)
    author = DirectAuthor(prop)
    applier = DirectApplier(AdaptationResult(status="applied", reason_code="ok"))
    service = NarrativeService(reader, author, applier, jobs, clock)

    async def _test():
        b = boundary(campaign_id=cid, source_id="src-prepared-recov")
        work_id = await jobs.enqueue(b)

        # Worker authors and saves draft, but dies before apply
        author_claim = await jobs.claim(clock())
        assert author_claim is not None
        await jobs.save_draft(author_claim, prop, clock())

        # Reset author calls counter
        author.calls = 0

        # Now service recovers and executes
        report = await service.prepare_once()
        assert report is not None
        assert report.work_id == work_id
        assert report.status == "applied"
        # Author was NOT called because draft was already prepared!
        assert author.calls == 0
        assert applier.calls == 1

    asyncio.run(_test())


def test_master_service_calls_narrative_preparer_in_recovery(client):
    maker = make_sessionmaker(client.app.state.engine)
    called = False

    class FakeNarrativePreparer:
        async def run_due(self, *, limit: int = 20):
            nonlocal called
            called = True
            return ()

    preparer = FakeNarrativePreparer()
    master_svc = MasterService(
        maker,
        client.app.state.bus,
        client.app.state.master.llm,
        narrative_preparer=preparer,
    )

    async def _test():
        await master_svc.recover(startup=True)
        assert called is True

    asyncio.run(_test())
