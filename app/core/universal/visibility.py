"""One current-visibility policy for combat, effects and perception."""

from sqlalchemy import select

from app.core.object_policy import concealed, revealed_to
from app.db.models import Entity


async def shared_observations(session, campaign_id, audience, changes):
    """A discovered detail is shared only when every recipient can see it."""
    from app.db.models import Character

    heroes = list(
        await session.scalars(
            select(Character).where(
                Character.campaign_id == campaign_id,
                Character.seat_id.is_not(None),
                Character.status.in_(["active", "approved"]),
            )
        )
    )
    if audience is not None:
        heroes = [h for h in heroes if h.seat_id in audience]
    result = []
    for change in changes:
        if change.get("private"):
            continue
        if change.get("kind") == "observation":
            entity = await session.get(Entity, change.get("subject_id"))
            if entity is None or not heroes:
                continue
            visible = [
                (entity.id == h.location_id or entity.location_id == h.location_id)
                and await visible_entity(session, campaign_id, h.id, entity)
                for h in heroes
            ]
            if not all(visible):
                continue
        result.append(change)
    return result


async def visible_entity(session, campaign_id, hero_id, entity):
    if entity.campaign_id != campaign_id or entity.state.get("visibility") in {"hidden", "private"}:
        return False
    entities = {
        row.id: row
        for row in await session.scalars(
            select(Entity).where(Entity.campaign_id == campaign_id).execution_options(populate_existing=True)
        )
    }
    return not concealed(entity, entities, await revealed_to(session, hero_id))
