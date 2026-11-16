"""One attempt per way: a failed check closes that ability on that target for the whole party."""

from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import select

from app.db.models import AttemptLock


async def approach_closed(session, campaign_id: str, target_id: str, attribute: str) -> bool:
    return (
        await session.scalar(
            select(AttemptLock.id).where(
                AttemptLock.campaign_id == campaign_id,
                AttemptLock.target_id == target_id,
                AttemptLock.attribute == attribute,
            )
        )
        is not None
    )


async def close_approach(
    session, campaign_id: str, target_id: str, attribute: str, actor_id: str, event_id: str
) -> None:
    """Idempotent: a replayed receipt finds the row and adds nothing."""
    if await approach_closed(session, campaign_id, target_id, attribute):
        return
    session.add(
        AttemptLock(
            campaign_id=campaign_id, target_id=target_id, attribute=attribute, actor_id=actor_id, event_id=event_id
        )
    )
    await session.flush()


async def closed_approaches(session, campaign_id: str, target_ids: Iterable[str]) -> list[dict]:
    ids = list(target_ids)
    if not ids:
        return []
    rows = await session.execute(
        select(AttemptLock.target_id, AttemptLock.attribute)
        .where(AttemptLock.campaign_id == campaign_id, AttemptLock.target_id.in_(ids))
        .order_by(AttemptLock.target_id, AttemptLock.attribute)
    )
    return [{"target_id": t, "attribute": a} for t, a in rows]
