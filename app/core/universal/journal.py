"""A journal of requests the engine has no ready mechanics for: the evidence for what to build next."""

from sqlalchemy import select

from app.db.models import UniversalJournal


async def record_journal(session, campaign_id, kind, source_key, source_text, detail):
    """One entry per (campaign, kind, source message), so a replay or a retry never writes it twice."""
    seen = await session.scalar(
        select(UniversalJournal.id).where(
            UniversalJournal.campaign_id == campaign_id,
            UniversalJournal.kind == kind,
            UniversalJournal.source_key == source_key,
        )
    )
    if seen is None:
        session.add(
            UniversalJournal(
                campaign_id=campaign_id, kind=kind, source_key=source_key, source_text=source_text, detail=detail
            )
        )
        await session.flush()
