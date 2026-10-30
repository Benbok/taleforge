"""python -m tests.eval.capture CAMPAIGN SOURCE NAME (against the configured DB)."""

import argparse
import asyncio
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.agents.master.prompting.context import build_decide_context
from app.db.models import Campaign, Character, Message

FIXTURES = Path(__file__).parent / "fixtures"


async def capture_context(session, campaign_id: str, source: str) -> dict:
    campaign = await session.scalar(
        select(Campaign).where(Campaign.id == campaign_id).options(selectinload(Campaign.seats))
    )
    if campaign is None or campaign.ruleset_id != "universal":
        raise ValueError("Expected an existing universal campaign")
    hero = await session.scalar(
        select(Character)
        .where(
            Character.campaign_id == campaign_id,
            Character.seat_id.is_not(None),
            Character.status.in_(["active", "approved"]),
        )
        .order_by(Character.id)
    )
    if hero is None:
        raise ValueError("Campaign has no admitted player hero")
    seat = next(seat for seat in campaign.seats if seat.id == hero.seat_id)
    # Match the audience of the latest actual turn, excluding the new source.
    message = await session.scalar(
        select(Message).where(Message.campaign_id == campaign_id).order_by(Message.seq.desc()).limit(1)
    )
    audience = [s.id for s in campaign.seats if s.role == "player"]
    context = await build_decide_context(
        session,
        campaign,
        hero,
        seat,
        source,
        upto_seq=message.seq if message else 0,
        audience=audience,
    )
    context["actor_id"] = hero.id
    context["allowed_target_ids"] = sorted({hero.id, *(e["id"] for e in context["scene"].get("entities", []))})
    return context


async def main():
    from app.config import settings
    from app.db.session import make_engine, make_sessionmaker

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("campaign_id")
    parser.add_argument("source")
    parser.add_argument("name", choices=["shire", "station"])
    args = parser.parse_args()
    engine = make_engine(settings.database_url)
    try:
        async with make_sessionmaker(engine)() as session:
            context = await capture_context(session, args.campaign_id, args.source)
        FIXTURES.mkdir(parents=True, exist_ok=True)
        target = FIXTURES / f"{args.name}.json"
        target.write_text(json.dumps(context, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(target)
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
