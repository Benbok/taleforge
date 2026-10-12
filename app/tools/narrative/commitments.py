"""Durable fact commitments and narration claim reservations."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.core.narrative.contracts import (
    FactRef,
    SnapshotRef,
)
from app.db.models import NarrativeFact
from app.tools.registry import ToolContext


async def record_commitments(
    ctx: ToolContext,
    refs: tuple[FactRef, ...],
    *,
    reason: str,
    snapshot_ref: SnapshotRef,
) -> tuple[FactRef, ...]:
    """Transition draft facts to committed status and record a hidden audit event."""
    if not refs:
        return ()

    cid = ctx.campaign.id
    newly_sealed: list[FactRef] = []

    for ref in refs:
        stmt = select(NarrativeFact).where(
            NarrativeFact.campaign_id == cid,
            NarrativeFact.namespace == ref.namespace,
            NarrativeFact.subject_id == ref.subject_id,
            NarrativeFact.key == ref.key,
        )
        res = await ctx.session.execute(stmt)
        row = res.scalar_one_or_none()
        if row is not None and row.freedom == "draft":
            row.freedom = "committed"
            row.snapshot_ref = snapshot_ref.model_dump()
            newly_sealed.append(ref)

    if newly_sealed:
        await ctx.session.flush()
        await ctx.record(
            "narrative_seal",
            hidden=True,
            payload={
                "reason": reason,
                "refs": [r.model_dump() for r in newly_sealed],
                "snapshot_ref": snapshot_ref.model_dump(),
            },
        )

    return tuple(newly_sealed)


async def reserve_narration_claims(
    maker: async_sessionmaker,
    campaign_id: str,
    turn_id: str,
    refs: tuple[FactRef, ...],
    audience: tuple[str, ...],
) -> tuple[FactRef, ...]:
    """Atomically commit and reserve fact claims prior to LLM narration composing."""
    if not refs:
        return ()

    reserved: list[FactRef] = []
    async with maker() as session:
        for ref in refs:
            stmt = select(NarrativeFact).where(
                NarrativeFact.campaign_id == campaign_id,
                NarrativeFact.namespace == ref.namespace,
                NarrativeFact.subject_id == ref.subject_id,
                NarrativeFact.key == ref.key,
            )
            res = await session.execute(stmt)
            row = res.scalar_one_or_none()
            if row is not None:
                row.freedom = "committed"
                aud_set = set(row.audience or [])
                aud_set.update(audience)
                row.audience = list(aud_set)
                reserved.append(ref)
        await session.commit()

    return tuple(reserved)
