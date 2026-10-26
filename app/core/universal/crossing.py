"""Walking over a remembered structure: the place on its far side appears when someone first goes there."""

import hashlib

from app.core.campaigns import AccessDenied
from app.core.universal.objects import accessible, object_state, store
from app.db.models import Character, Entity
from app.rules.universal.exploration import EffectChange


def _link(place, target_id, label):
    links = [x for x in (place.state or {}).get("links") or [] if isinstance(x, dict)]
    if not any(x.get("to") == target_id for x in links):
        links.append({"to": target_id, "label": label})
    place.state = {**(place.state or {}), "links": links}


async def cross_structure(ctx, op, source_event):
    """Move the acting hero (and only the hero) over the structure named by `op.object_id`.

    The first crossing creates the far place from the structure's own words and links it both ways; later
    crossings, from either side, reuse it."""
    s = ctx.session
    actor = await s.get(Character, ctx.actor_id)
    row = await s.get(Entity, op.object_id or "")
    try:
        accessible(row, actor)
    except AccessDenied:
        raise ValueError("Пути больше нет: постройки здесь нет или она исчезла") from None
    state = object_state(row)
    if state.template != "structure" or not state.leads_to:
        raise ValueError("Эта постройка никуда не ведёт")
    origin_id = row.location_id
    if state.leads_to_location_id is None:
        far_id = "en_" + hashlib.sha256(f"cross:{row.id}".encode()).hexdigest()[:24]
        far = await s.get(Entity, far_id)
        if far is None:
            far = Entity(
                id=far_id,
                campaign_id=ctx.campaign_id,
                kind="location",
                name=state.leads_to,
                description=state.leads_view,
                state={"created_by": row.id},
            )
            s.add(far)
        _link(far, origin_id, row.name)
        origin = await s.get(Entity, origin_id) if origin_id else None
        if origin is not None and origin.kind == "location":
            _link(origin, far_id, row.name)
        state.leads_to_location_id = far_id
        store(row, state)
    far_id = state.leads_to_location_id
    target_id = origin_id if actor.location_id == far_id else far_id
    actor.location_id = target_id
    await s.flush()
    if target_id:
        from app.core.universal.orientation_generation import ensure_map

        await ensure_map(s, ctx.campaign_id, target_id)
    place = await s.get(Entity, target_id) if target_id else None
    where = place.name if place is not None else "прежнее место"
    return EffectChange(
        kind="moved",
        subject_id=actor.id,
        description=f"Герой переходит по постройке «{row.name}»: {where}.",
        data={"location_id": target_id or "", "via": row.id},
    )
