"""One current-visibility policy for combat, effects and perception."""

from sqlalchemy import select

from app.core.object_policy import concealed, revealed_to
from app.db.models import Entity


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
