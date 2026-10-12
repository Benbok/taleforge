"""Narrative orchestration service across ports (spec §11, §15, Task 14)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.core.narrative.contracts import (
    AdaptationResult,
    PreparationReport,
    SnapshotRequest,
)
from app.core.narrative.ports import (
    NarrativeApplier,
    NarrativeAuthor,
    NarrativeJobs,
    NarrativeReader,
)


class NarrativeService:
    """Orchestrates director narrative workflows through injectable ports.

    Pure domain orchestrator: does not directly import DB, ORM, LLM or tools.
    """

    def __init__(
        self,
        reader: NarrativeReader,
        author: NarrativeAuthor,
        applier: NarrativeApplier,
        jobs: NarrativeJobs,
        clock: Callable[[], datetime],
    ) -> None:
        self._reader = reader
        self._author = author
        self._applier = applier
        self._jobs = jobs
        self._clock = clock

    async def prepare_once(self) -> PreparationReport | None:
        """Executes a single director work unit.

        Returns PreparationReport or None if queue is idle.
        """
        now = self._clock()
        claim = await self._jobs.claim(now)
        if claim is None:
            return None

        if claim.phase == "author":
            # 1. Assemble snapshot
            req = SnapshotRequest(
                source=claim.source,
                focus=None,
                audience=(),
                evidence_refs=(),
                mutable_subject_refs=(),
                feedback=(),
            )
            snapshot = await self._reader.snapshot(req)

            # 2. Reserve LLM call quota before invoking model
            reserved = await self._jobs.reserve_call(claim, now)
            if reserved is None:
                # LLM call budget exhausted
                result = AdaptationResult(
                    status="denied",
                    reason_code="call_budget_exhausted",
                )
                await self._jobs.finish(claim, result, now)
                return PreparationReport(
                    work_id=claim.work_id,
                    status="rejected",
                    reason_code="call_budget_exhausted",
                    calls_reserved=claim.llm_calls,
                )

            # 3. Author proposal
            snapshot = snapshot.model_copy(update={"author_attempt": reserved.llm_calls})
            proposal = await self._author.propose(snapshot)

            # 4. Handle no_change
            if len(proposal.operations) == 0:
                result = AdaptationResult(
                    status="no_change",
                    reason_code="no_change",
                )
                await self._jobs.finish(reserved, result, now)
                return PreparationReport(
                    work_id=claim.work_id,
                    status="no_change",
                    reason_code="no_change",
                    calls_reserved=reserved.llm_calls,
                )

            # 5. Save draft -> prepared
            await self._jobs.save_draft(reserved, proposal, now)

            # 6. Immediately attempt apply phase
            apply_claim = await self._jobs.claim(now)
            if apply_claim is not None and apply_claim.phase == "apply":
                app_result = await self._applier.apply(proposal)
                await self._jobs.finish(apply_claim, app_result, now)
                return PreparationReport(
                    work_id=claim.work_id,
                    status=app_result.status,
                    reason_code=app_result.reason_code,
                    calls_reserved=reserved.llm_calls,
                )

            return PreparationReport(
                work_id=claim.work_id,
                status="prepared",
                reason_code="draft_saved",
                calls_reserved=reserved.llm_calls,
            )

        elif claim.phase == "apply":
            if claim.draft is None:
                res = AdaptationResult(status="failed", reason_code="missing_draft")
                await self._jobs.finish(claim, res, now)
                return PreparationReport(
                    work_id=claim.work_id,
                    status="failed",
                    reason_code="missing_draft",
                    calls_reserved=claim.llm_calls,
                )

            res = await self._applier.apply(claim.draft)
            await self._jobs.finish(claim, res, now)
            return PreparationReport(
                work_id=claim.work_id,
                status=res.status,
                reason_code=res.reason_code,
                calls_reserved=claim.llm_calls,
            )

        return None

    async def run_due(self, *, limit: int = 20) -> tuple[PreparationReport, ...]:
        """Runs due background director tasks up to limit."""
        reports: list[PreparationReport] = []
        for _ in range(limit):
            report = await self.prepare_once()
            if report is None:
                break
            reports.append(report)
        return tuple(reports)
