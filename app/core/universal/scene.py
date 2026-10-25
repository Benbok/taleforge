"""Public exploration projection; private world laws stay in the admission context."""

from sqlalchemy import select

from app.core.inspect import viewer_hero
from app.core.object_policy import revealed_to
from app.core.scene_view import visible_scene
from app.core.universal.places import public_location_name
from app.core.world import get_scene
from app.db.models import Character, Entity
from app.tools.runtime import scene_payload


async def universal_scene(session, campaign, viewer):
    scene = await get_scene(session, campaign.id)
    entities = {e.id: e for e in (await session.scalars(select(Entity).where(Entity.campaign_id == campaign.id))).all()}
    characters = {
        h.id: h for h in (await session.scalars(select(Character).where(Character.campaign_id == campaign.id))).all()
    }
    hero = None if viewer.is_master else await viewer_hero(session, viewer)
    hero_id = hero.id if hero else None
    found = await revealed_to(session, hero_id)
    view = visible_scene(scene, entities, characters, hero_id=hero_id, is_master=viewer.is_master, revealed=found)
    payload = scene_payload(scene, entities, characters, view)
    location = entities.get(view.current_location_id or "")
    if location is not None:
        payload["location"]["name"] = public_location_name(campaign, location)
        payload["location"]["description"] = location.description
    return payload
