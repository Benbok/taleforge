"""Narrative orchestration service across ports (spec §11, §15, Task 14)."""

from __future__ import annotations

import logging
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

log = logging.getLogger(__name__)

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

        stage = "snapshot"
        pending_finish: tuple[AdaptationResult, PreparationReport, tuple[Violation, ...] | None] | None = None

        async def finish(
            result: AdaptationResult,
            report: PreparationReport,
            *,
            feedback: tuple[Violation, ...] | None = None,
        ) -> PreparationReport:
            nonlocal stage, pending_finish
            stage = "finish"
            pending_finish = (result, report, feedback)
            await self._jobs.finish(claim, result, self._clock(), feedback=feedback)
            return report

        try:
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
                stage = "reserve_call"
                reserved = await self._jobs.reserve_call(claim, now)
                if reserved is None:
                    result = AdaptationResult(
                        status="denied",
                        reason_code="call_budget_exhausted",
                    )
                    return await finish(
                        result,
                        PreparationReport(
                            work_id=claim.work_id,
                            status="rejected",
                            reason_code="call_budget_exhausted",
                            calls_reserved=claim.llm_calls,
                        ),
                    )

                claim = reserved
                stage = "renew"
                if not await self._jobs.renew(claim, self._clock()):
                    raise LeaseLost("lease renewal denied")

                # 3. Author proposal
                snapshot = snapshot.model_copy(update={"author_attempt": reserved.llm_calls})
                stage = "author"
                proposal = await self._author.propose(snapshot)

                # 4. Save draft -> prepared (R12: both normal operations and no_change return prepared)
                now = self._clock()
                stage = "save_draft"
                await self._jobs.save_draft(claim, proposal, now)

                return PreparationReport(
                    work_id=claim.work_id,
                    status="prepared",
                    reason_code="draft_saved",
                    calls_reserved=reserved.llm_calls,
                )

            elif claim.phase == "apply":
                if claim.draft is None:
                    res = AdaptationResult(status="failed", reason_code="missing_draft")
                    return await finish(
                        res,
                        PreparationReport(
                            work_id=claim.work_id,
                            status="failed",
                            reason_code="missing_draft",
                            calls_reserved=claim.llm_calls,
                        ),
                    )

                stage = "renew"
                if not await self._jobs.renew(claim, self._clock()):
                    raise LeaseLost("lease renewal denied")

                stage = "apply"
                res = await self._applier.apply(claim.draft, claim=claim)

                now = self._clock()

                if res.status == "stale":
                    # Stale read set collision: allow max 1 resnapshot attempt
                    stage = "resnapshot"
                    resnap = await self._jobs.resnapshot(claim, now)
                    if resnap is not None:
                        return await finish(
                            res,
                            PreparationReport(
                                work_id=claim.work_id,
                                status="retry_wait",
                                reason_code="stale_resnapshot",
                                calls_reserved=claim.llm_calls,
                            ),
                        )
                    else:
                        denied_res = AdaptationResult(
                            status="denied",
                            reason_code="conflict_limit_exceeded",
                        )
                        return await finish(
                            denied_res,
                            PreparationReport(
                                work_id=claim.work_id,
                                status="rejected",
                                reason_code="conflict_limit_exceeded",
                                calls_reserved=claim.llm_calls,
                            ),
                        )

                if res.status == "denied":
                    # Check for model-correctable denial (max 2 calls) with feedback
                    if res.reason_code not in NON_CORRECTABLE_DENIALS and claim.llm_calls < 2:
                        fb = (Violation(code=res.reason_code),)
                        return await finish(
                            res,
                            PreparationReport(
                                work_id=claim.work_id,
                                status="retry_wait",
                                reason_code=f"correctable_denial: {res.reason_code}",
                                calls_reserved=claim.llm_calls,
                            ),
                            feedback=fb,
                        )

                return await finish(
                    res,
                    PreparationReport(
                        work_id=claim.work_id,
                        status=res.status,
                        reason_code=res.reason_code,
                        calls_reserved=claim.llm_calls,
                    ),
                )

            return None

        except LeaseLost:
            return PreparationReport(
                work_id=claim.work_id,
                status="failed",
                reason_code="lease_lost",
                calls_reserved=claim.llm_calls,
            )
        except Exception as exc:
            # Never copy provider/SQL exception text or traceback into reports/logs.
            log.warning("narrative work %s stage %s failed (%s)", claim.work_id, stage, type(exc).__name__)
            reason_code = f"{stage}_error"
            try:
                if stage == "finish" and pending_finish is not None:
                    result, report, feedback = pending_finish
                    # Finalization failure must preserve an already committed outcome.
                    await self._jobs.finish(claim, result, self._clock(), feedback=feedback)
                    return report
                await self._jobs.finish(
                    claim,
                    AdaptationResult(status="failed", reason_code=reason_code),
                    self._clock(),
                )
            except LeaseLost:
                reason_code = "lease_lost"
            except Exception as finish_exc:
                # Storage is unavailable: lease expiry remains the recovery path.
                log.warning("narrative work %s failure recording failed (%s)", claim.work_id, type(finish_exc).__name__)
                reason_code = "failure_recording_error"
            return PreparationReport(
                work_id=claim.work_id,
                status="failed",
                reason_code=reason_code,
                calls_reserved=claim.llm_calls,
            )

    async def run_due(self, *, limit: int = 20) -> tuple[PreparationReport, ...]:
        """Runs due background director tasks up to limit with batch failure isolation (R15)."""
        reports: list[PreparationReport] = []
        for _ in range(limit):
            try:
                report = await self.prepare_once()
            except Exception as exc:
                log.warning("narrative batch claim failed (%s)", type(exc).__name__)
                # Failure of one campaign does not break batch processing of remaining items
                reports.append(
                    PreparationReport(
                        work_id="unknown",
                        status="failed",
                        reason_code="batch_error",
                    )
                )
                continue

            if report is None:
                break
            reports.append(report)
        return tuple(reports)
