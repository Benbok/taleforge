"""Painted top-down backdrop under the orientation map: public outline in, shared per-area picture out."""

from app.core.artwork.recipe import ArtworkRecipe
from app.core.campaigns import NotFound, is_admin
from app.core.universal.backdrop_skeleton import public_sketch, render_skeleton
from app.core.universal.places import public_location_name
from app.core.universal.scene import universal_scene
from app.db.models import Entity


async def current_area(session, viewer, location_id):
    # Same projection as the game: split parties and undiscovered places stay invisible.
    visible = await universal_scene(session, viewer.campaign, viewer)
    if (visible.get("location") or {}).get("id") != location_id:
        raise NotFound("локация недоступна")
    location = await session.get(Entity, location_id)
    if not location or location.campaign_id != viewer.campaign.id or location.kind != "location":
        raise NotFound("локация недоступна")
    return location


def source(viewer, location) -> dict:
    stored = (location.state or {}).get("sketch")
    return {
        "identity": public_location_name(viewer.campaign, location),
        "appearance": location.description or "",
        "personality": "",
        "sketch": public_sketch(stored) if stored else None,
    }


def blocker(src) -> str | None:
    if not src["appearance"].strip():
        return "сначала дождитесь описания локации"
    if not src["sketch"]:
        return "сначала создайте схему"
    return None


RECIPE = ArtworkRecipe(
    kind="map_backdrop",
    media_subdir="map-backdrops",
    purpose="map_backdrop_illustration",
    noun="подложку",
    source=source,
    permitted=lambda viewer: is_admin(viewer.user),
    blocker=blocker,
    init_image=lambda src: render_skeleton(src["sketch"]) if src["sketch"] else None,
    prompt_source=lambda src: {key: src[key] for key in ("identity", "appearance", "personality")},
    url=lambda campaign_id, location_id, image_id: f"/api/campaigns/{campaign_id}/locations/{location_id}/map-backdrop/{image_id}",
    denied="подложку создаёт администратор",
)
