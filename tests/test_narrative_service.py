"""Tests for NarrativeService orchestration with isolated ports (Task 14)."""

import asyncio
from datetime import datetime
from typing import Any

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
        self.last_request: SnapshotRequest | None = None

    async def snapshot(self, request: SnapshotRequest) -> NarrativeSnapshot:
        self.calls += 1
        self.last_request = request
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
        self.last_claim: WorkClaim | None = None

    async def apply(
        self, proposal: AdaptationProposal, *, claim: WorkClaim | None = None
    ) -> AdaptationResult:
        self.calls += 1
        self.last_proposal = proposal
        self.last_claim = claim
        return self.result


class FakeJobs:
    def __init__(self, claim_sequence: list[WorkClaim | None] | None = None) -> None:
        self._claims = list(claim_sequence or [])
        self.saved_drafts: list[AdaptationProposal] = []
        self.finished_results: list[AdaptationResult] = []
        self.finished_feedbacks: list[Any] = []
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
        self,
        claim: WorkClaim,
        result: AdaptationResult,
        now: datetime | None = None,
        *,
        feedback: tuple[Any, ...] | None = None,
    ) -> None:
        self.finished_results.append(result)
        self.finished_feedbacks.append(feedback)

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
        # Step 1: author phase generates proposal and saves draft
        rep1 = await service.prepare_once()
        assert rep1 is not None
        assert rep1.status == "prepared"
        assert rep1.reason_code == "draft_saved"
        assert author.calls == 1
        assert applier.calls == 0
        assert len(jobs.saved_drafts) == 1

        # Step 2: apply phase applies saved draft
        rep2 = await service.prepare_once()
        assert rep2 is not None
        assert rep2.status == "applied"
        assert rep2.reason_code == "ok"
        assert author.calls == 1
        assert applier.calls == 1
        assert applier.last_claim == apply_claim
        assert len(jobs.finished_results) == 1

    asyncio.run(_test())


def test_service_handles_no_change_with_receipt():
    """R12/R14: no_change passes through apply and receives a durable receipt."""
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
    apply_claim = WorkClaim(
        work_id="work-no-change",
        campaign_id="camp-1",
        source=snap.source,
        proposal_id=snap.proposal_id,
        lease_token="lease-2",
        lease_until=clock(),
        session_budget_ref="sess-1",
        phase="apply",
        draft=no_change_prop,
    )
    jobs = FakeJobs([author_claim, apply_claim])
    reader = FakeReader(snap)
    author = FakeAuthor(no_change_prop)
    applier = FakeApplier(
        AdaptationResult(
            status="no_change",
            reason_code="no_change",
            event_ids=("receipt-ev-nc",),
        )
    )

    service = NarrativeService(reader, author, applier, jobs, clock)

    async def _test():
        reports = await service.run_due(limit=10)
        assert len(reports) == 2
        assert reports[0].status == "prepared"
        assert reports[1].status == "no_change"
        assert author.calls == 1
        assert applier.calls == 1
        assert len(jobs.finished_results) == 1
        assert jobs.finished_results[0].status == "no_change"
        assert jobs.finished_results[0].event_ids == ("receipt-ev-nc",)

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
        assert reports[0].status == "prepared"
        assert reports[1].work_id == "w-2"
        assert reports[1].status == "prepared"

    asyncio.run(_test())


# ──────────────────────────────────────────────────────────────────────────────
# F7 / R11 — service builds SnapshotRequest from claim, not empty defaults
# ──────────────────────────────────────────────────────────────────────────────

def test_snapshot_request_built_from_claim_context():
    """R11: service.prepare_once must pass evidence/audience/focus from claim to reader.

    Before the fix, service.py hardcoded empty tuples. After the fix, the
    SnapshotRequest the reader receives must exactly reflect the claim fields.
    """
    from app.core.narrative.contracts import EvidenceRef

    clock = FakeClock()
    snap = snapshot()

    ev = EvidenceRef(campaign_id="camp-1", kind="event", source_id="evt-99")
    author_claim = WorkClaim(
        work_id="work-ctx-test",
        campaign_id="camp-1",
        source=snap.source,
        proposal_id=snap.proposal_id,
        lease_token="lease-ctx",
        lease_until=clock(),
        session_budget_ref="sess-ctx",
        phase="author",
        # Boundary context that must reach the reader
        evidence_refs=(ev,),
        audience=("hero-a", "hero-b"),
        focus="dungeon-entrance",
    )
    jobs = FakeJobs([author_claim])
    reader = FakeReader(snap)
    author = FakeAuthor(proposal(snap, operations=()))
    applier = FakeApplier()

    service = NarrativeService(reader, author, applier, jobs, clock)

    async def _test():
        report = await service.prepare_once()
        assert report is not None
        assert report.status == "prepared"

        req = reader.last_request
        assert req is not None, "reader.snapshot was never called"
        assert req.evidence_refs == (ev,), "evidence_refs not passed to SnapshotRequest"
        assert req.audience == ("hero-a", "hero-b"), "audience not passed"
        assert req.focus == "dungeon-entrance", "focus not passed"

    asyncio.run(_test())


# ──────────────────────────────────────────────────────────────────────────────
# F8 / R15 — batch processing isolates author errors across campaigns
# ──────────────────────────────────────────────────────────────────────────────

def test_batch_isolates_author_error_and_allows_subsequent_campaign():
    """R15: Failure in campaign 1 must not abort the batch for campaign 2."""
    clock = FakeClock()
    snap1 = snapshot(source=snapshot().source.model_copy(update={"campaign_id": "c-1"}))
    snap2 = snapshot(source=snapshot().source.model_copy(update={"campaign_id": "c-2"}))

    claim1 = WorkClaim(
        work_id="w-err",
        campaign_id="c-1",
        source=snap1.source,
        proposal_id="p-1",
        lease_token="l-1",
        lease_until=clock(),
        session_budget_ref="sess-1",
        phase="author",
    )
    claim2 = WorkClaim(
        work_id="w-ok",
        campaign_id="c-2",
        source=snap2.source,
        proposal_id="p-2",
        lease_token="l-2",
        lease_until=clock(),
        session_budget_ref="sess-2",
        phase="author",
    )
    jobs = FakeJobs([claim1, claim2])

    class DynamicReader:
        async def snapshot(self, req: SnapshotRequest):
            return snapshot(source=req.source)

    reader = DynamicReader()

    class FlakyAuthor:
        def __init__(self):
            self.calls = 0

        async def propose(self, snap: NarrativeSnapshot):
            self.calls += 1
            if snap.source.campaign_id == "c-1":
                raise RuntimeError("LLM gateway 503 error on c-1")
            return proposal(snap, operations=())

    author = FlakyAuthor()
    applier = FakeApplier()
    service = NarrativeService(reader, author, applier, jobs, clock)

    async def _test():
        reports = await service.run_due(limit=10)
        assert len(reports) == 2
        # Campaign 1 failed gracefully and was recorded
        assert reports[0].work_id == "w-err"
        assert reports[0].status == "failed"
        assert "503" in reports[0].reason_code
        # Campaign 2 succeeded despite campaign 1 failure!
        assert reports[1].work_id == "w-ok"
        assert reports[1].status == "prepared"

    asyncio.run(_test())


# ──────────────────────────────────────────────────────────────────────────────
# F8 — stale conflict triggers 1 resnapshot, second stale is rejected
# ──────────────────────────────────────────────────────────────────────────────

def test_stale_triggers_one_resnapshot_then_terminal_rejection():
    """F8: 1st stale read set collision triggers resnapshot; 2nd stale is rejected."""
    clock = FakeClock()
    snap = snapshot()
    prop = proposal(snap, operations=(op("develop_actor_role", entity_id="npc-1", new_role="Лидер"),))

    claim_apply = WorkClaim(
        work_id="w-stale",
        campaign_id="camp-1",
        source=snap.source,
        proposal_id=snap.proposal_id,
        lease_token="l-stale",
        lease_until=clock(),
        session_budget_ref="sess-1",
        phase="apply",
        draft=prop,
    )

    class ResnapshotCountingJobs(FakeJobs):
        def __init__(self, claims):
            super().__init__(claims)
            self.resnap_count = 0

        async def resnapshot(self, claim: WorkClaim, now: datetime) -> WorkClaim | None:
            if self.resnap_count >= 1:
                return None
            self.resnap_count += 1
            return claim.model_copy(update={"proposal_id": f"new-prop-{self.resnap_count}"})

    jobs = ResnapshotCountingJobs([claim_apply, claim_apply])
    reader = FakeReader(snap)
    author = FakeAuthor(prop)
    applier = FakeApplier(AdaptationResult(status="stale", reason_code="stale_read_set"))

    service = NarrativeService(reader, author, applier, jobs, clock)

    async def _test():
        # First stale: resnapshot succeeds, report status is retry_wait
        rep1 = await service.prepare_once()
        assert rep1 is not None
        assert rep1.status == "retry_wait"
        assert rep1.reason_code == "stale_resnapshot"

        # Second stale: resnapshot limit reached -> rejected with conflict_limit_exceeded
        rep2 = await service.prepare_once()
        assert rep2 is not None
        assert rep2.status == "rejected"
        assert rep2.reason_code == "conflict_limit_exceeded"

    asyncio.run(_test())


# ──────────────────────────────────────────────────────────────────────────────
# F8 — model-correctable denial persists feedback for next attempt
# ──────────────────────────────────────────────────────────────────────────────

def test_model_correctable_denial_persists_feedback_and_reschedules():
    """F8: A correctable denial (novelty_exceeded) passes feedback into jobs.finish."""
    clock = FakeClock()
    snap = snapshot()
    prop = proposal(snap, operations=(op("develop_actor_role", entity_id="npc-1", new_role="Лидер"),))

    claim_apply = WorkClaim(
        work_id="w-correctable",
        campaign_id="camp-1",
        source=snap.source,
        proposal_id=snap.proposal_id,
        lease_token="l-corr",
        lease_until=clock(),
        session_budget_ref="sess-1",
        phase="apply",
        draft=prop,
        llm_calls=1,  # 1 call used, 1 remaining
    )

    jobs = FakeJobs([claim_apply])
    reader = FakeReader(snap)
    author = FakeAuthor(prop)
    applier = FakeApplier(AdaptationResult(status="denied", reason_code="scene_novelty_exceeded"))

    service = NarrativeService(reader, author, applier, jobs, clock)

    async def _test():
        rep = await service.prepare_once()
        assert rep is not None
        assert rep.status == "retry_wait"
        assert "scene_novelty_exceeded" in rep.reason_code

        # Feedback was passed to jobs.finish
        assert len(jobs.finished_feedbacks) == 1
        fb = jobs.finished_feedbacks[0]
        assert fb is not None
        assert len(fb) == 1
        assert fb[0].code == "scene_novelty_exceeded"

    asyncio.run(_test())
