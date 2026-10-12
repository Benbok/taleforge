"""Tests for NarrativeService orchestration with isolated ports (Task 14)."""

import asyncio
from datetime import datetime

from app.core.narrative.contracts import (
    AdaptationProposal,
    AdaptationResult,
    NarrativeSnapshot,
    PreparationReport,
    SnapshotRequest,
    WorkClaim,
)
from app.core.narrative.service import NarrativeService
from tests.narrative_helpers import FakeClock, op, proposal, snapshot


class FakeReader:
    def __init__(self, snap: NarrativeSnapshot | None = None) -> None:
        self.snap = snap or snapshot()
        self.calls = 0

    async def snapshot(self, request: SnapshotRequest) -> NarrativeSnapshot:
        self.calls += 1
        return self.snap


class FakeAuthor:
    def __init__(self, prop: AdaptationProposal | None = None) -> None:
        self.prop = prop
        self.calls = 0

    async def propose(self, snapshot: NarrativeSnapshot) -> AdaptationProposal:
        self.calls += 1
        return self.prop if self.prop is not None else proposal(snapshot)


class FakeApplier:
    def __init__(self, result: AdaptationResult | None = None) -> None:
        self.result = result or AdaptationResult(status="applied", reason_code="ok")
        self.calls = 0
        self.last_proposal: AdaptationProposal | None = None

    async def apply(self, proposal: AdaptationProposal) -> AdaptationResult:
        self.calls += 1
        self.last_proposal = proposal
        return self.result


class FakeJobs:
    def __init__(self, claim_sequence: list[WorkClaim | None] | None = None) -> None:
        self._claims = list(claim_sequence or [])
        self.saved_drafts: list[AdaptationProposal] = []
        self.finished_results: list[AdaptationResult] = []
        self.reserved_calls = 0
        self.saved_draft_unchanged = True

    async def claim(self, now: datetime, *, campaign_id: str | None = None) -> WorkClaim | None:
        if self._claims:
            return self._claims.pop(0)
        return None

    async def reserve_call(self, claim: WorkClaim, now: datetime) -> WorkClaim | None:
        if claim.llm_calls >= 2:
            return None
        self.reserved_calls += 1
        return claim.model_copy(update={"llm_calls": claim.llm_calls + 1})

    async def renew(self, claim: WorkClaim, now: datetime) -> bool:
        return True

    async def save_draft(
        self, claim: WorkClaim, prop: AdaptationProposal, now: datetime | None = None
    ) -> None:
        self.saved_drafts.append(prop)
        self.saved_draft_unchanged = False

    async def finish(
        self, claim: WorkClaim, result: AdaptationResult, now: datetime | None = None
    ) -> None:
        self.finished_results.append(result)

    async def resnapshot(self, claim: WorkClaim, now: datetime) -> WorkClaim | None:
        return claim.model_copy(update={"proposal_id": "new-prop"})


def prepared_service_fixture(pending_narration: bool = False):
    clock = FakeClock()
    draft_prop = proposal(
        summary="Подготовленный черновик",
        operations=(op("develop_actor_role", entity_id="npc-1", new_role="Лидер"),),
    )
    apply_claim = WorkClaim(
        work_id="work-prepared-1",
        campaign_id="camp-1",
        source=draft_prop.source,
        proposal_id=draft_prop.proposal_id,
        lease_token="lease-token-1",
        lease_until=clock(),
        session_budget_ref="sess-1",
        phase="apply",
        draft=draft_prop,
        status="prepared",
    )
    jobs = FakeJobs([apply_claim])
    reader = FakeReader()
    author = FakeAuthor()
    applier = FakeApplier(
        result=AdaptationResult(status="deferred", reason_code="pending_narration" if pending_narration else "combat")
    )
    service = NarrativeService(reader, author, applier, jobs, clock)
    return service, author, jobs


def run_service_once(service: NarrativeService) -> PreparationReport:
    return asyncio.run(service.prepare_once())


def test_prepared_deferred_work_does_not_call_author_again():
    service, author, jobs = prepared_service_fixture(pending_narration=True)
    report = run_service_once(service)
    assert report.status == "deferred"
    assert author.calls == 0
    assert jobs.saved_draft_unchanged


def test_service_author_and_apply_flow():
    clock = FakeClock()
    snap = snapshot()
    prop = proposal(
        snap,
        summary="Новый мотив",
        operations=(op("develop_actor_role", entity_id="npc-1", new_role="Вождь"),),
    )
    author_claim = WorkClaim(
        work_id="work-1",
        campaign_id="camp-1",
        source=snap.source,
        proposal_id=snap.proposal_id,
        lease_token="lease-1",
        lease_until=clock(),
        session_budget_ref="sess-1",
        phase="author",
    )
    apply_claim = WorkClaim(
        work_id="work-1",
        campaign_id="camp-1",
        source=snap.source,
        proposal_id=snap.proposal_id,
        lease_token="lease-2",
        lease_until=clock(),
        session_budget_ref="sess-1",
        phase="apply",
        draft=prop,
    )
    jobs = FakeJobs([author_claim, apply_claim])
    reader = FakeReader(snap)
    author = FakeAuthor(prop)
    applier = FakeApplier(AdaptationResult(status="applied", reason_code="ok"))

    service = NarrativeService(reader, author, applier, jobs, clock)

    async def _test():
        report = await service.prepare_once()
        assert report is not None
        assert report.status == "applied"
        assert report.reason_code == "ok"
        assert author.calls == 1
        assert applier.calls == 1
        assert len(jobs.saved_drafts) == 1
        assert len(jobs.finished_results) == 1

    asyncio.run(_test())


def test_service_handles_no_change_without_calling_applier():
    clock = FakeClock()
    snap = snapshot()
    no_change_prop = proposal(snap, summary="Изменений нет", operations=())
    author_claim = WorkClaim(
        work_id="work-no-change",
        campaign_id="camp-1",
        source=snap.source,
        proposal_id=snap.proposal_id,
        lease_token="lease-1",
        lease_until=clock(),
        session_budget_ref="sess-1",
        phase="author",
    )
    jobs = FakeJobs([author_claim])
    reader = FakeReader(snap)
    author = FakeAuthor(no_change_prop)
    applier = FakeApplier()

    service = NarrativeService(reader, author, applier, jobs, clock)

    async def _test():
        report = await service.prepare_once()
        assert report is not None
        assert report.status == "no_change"
        assert report.reason_code == "no_change"
        assert author.calls == 1
        assert applier.calls == 0
        assert len(jobs.finished_results) == 1
        assert jobs.finished_results[0].status == "no_change"

    asyncio.run(_test())


def test_service_run_due_batches():
    clock = FakeClock()
    snap = snapshot()
    no_change_prop = proposal(snap, operations=())
    claim1 = WorkClaim(
        work_id="w-1",
        campaign_id="camp-1",
        source=snap.source,
        proposal_id="p1",
        lease_token="l1",
        lease_until=clock(),
        session_budget_ref="sess-1",
        phase="author",
    )
    claim2 = WorkClaim(
        work_id="w-2",
        campaign_id="camp-1",
        source=snap.source,
        proposal_id="p2",
        lease_token="l2",
        lease_until=clock(),
        session_budget_ref="sess-1",
        phase="author",
    )
    jobs = FakeJobs([claim1, claim2])
    reader = FakeReader(snap)
    author = FakeAuthor(no_change_prop)
    applier = FakeApplier()

    service = NarrativeService(reader, author, applier, jobs, clock)

    async def _test():
        reports = await service.run_due(limit=10)
        assert len(reports) == 2
        assert reports[0].work_id == "w-1"
        assert reports[1].work_id == "w-2"

    asyncio.run(_test())
