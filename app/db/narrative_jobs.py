"""Durable director job queue and lease manager (spec §15, Task 12)."""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.narrative.contracts import (
    AdaptationProposal,
    AdaptationResult,
    BoundaryRecord,
    EvidenceRef,
    LeaseLost,
    NarrativeSource,
    Violation,
    WorkClaim,
)
from app.core.narrative.keys import narrative_key
from app.db.models import Campaign, Event, NarrativeWork, new_id


def _as_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _evidence_refs(raw: list[dict] | None) -> tuple[EvidenceRef, ...]:
    """Deserialise evidence_refs from the JSON column into EvidenceRef objects."""
    if not raw:
        return ()
    return tuple(EvidenceRef.model_validate(r) for r in raw if isinstance(r, dict))


class SqlNarrativeJobs:
    """SQL storage for durable director work items, leases, and state transitions."""

    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        *,
        max_author_slots: int = 2,
    ) -> None:
        self._session_maker = session_maker
        self._max_author_slots = max_author_slots

    async def enqueue(self, boundary: BoundaryRecord) -> str:
        """Enqueues director work if not already present; returns job id."""
        async with self._session_maker() as session:
            existing_id = await session.scalar(
                select(NarrativeWork.id).where(
                    NarrativeWork.campaign_id == boundary.campaign_id,
                    NarrativeWork.source_key == boundary.source_key,
                )
            )
            if existing_id:
                return existing_id

            now_utc = datetime.now(UTC)
            work = NarrativeWork(
                campaign_id=boundary.campaign_id,
                source_key=boundary.source_key,
                scope=boundary.scope,
                kind=boundary.kind,
                source_id=boundary.source_id,
                audience=list(boundary.audience),
                focus=boundary.focus,
                session_budget_ref=boundary.session_budget_ref,
                policy_version=boundary.policy_version,
                evidence_refs=[ref.model_dump() for ref in boundary.evidence_refs],
                base={},
                proposal_id=new_id("prop"),
                draft=None,
                status="pending",
                created_at=now_utc,
                updated_at=now_utc,
            )
            session.add(work)
            try:
                await session.commit()
                return work.id
            except IntegrityError:
                await session.rollback()
                existing_id = await session.scalar(
                    select(NarrativeWork.id).where(
                        NarrativeWork.campaign_id == boundary.campaign_id,
                        NarrativeWork.source_key == boundary.source_key,
                    )
                )
                if existing_id:
                    return existing_id
                raise

    async def claim(self, now: datetime, *, campaign_id: str | None = None) -> WorkClaim | None:
        """Claims next available work item: prepared for apply, or pending/retry_wait for author."""
        now_utc = _as_utc(now)
        async with self._session_maker() as session:
            # 1. Maintenance: expire old leases
            expired_preparing = (
                await session.scalars(
                    select(NarrativeWork).where(
                        NarrativeWork.status == "preparing",
                        NarrativeWork.lease_until.is_not(None),
                        NarrativeWork.lease_until <= now_utc,
                    )
                )
            ).all()
            for work in expired_preparing:
                if work.attempts >= 6:
                    work.status = "rejected"
                else:
                    delays = [5, 15, 60]
                    delay = delays[min(max(work.attempts - 1, 0), len(delays) - 1)]
                    work.status = "retry_wait"
                    base_time = work.lease_until or now_utc
                    work.retry_after = base_time + timedelta(seconds=delay)
                work.capacity_slot = None
                work.lease_token = None
                work.lease_until = None
                work.updated_at = now_utc

            expired_prepared = (
                await session.scalars(
                    select(NarrativeWork).where(
                        NarrativeWork.status == "prepared",
                        NarrativeWork.lease_until.is_not(None),
                        NarrativeWork.lease_until <= now_utc,
                    )
                )
            ).all()
            for work in expired_prepared:
                work.lease_token = None
                work.lease_until = None
                work.updated_at = now_utc

            if expired_preparing or expired_prepared:
                await session.commit()

            # 2. Priority A: prepared jobs ready for apply phase
            apply_query = select(NarrativeWork).where(
                NarrativeWork.campaign_id.in_(select(Campaign.id).where(Campaign.purpose == "game")),
                NarrativeWork.status == "prepared",
                (NarrativeWork.lease_until.is_(None) | (NarrativeWork.lease_until <= now_utc)),
                (NarrativeWork.retry_after.is_(None) | (NarrativeWork.retry_after <= now_utc)),
            )
            if campaign_id is not None:
                apply_query = apply_query.where(NarrativeWork.campaign_id == campaign_id)
            apply_query = apply_query.order_by(NarrativeWork.created_at.asc()).limit(1)

            prepared_job = await session.scalar(apply_query)
            if prepared_job is not None:
                token = secrets.token_hex(16)
                lease_until = now_utc + timedelta(seconds=120)
                stmt = (
                    update(NarrativeWork)
                    .where(
                        NarrativeWork.id == prepared_job.id,
                        NarrativeWork.status == "prepared",
                        (NarrativeWork.lease_until.is_(None) | (NarrativeWork.lease_until <= now_utc)),
                    )
                    .values(
                        lease_token=token,
                        lease_until=lease_until,
                        updated_at=now_utc,
                    )
                )
                res = await session.execute(stmt)
                if res.rowcount == 1:
                    await session.commit()
                    draft_prop = None
                    if prepared_job.draft:
                        draft_prop = AdaptationProposal.model_validate(prepared_job.draft)

                    return WorkClaim(
                        work_id=prepared_job.id,
                        campaign_id=prepared_job.campaign_id,
                        source=NarrativeSource(
                            campaign_id=prepared_job.campaign_id,
                            scope=prepared_job.scope,  # type: ignore
                            source_kind="work",
                            source_id=prepared_job.id,  # stable work identity (R13)
                            stable_part=0,
                        ),
                        proposal_id=prepared_job.proposal_id,
                        lease_token=token,
                        lease_until=lease_until,
                        llm_calls=prepared_job.llm_calls,
                        attempts=prepared_job.attempts,
                        session_budget_ref=prepared_job.session_budget_ref,
                        phase="apply",
                        draft=draft_prop,
                        capacity_slot=None,
                        status="prepared",
                        evidence_refs=_evidence_refs(prepared_job.evidence_refs),
                        audience=tuple(prepared_job.audience or ()),
                        focus=prepared_job.focus,
                    )

            # 3. Priority B: author jobs (capacity slots 0..max_author_slots-1)
            taken_slots_rows = await session.scalars(
                select(NarrativeWork.capacity_slot).where(
                    NarrativeWork.status == "preparing",
                    NarrativeWork.capacity_slot.is_not(None),
                    NarrativeWork.lease_until > now_utc,
                )
            )
            taken_slots = set(taken_slots_rows.all())
            free_slots = [s for s in range(self._max_author_slots) if s not in taken_slots]
            if not free_slots:
                return None
            chosen_slot = free_slots[0]

            busy_campaigns_rows = await session.scalars(
                select(NarrativeWork.campaign_id).where(
                    NarrativeWork.status == "preparing",
                    NarrativeWork.lease_until > now_utc,
                )
            )
            busy_campaigns = set(busy_campaigns_rows.all())

            author_query = select(NarrativeWork).where(
                NarrativeWork.campaign_id.in_(select(Campaign.id).where(Campaign.purpose == "game")),
                NarrativeWork.status.in_(("pending", "retry_wait")),
                (NarrativeWork.lease_until.is_(None) | (NarrativeWork.lease_until <= now_utc)),
                (NarrativeWork.retry_after.is_(None) | (NarrativeWork.retry_after <= now_utc)),
            )
            if busy_campaigns:
                author_query = author_query.where(NarrativeWork.campaign_id.not_in(busy_campaigns))
            if campaign_id is not None:
                author_query = author_query.where(NarrativeWork.campaign_id == campaign_id)

            author_query = author_query.order_by(NarrativeWork.created_at.asc())
            candidates = (await session.scalars(author_query)).all()

            for candidate in candidates:
                if candidate.attempts >= 6:
                    candidate.status = "rejected"
                    candidate.capacity_slot = None
                    candidate.lease_token = None
                    candidate.lease_until = None
                    candidate.updated_at = now_utc
                    await session.commit()
                    continue

                token = secrets.token_hex(16)
                new_attempts = candidate.attempts + 1
                lease_until = now_utc + timedelta(seconds=120)

                stmt = (
                    update(NarrativeWork)
                    .where(
                        NarrativeWork.id == candidate.id,
                        NarrativeWork.status.in_(("pending", "retry_wait")),
                        (NarrativeWork.lease_until.is_(None) | (NarrativeWork.lease_until <= now_utc)),
                    )
                    .values(
                        status="preparing",
                        lease_token=token,
                        lease_until=lease_until,
                        capacity_slot=chosen_slot,
                        attempts=new_attempts,
                        retry_after=None,
                        updated_at=now_utc,
                    )
                )
                try:
                    res = await session.execute(stmt)
                    if res.rowcount == 1:
                        await session.commit()
                        feedback_items: tuple[Violation, ...] = ()
                        if candidate.draft and isinstance(candidate.draft.get("feedback"), list):
                            feedback_items = tuple(
                                Violation.model_validate(v) for v in candidate.draft["feedback"] if isinstance(v, dict)
                            )

                        return WorkClaim(
                            work_id=candidate.id,
                            campaign_id=candidate.campaign_id,
                            source=NarrativeSource(
                                campaign_id=candidate.campaign_id,
                                scope=candidate.scope,  # type: ignore
                                source_kind="work",
                                source_id=candidate.id,  # stable work identity (R13)
                                stable_part=0,
                            ),
                            proposal_id=candidate.proposal_id,
                            lease_token=token,
                            lease_until=lease_until,
                            llm_calls=candidate.llm_calls,
                            attempts=new_attempts,
                            session_budget_ref=candidate.session_budget_ref,
                            phase="author",
                            capacity_slot=chosen_slot,
                            status="preparing",
                            evidence_refs=_evidence_refs(candidate.evidence_refs),
                            audience=tuple(candidate.audience or ()),
                            focus=candidate.focus,
                            feedback=feedback_items,
                        )
                except IntegrityError:
                    await session.rollback()
                    return None

            return None

    async def reserve_call(self, claim: WorkClaim, now: datetime) -> WorkClaim | None:
        """Reserves an LLM call quota (max 2 per job). Returns updated claim or None if exhausted."""
        now_utc = _as_utc(now)
        async with self._session_maker() as session:
            stmt = (
                update(NarrativeWork)
                .where(
                    NarrativeWork.id == claim.work_id,
                    NarrativeWork.lease_token == claim.lease_token,
                    NarrativeWork.lease_until > now_utc,
                    NarrativeWork.llm_calls < 2,
                )
                .values(
                    llm_calls=NarrativeWork.llm_calls + 1,
                    updated_at=now_utc,
                )
            )
            res = await session.execute(stmt)
            if res.rowcount == 1:
                new_calls = await session.scalar(
                    select(NarrativeWork.llm_calls).where(NarrativeWork.id == claim.work_id)
                )
                await session.commit()
                return claim.model_copy(update={"llm_calls": new_calls})
            return None

    async def renew(self, claim: WorkClaim, now: datetime) -> bool:
        """Renews active lease if token matches and lease has not expired."""
        now_utc = _as_utc(now)
        new_lease_until = now_utc + timedelta(seconds=120)
        async with self._session_maker() as session:
            stmt = (
                update(NarrativeWork)
                .where(
                    NarrativeWork.id == claim.work_id,
                    NarrativeWork.lease_token == claim.lease_token,
                    NarrativeWork.lease_until > now_utc,
                )
                .values(
                    lease_until=new_lease_until,
                    updated_at=now_utc,
                )
            )
            res = await session.execute(stmt)
            if res.rowcount == 1:
                await session.commit()
                return True
            return False

    async def save_draft(
        self,
        claim: WorkClaim,
        proposal: AdaptationProposal,
        now: datetime | None = None,
    ) -> None:
        """Saves generated proposal as draft; transitions to prepared and frees capacity slot."""
        now_utc = _as_utc(now) if now is not None else datetime.now(UTC)
        async with self._session_maker() as session:
            stmt = (
                update(NarrativeWork)
                .where(
                    NarrativeWork.id == claim.work_id,
                    NarrativeWork.lease_token == claim.lease_token,
                    NarrativeWork.lease_until > now_utc,
                )
                .values(
                    draft=proposal.model_dump(),
                    base=proposal.base.model_dump(),
                    proposal_id=proposal.proposal_id,
                    status="prepared",
                    capacity_slot=None,
                    lease_token=None,
                    lease_until=None,
                    updated_at=now_utc,
                )
            )
            res = await session.execute(stmt)
            if res.rowcount != 1:
                raise LeaseLost(f"Lease lost or expired for job {claim.work_id}")
            await session.commit()

    async def finish(
        self,
        claim: WorkClaim,
        result: AdaptationResult,
        now: datetime | None = None,
        *,
        feedback: tuple[Violation, ...] | None = None,
    ) -> None:
        """Records terminal or retry status after applying adaptation."""
        now_utc = _as_utc(now) if now is not None else datetime.now(UTC)
        async with self._session_maker() as session:
            receipt_event_id = None
            if result.status in ("applied", "repeated", "no_change") and result.event_ids:
                receipt_event_id = await session.scalar(
                    select(Event.id).where(
                        Event.campaign_id == claim.campaign_id,
                        Event.tool == "adapt_story",
                        Event.idempotency_key == narrative_key(claim.source),
                        Event.id.in_(result.event_ids),
                    )
                )
                if receipt_event_id is None:
                    raise ValueError("adaptation parent receipt missing")
            draft_to_save: dict | None = None
            save_draft_explicitly = False

            if result.status in ("applied", "repeated"):
                new_status = "applied"
                retry_after = None
            elif result.status == "no_change":
                new_status = "no_change"
                retry_after = None
            elif result.status == "denied":
                if feedback and claim.llm_calls < 2:
                    new_status = "retry_wait"
                    retry_after = now_utc + timedelta(seconds=5)
                    draft_to_save = {"feedback": [v.model_dump() for v in feedback]}
                    save_draft_explicitly = True
                else:
                    new_status = "rejected"
                    retry_after = None
            elif result.status == "deferred":
                new_status = "prepared"
                retry_after = now_utc + timedelta(seconds=30)
            elif result.status in ("stale", "failed"):
                new_status = "retry_wait"
                retry_after = now_utc + timedelta(seconds=5)
                save_draft_explicitly = True
                draft_to_save = None
            else:
                new_status = "rejected"
                retry_after = None

            values_to_update: dict[str, Any] = {
                "status": new_status,
                "retry_after": retry_after,
                "receipt_event_id": receipt_event_id,
                "lease_token": None,
                "lease_until": None,
                "capacity_slot": None,
                "updated_at": now_utc,
            }
            if save_draft_explicitly:
                values_to_update["draft"] = draft_to_save

            stmt = (
                update(NarrativeWork)
                .where(
                    NarrativeWork.id == claim.work_id,
                    NarrativeWork.lease_token == claim.lease_token,
                )
                .values(**values_to_update)
            )
            res = await session.execute(stmt)
            if res.rowcount != 1:
                raise LeaseLost(f"Lease lost or token mismatch for job {claim.work_id}")
            await session.commit()

    async def resnapshot(self, claim: WorkClaim, now: datetime) -> WorkClaim | None:
        """Allocates a fresh proposal attempt on world collision (max 1 resnapshot per job)."""
        now_utc = _as_utc(now)
        new_prop_id = new_id("prop")
        async with self._session_maker() as session:
            stmt = (
                update(NarrativeWork)
                .where(
                    NarrativeWork.id == claim.work_id,
                    NarrativeWork.lease_token == claim.lease_token,
                    NarrativeWork.lease_until > now_utc,
                    NarrativeWork.resnapshots < 1,
                )
                .values(
                    resnapshots=NarrativeWork.resnapshots + 1,
                    proposal_id=new_prop_id,
                    updated_at=now_utc,
                )
            )
            res = await session.execute(stmt)
            if res.rowcount == 1:
                await session.commit()
                return claim.model_copy(update={"proposal_id": new_prop_id})
            return None
