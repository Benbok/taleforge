"""Database adapter for NarrativeReader port."""

from __future__ import annotations

from collections.abc import Callable

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.narrative.contracts import (
    NarrativePolicy,
    NarrativeSnapshot,
    SnapshotRequest,
)
from app.db.models import Campaign
from app.rules.dice import Dice
from app.tools.narrative.context import load_snapshot
from app.tools.runtime import open_context


class DbNarrativeReader:
    """Implements NarrativeReader port without holding world locks or long leases."""

    def __init__(
        self,
        maker: async_sessionmaker,
        *,
        policy_provider: Callable[[], NarrativePolicy],
    ) -> None:
        self._maker = maker
        self._policy_provider = policy_provider

    async def snapshot(self, request: SnapshotRequest) -> NarrativeSnapshot:
        async with self._maker() as session:
            campaign = await session.get(Campaign, request.source.campaign_id)
            if campaign is None:
                raise ValueError(f"Campaign not found: {request.source.campaign_id}")

            ctx = await open_context(
                session,
                campaign,
                Dice(),
                turn_id=None,
                seat_id=None,
            )
            return await load_snapshot(ctx, request, policy=self._policy_provider())
