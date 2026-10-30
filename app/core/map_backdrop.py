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


def side_of(bearing) -> str:
    """Grid side of an orientation exit; the same rule as the client (orientationPassages.ts)."""
    bearing = bearing or ""
    return "e" if "e" in bearing else "w" if "w" in bearing else "s" if "s" in bearing else "n"


async def visible_passages(session, viewer) -> list[dict]:
    """Exits the party knows, as the orientation map lists them: label and side of the grid."""
    from app.core.map import party_map

    found = {}
    for exit in (await party_map(session, viewer)).get("exits") or []:
        name = (exit.get("via") or exit.get("name") or "").strip()[:60]
        if name:
            found[name] = side_of(exit.get("bearing"))
    return [{"name": name, "side": side} for name, side in sorted(found.items(), key=lambda item: (item[1], item[0]))]


def _spread(passages, cols, rows, taken):
    """Exits on one side share it evenly (what the orientation map draws); width two cells."""
    result = []
    for side in "nesw":
        group = [p for p in passages if p["side"] == side and p["name"] not in taken]
        length = cols if side in "ns" else rows
        for i, passage in enumerate(group):
            at = min(max(round((i + 1) * length / (len(group) + 1) - 1), 0), max(length - 2, 0))
            result.append({"name": passage["name"], "side": side, "at": at, "kind": "passage", "state": None, "width": 2})
    return result


def source(viewer, location, passages=()) -> dict:
    stored = (location.state or {}).get("sketch")
    sketch = public_sketch(stored) if stored else None
    if sketch:
        taken = {e["name"] for e in sketch["exits"]}
        sketch["exits"] = [*sketch["exits"], *_spread(list(passages), sketch["cols"], sketch["rows"], taken)]
    return {
        "identity": public_location_name(viewer.campaign, location),
        "appearance": location.description or "",
        "personality": "",
        "sketch": sketch,
        # Passages of a complex are opened/hidden on the root entity, which the stored sketch does not reflect.
        "complex": bool(stored and stored.get("blueprint")),
    }


def blocker(src) -> str | None:
    if not src["appearance"].strip():
        return "сначала дождитесь описания локации"
    if not src["sketch"]:
        return "сначала создайте схему"
    if src["complex"]:
        return "подложка пока недоступна для комплексных локаций"
    return None


async def source_with_passages(viewer, location, session) -> dict:
    return source(viewer, location, await visible_passages(session, viewer))


EDGES = {"w": "слева", "e": "справа", "n": "сверху", "s": "снизу"}


def prompt_source(src) -> dict:
    """Description plus the exits by picture edge, so the painted paths and gaps leave where the map's exits are."""
    appearance = src["appearance"]
    exits = [e for e in (src["sketch"] or {}).get("exits", []) if e.get("kind") == "passage"]
    if exits:
        listed = "; ".join(
            f"{EDGES[side]} — " + ", ".join(f"«{e['name']}»" for e in exits if e["side"] == side)
            for side in "wens"
            if any(e["side"] == side for e in exits)
        )
        appearance = f"{appearance}\n\nВыходы из места (стороны картины): {listed}."
    return {"identity": src["identity"], "appearance": appearance, "personality": src["personality"]}


RECIPE = ArtworkRecipe(
    kind="map_backdrop",
    media_subdir="map-backdrops",
    purpose="map_backdrop_illustration",
    noun="подложку",
    source=source_with_passages,
    source_needs_session=True,
    permitted=lambda viewer: is_admin(viewer.user),
    blocker=blocker,
    init_image=lambda src: render_skeleton(src["sketch"]) if src["sketch"] and not src["complex"] else None,
    prompt_source=prompt_source,
    url=lambda campaign_id, location_id, image_id: f"/api/campaigns/{campaign_id}/locations/{location_id}/map-backdrop/{image_id}",
    denied="подложку создаёт администратор",
)
