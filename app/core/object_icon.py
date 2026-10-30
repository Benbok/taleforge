"""Small pictures of world objects, drawn on request and shown on the map instead of a generic glyph."""

from sqlalchemy import select

from app.core.artwork.recipe import ArtworkRecipe
from app.core.campaigns import NotFound, is_admin
from app.core.object_policy import concealed
from app.db.models import Entity


async def public_objects(session, viewer, location) -> list[Entity]:
    """Objects the area's map shows as markers (features bound to an entity) that are still visible and not private."""
    sketch = (location.state or {}).get("sketch") or {}
    ids = [f["entity_id"] for f in sketch.get("features") or [] if f.get("entity_id") and not f.get("hidden")]
    if not ids:
        return []
    entities = {e.id: e for e in await session.scalars(select(Entity).where(Entity.campaign_id == viewer.campaign.id))}
    found = []
    for object_id in dict.fromkeys(ids):
        row = entities.get(object_id)
        if row is None or row.kind != "object" or row.location_id != location.id or concealed(row, entities):
            continue
        if (row.state or {}).get("visibility") in {"hidden", "private"}:
            continue
        found.append(row)
    return found


async def visible_object(session, viewer, location, object_id) -> Entity:
    for row in await public_objects(session, viewer, location):
        if row.id == object_id:
            return row
    raise NotFound("предмет недоступен")


def source(viewer, obj) -> dict:
    return {"identity": (obj.name or "")[:80], "appearance": (obj.description or "")[:400], "personality": ""}


RECIPE = ArtworkRecipe(
    kind="object_icon",
    media_subdir="object-icons",
    purpose="object_icon_illustration",
    noun="значок предмета",
    source=source,
    permitted=lambda viewer: is_admin(viewer.user),
    blocker=lambda src: None if src["identity"].strip() else "у предмета нет названия",
    init_image=lambda src: None,
    prompt_source=lambda src: dict(src),
    url=lambda campaign_id, object_id, image_id: f"/api/campaigns/{campaign_id}/objects/{object_id}/icon/{image_id}",
    denied="значки предметов создаёт администратор",
)
