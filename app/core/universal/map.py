"""Universal map visibility shares the same policy as the playing scene."""

from app.core.universal.visibility import visible_entity


async def map_entities(session, campaign_id, hero_id, master, entities):
    result = []
    for entity in entities:
        state = entity.state or {}
        prop = state.get("exploration", {})
        if state.get("universal_item") or (prop and (prop.get("owner_id") is not None or prop.get("expired"))):
            continue
        if not master and not await visible_entity(session, campaign_id, hero_id, entity):
            continue
        result.append(entity)
    return result
