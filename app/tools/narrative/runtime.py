"""Runtime implementation of NarrativeApplier port (Task 14)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.narrative.contracts import (
    AdaptationProposal,
    AdaptationResult,
    LeaseLost,
    NarrativePolicy,
    WorkClaim,
)
from app.db.models import Campaign, NarrativeWork, as_utc
from app.rules.dice import Dice
from app.tools.narrative.executor import apply_in_context
from app.tools.runtime import flush_outbox, open_context, publish_changes


class RuntimeNarrativeApplier:
    """Infrastructure adapter applying proposals in a database transaction with world lock."""

    def __init__(
        self,
        session_maker: async_sessionmaker[AsyncSession],
        bus: Any,
        coordination: Any,
        *,
        policy_provider: Callable[[str], NarrativePolicy],
        dice_factory: Callable[[], Dice] = Dice,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_maker = session_maker
        self._bus = bus
        self._coordination = coordination
        self._policy_provider = policy_provider
        self._dice_factory = dice_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    async def apply(
        self,
        proposal: AdaptationProposal,
        *,
        claim: WorkClaim | None = None,
    ) -> AdaptationResult:
        cid = proposal.source.campaign_id
        policy = self._policy_provider(cid)

        turn_lock = None
        if self._coordination is not None and hasattr(self._coordination, "turn_lock"):
            turn_lock = self._coordination.turn_lock(cid)

        if turn_lock is not None:
            async with turn_lock:
                return await self._apply_transaction(cid, proposal, policy, claim=claim)
        return await self._apply_transaction(cid, proposal, policy, claim=claim)

    async def _apply_transaction(
        self,
        cid: str,
        proposal: AdaptationProposal,
        policy: NarrativePolicy,
        *,
        claim: WorkClaim | None = None,
    ) -> AdaptationResult:
        async with self._session_maker() as session:
            campaign = await session.get(Campaign, cid)
            if campaign is None:
                return AdaptationResult(status="failed", reason_code="campaign_not_found")

            # Verify server-owned claim and lease validity before writing (R12)
            if claim is not None:
                if (
                    claim.campaign_id != cid
                    or claim.proposal_id != proposal.proposal_id
                    or claim.source.campaign_id != cid
                    or claim.source.source_id != claim.work_id
                ):
                    raise LeaseLost("Work/source/proposal mismatch")

                now_utc = as_utc(self._clock())
                work = await session.scalar(
                    select(NarrativeWork).where(
                        NarrativeWork.id == claim.work_id,
                        NarrativeWork.lease_token == claim.lease_token,
                    )
                )
                if work is None or work.lease_until is None or as_utc(work.lease_until) <= now_utc:
                    raise LeaseLost(f"Lease lost or expired for job {claim.work_id}")

            dice = self._dice_factory()
            ctx = await open_context(session, campaign, dice, turn_id=None, seat_id=None)
            result = await apply_in_context(ctx, proposal, policy=policy)
            await flush_outbox(session, ctx)
            await session.commit()

            # Publish changes after commit (R14)
            if self._bus is not None and result.status in ("applied", "no_change"):
                await publish_changes(self._bus, ctx, [])

            return result
