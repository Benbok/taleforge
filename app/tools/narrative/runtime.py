"""Runtime implementation of NarrativeApplier port (Task 14)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.narrative.contracts import (
    AdaptationProposal,
    AdaptationResult,
    NarrativePolicy,
)
from app.db.models import Campaign
from app.rules.dice import Dice
from app.tools.narrative.executor import apply_in_context
from app.tools.runtime import flush_outbox, open_context


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
    ) -> None:
        self._session_maker = session_maker
        self._bus = bus
        self._coordination = coordination
        self._policy_provider = policy_provider
        self._dice_factory = dice_factory

    async def apply(self, proposal: AdaptationProposal) -> AdaptationResult:
        cid = proposal.source.campaign_id
        policy = self._policy_provider(cid)

        turn_lock = None
        if self._coordination is not None and hasattr(self._coordination, "turn_lock"):
            turn_lock = self._coordination.turn_lock(cid)

        if turn_lock is not None:
            async with turn_lock:
                return await self._apply_transaction(cid, proposal, policy)
        return await self._apply_transaction(cid, proposal, policy)

    async def _apply_transaction(
        self, cid: str, proposal: AdaptationProposal, policy: NarrativePolicy
    ) -> AdaptationResult:
        async with self._session_maker() as session:
            campaign = await session.get(Campaign, cid)
            if campaign is None:
                return AdaptationResult(status="failed", reason_code="campaign_not_found")

            dice = self._dice_factory()
            ctx = await open_context(session, campaign, dice, turn_id=None, seat_id=None)
            result = await apply_in_context(ctx, proposal, policy=policy)
            await flush_outbox(session, ctx)
            await session.commit()
            return result
