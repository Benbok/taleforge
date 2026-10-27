"""Universal map visibility shares the same policy as the playing scene."""

from app.core.universal.visibility import visible_entity


def route_is_known(place, destination_id):
    state = place.state or {}
    sketch = state.get("sketch") or {}
    passages = [
        p for p in [*sketch.get("exits", []), *sketch.get("unplaced_exits", [])] if p.get("to") == destination_id
    ]
    if passages:
        return any(not p.get("hidden") for p in passages)
    links = [p for p in state.get("links", []) if isinstance(p, dict) and p.get("to") == destination_id]
    return not links or any(not p.get("hidden") and p.get("visibility") not in {"hidden", "private"} for p in links)


def exit_details(place, destination_id):
    state = place.state or {}
    sketch = state.get("sketch") or {}
    passages = [
        p
        for p in [*sketch.get("exits", []), *sketch.get("unplaced_exits", [])]
        if p.get("to") == destination_id and not p.get("hidden")
    ]
    candidates = passages or [
        p
        for p in state.get("links", [])
        if isinstance(p, dict) and p.get("to") == destination_id and not p.get("hidden")
    ]
    candidate = next((p for p in candidates if p.get("state") == "open"), candidates[0] if candidates else {})
    return {key: candidate[key] for key in ("kind", "state") if candidate.get(key) is not None}


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
