"""Safely link an existing NPC to an existing hero after historical verification.

Dry-run is the default.  Use ``--apply`` only after checking the printed
campaign, entity, hero, and evidence event.
"""

from __future__ import annotations

import argparse
import asyncio
import copy

from app.db.models import Campaign, Character, Entity, Event


def _valid_basis(event: Event, entity_id: str, hero_id: str) -> bool:
    if event.actor_id != hero_id or event.target_id != entity_id or event.hidden:
        return False
    payload = event.payload or {}
    if event.tool == "pass_item":
        return True
    return (
        event.tool == "roll_check"
        and payload.get("kind") == "check"
        and payload.get("stat") in {"persuasion", "deception", "intimidation", "performance"}
        and payload.get("success") is True
    )


async def link(session, args: argparse.Namespace) -> tuple[bool, str]:
    campaign = await session.get(Campaign, args.campaign_id)
    entity = await session.get(Entity, args.entity_id)
    hero = await session.get(Character, args.hero_id)
    event = await session.get(Event, args.basis_event_id)
    if campaign is None or entity is None or hero is None or event is None:
        return False, "campaign, entity, hero, and basis event must belong to the database"
    if entity.campaign_id != campaign.id or hero.campaign_id != campaign.id or event.campaign_id != campaign.id:
        return False, "campaign/entity/hero/event mismatch"
    if entity.kind != "creature" or hero.status not in {"approved", "active"}:
        return False, "entity must be a creature and hero must be playable"
    if not _valid_basis(event, entity.id, hero.id):
        return False, "basis event is not a successful social check or visible item transfer by this hero"
    state = dict(entity.state or {})
    current = state.get("companion")
    if current is not None:
        if current.get("of") == hero.id and current.get("since_event") == event.id:
            return True, "already linked"
        return False, "entity is already linked to another hero"
    if state.get("dead") or state.get("fled") or state.get("attitude", "hostile") == "hostile":
        return False, "dead, fled, or hostile entity cannot become a companion"
    before = copy.deepcopy(state)
    state["companion"] = {"of": hero.id, "since_event": event.id, "reason": args.reason}
    state["attitude"] = "friendly"
    if not args.apply:
        return True, f"would link {entity.name} to {hero.name} using {event.id}"
    entity.state = state
    session.add(
        Event(
            campaign_id=campaign.id,
            tool="backfill_join_party",
            actor_id=hero.id,
            target_id=entity.id,
            payload={"entity_id": entity.id, "hero_id": hero.id, "since_event": event.id, "reason": args.reason},
            inverse=[{"table": "entities", "id": entity.id, "field": "state", "before": before}],
            hidden=False,
        )
    )
    return True, f"linked {entity.name} to {hero.name} using {event.id}"


async def main(args: argparse.Namespace) -> int:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.config import Settings

    engine = create_async_engine(Settings.from_env().database_url)
    try:
        async with async_sessionmaker(engine)() as session:
            ok, message = await link(session, args)
            if ok and args.apply and message.startswith("linked"):
                await session.commit()
            else:
                await session.rollback()
            print(message)
            return 0 if ok else 2
    finally:
        await engine.dispose()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--campaign-id", required=True)
    parser.add_argument("--entity-id", required=True)
    parser.add_argument("--hero-id", required=True)
    parser.add_argument("--basis-event-id", required=True)
    parser.add_argument("--reason", required=True)
    parser.add_argument("--apply", action="store_true")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
