"""Narrative orchestration service across ports (spec §11, §15, Task 14)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from app.core.narrative.contracts import (
    AdaptationResult,
    LeaseLost,
    PreparationReport,
    SnapshotRequest,
    Violation,
)
from app.core.narrative.ports import (
    NarrativeApplier,
    NarrativeAuthor,
    NarrativeJobs,
    NarrativeReader,
)

NON_CORRECTABLE_DENIALS: frozenset[str] = frozenset(
    {
        "campaign_boundary_violation",
        "internal_tool_denied",
        "internal_tool_unauthorized",
        "unknown_source",
        "proposal_id_mismatch",
        "source_mismatch",
        "policy_strict_mode",
        "strict_mode_active",
        "unsupported_schema_version",
        "call_budget_exhausted",
        "conflict_limit_exceeded",
        "security_denial",
        "nonlocal_effect_denied",
        "missing_draft",
    }
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

    async def prepare_once(self, campaign_id: str | None = None) -> PreparationReport | None:
        """Executes a single director work unit.

        Returns PreparationReport or None if queue is idle.
        """
        now = self._clock()
        claim = await self._jobs.claim(now, campaign_id=campaign_id)
        if claim is None:
            return None

        if claim.phase == "author":
            # 1. Assemble snapshot from saved boundary context (R11)
            req = SnapshotRequest(
                source=claim.source,
                focus=claim.focus,
                audience=claim.audience,
                evidence_refs=claim.evidence_refs,
                mutable_subject_refs=claim.mutable_subject_refs,
                feedback=claim.feedback,
            )
            snapshot = await self._reader.snapshot(req)

            # 2. Reserve LLM call quota before invoking model
            now = self._clock()
            reserved = await self._jobs.reserve_call(claim, now)
            if reserved is None:
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

            # Heartbeat lease renewal
            await self._jobs.renew(reserved, now)

            # 3. Author proposal
            snapshot = snapshot.model_copy(update={"author_attempt": reserved.llm_calls})
            try:
                proposal = await self._author.propose(snapshot)
            except Exception as e:
                now = self._clock()
                result = AdaptationResult(
                    status="failed",
                    reason_code=f"author_error: {e}",
                )
                await self._jobs.finish(reserved, result, now)
                return PreparationReport(
                    work_id=claim.work_id,
                    status="failed",
                    reason_code=f"author_error: {e}",
                    calls_reserved=reserved.llm_calls,
                )

            # 4. Save draft -> prepared (R12: both normal operations and no_change return prepared)
            now = self._clock()
            await self._jobs.save_draft(reserved, proposal, now)

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

            # Heartbeat lease renewal
            await self._jobs.renew(claim, now)

            try:
                res = await self._applier.apply(claim.draft, claim=claim)
            except LeaseLost:
                # Expired or superseded lease: world was not written, abort cleanly
                return PreparationReport(
                    work_id=claim.work_id,
                    status="failed",
                    reason_code="lease_lost",
                    calls_reserved=claim.llm_calls,
                )
            except Exception as e:
                now = self._clock()
                res = AdaptationResult(status="failed", reason_code=f"apply_error: {e}")

            now = self._clock()

            if res.status == "stale":
                # Stale read set collision: allow max 1 resnapshot attempt
                resnap = await self._jobs.resnapshot(claim, now)
                if resnap is not None:
                    await self._jobs.finish(claim, res, now)
                    return PreparationReport(
                        work_id=claim.work_id,
                        status="retry_wait",
                        reason_code="stale_resnapshot",
                        calls_reserved=claim.llm_calls,
                    )
                else:
                    denied_res = AdaptationResult(
                        status="denied",
                        reason_code="conflict_limit_exceeded",
                    )
                    await self._jobs.finish(claim, denied_res, now)
                    return PreparationReport(
                        work_id=claim.work_id,
                        status="rejected",
                        reason_code="conflict_limit_exceeded",
                        calls_reserved=claim.llm_calls,
                    )

            if res.status == "denied":
                # Check for model-correctable denial (max 2 calls) with feedback
                if res.reason_code not in NON_CORRECTABLE_DENIALS and claim.llm_calls < 2:
                    fb = (Violation(code=res.reason_code),)
                    await self._jobs.finish(claim, res, now, feedback=fb)
                    return PreparationReport(
                        work_id=claim.work_id,
                        status="retry_wait",
                        reason_code=f"correctable_denial: {res.reason_code}",
                        calls_reserved=claim.llm_calls,
                    )

            await self._jobs.finish(claim, res, now)
            return PreparationReport(
                work_id=claim.work_id,
                status=res.status,
                reason_code=res.reason_code,
                calls_reserved=claim.llm_calls,
            )

        return None

    async def run_due(self, *, limit: int = 20) -> tuple[PreparationReport, ...]:
        """Runs due background director tasks up to limit with batch failure isolation (R15)."""
        reports: list[PreparationReport] = []
        for _ in range(limit):
            try:
                report = await self.prepare_once()
            except Exception as e:
                # Failure of one campaign does not break batch processing of remaining items
                reports.append(
                    PreparationReport(
                        work_id="unknown",
                        status="failed",
                        reason_code=f"batch_error: {e}",
                    )
                )
                continue

            if report is None:
                break
            reports.append(report)
        return tuple(reports)
