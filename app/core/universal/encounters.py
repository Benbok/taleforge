"""Encounter participation is local and independent of reply eligibility."""

from sqlalchemy import select

from app.db.models import Entity, Scene


async def hostile_locations(session, campaign_id):
    return {
        row.location_id
        for row in await session.scalars(
            select(Entity).where(Entity.campaign_id == campaign_id, Entity.kind == "creature")
        )
        if row.state.get("hostile")
        and int(row.state.get("resources", {}).get("hp", "1")) > 0
        and row.state.get("resources", {}).get("vitality", {}).get("state") != "dead"
    }


async def in_combat(session, campaign_id, location_id):
    locations = await hostile_locations(session, campaign_id)
    if locations:
        return location_id in locations
    scene = await session.get(Scene, campaign_id)
    return bool(scene and scene.mode == "combat" and scene.location_id in {None, location_id})
