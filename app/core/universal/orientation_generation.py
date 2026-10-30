"""One saved cosmetic sketch per location; no game step, loot or model calls."""

import hashlib
import zlib
from copy import deepcopy
from dataclasses import replace

from sqlalchemy import select

from app.core.campaigns import AccessDenied
from app.core.inspect import viewer_hero
from app.core.layout.geometry import build_area
from app.core.layout.intent import LayoutIntent, PartIntent
from app.core.layout.provider import DeterministicLayoutProvider
from app.core.object_policy import concealed
from app.core.sketch import check, floor_cells
from app.core.universal.clock import lock_campaign
from app.db.models import Campaign, Character, Entity, Scene

INDOOR_NAME_WORDS = (
    "конюшн", "хлев", "сарай", "амбар", "погреб", "подвал", "кухн", "кладов", "чердак", "склеп",
    "мастерск", "кузниц", "спальн", "кабинет", "изб",
)


def build_sketch(campaign_id, location, entities):
    # A coarse outline is presentation, never an asserted measurement or obstacle.
    text = (location.name + " " + location.description).casefold()
    shape = "cave" if any(w in text for w in ("пещер", "ущель", "провал", "cave", "gorge")) else "open"
    if any(w in text for w in ("комнат", "зал", "таверн", "room", "hall", "tavern")):
        shape = "rect"
    # Only the name: a description of the yard mentions "в конюшне" without the yard being a stable.
    if any(w in location.name.casefold() for w in INDOOR_NAME_WORDS):
        shape = "rect"
    intent = LayoutIntent(
        entry="here",
        parts=[
            PartIntent(
                part_ref="here",
                name="Место",
                public_name="Место",
                shape=shape,
                environment="indoor" if shape != "open" else "outdoor",
                size="medium",
            )
        ],
    )
    seed = zlib.crc32(f"{campaign_id}:{location.id}:orientation-v1".encode())
    blueprint = DeterministicLayoutProvider().propose(intent, seed=seed, root_id=location.id)
    area = replace(blueprint.areas[0], details=(), object_slots=())
    sketch = build_area(blueprint, area)
    sketch.pop("blueprint", None)  # cosmetic sketch is not a persisted playable complex
    refresh_object_markers(sketch, location, entities)
    if errors := check(sketch, set(entities)):
        raise ValueError("; ".join(errors))
    return sketch


def refresh_object_markers(sketch, location, entities):
    """Refresh cosmetic object references while retaining the saved terrain and exits."""
    floor = floor_cells(sketch) or {(c, r) for c in range(sketch["cols"]) for r in range(sketch["rows"])}
    cells = sorted(floor - {tuple(sketch["party"])}, key=lambda c: (c[1], c[0]))
    if not cells:
        return
    sketch["features"] = [f for f in sketch.get("features", []) if not str(f.get("id", "")).startswith("sf_")]
    markers = []
    for row in sorted(entities.values(), key=lambda e: e.id):
        if row.kind != "object" or row.location_id != location.id or concealed(row, entities):
            continue
        state = row.state or {}
        if state.get("visibility") in {"hidden", "private"} or state.get("universal_item"):
            continue
        prop = state.get("exploration") or {}
        if prop and (prop.get("owner_id") or prop.get("expired")):
            continue
        markers.append(row)
    for i, row in enumerate(markers[:16]):
        c, r = cells[(i + 1) * len(cells) // (min(len(markers), 16) + 1)]
        sketch["features"].append(
            dict(
                id="sf_" + hashlib.sha256(row.id.encode()).hexdigest()[:24],
                entity_id=row.id,
                name=row.name[:60],
                kind="object",
                cells=[[c, r, c, r]],
                cover="none",
                hidden=False,
                solid=False,
            )
        )


async def ensure_map(session, campaign_id, location_id):
    if not location_id:
        return False
    await session.flush()
    await lock_campaign(session, campaign_id)
    campaign = await session.get(Campaign, campaign_id)
    location = await session.get(Entity, location_id, populate_existing=True)
    if campaign.ruleset_id != "universal" or location is None or location.campaign_id != campaign_id:
        raise ValueError("Локация недоступна в этом прохождении")
    if location.kind != "location":
        raise ValueError("Выберите локацию")
    state = location.state or {}
    if state.get("sketch") or state.get("complex") or state.get("blueprint") or state.get("room"):
        if state.get("sketch") and state.get("orientation_map", {}).get("version") == 1:
            entities = {e.id: e for e in await session.scalars(select(Entity).where(Entity.campaign_id == campaign_id))}
            sketch = deepcopy(state["sketch"])
            refresh_object_markers(sketch, location, entities)
            if sketch != state["sketch"]:
                location.state = {**state, "sketch": sketch}
                await session.flush()
        return False
    entities = {e.id: e for e in await session.scalars(select(Entity).where(Entity.campaign_id == campaign_id))}
    location.state = {
        **state,
        "sketch": build_sketch(campaign_id, location, entities),
        "orientation_map": {"version": 1, "approximate": True},
    }
    await session.flush()
    return True


async def generate_for_viewer(session, viewer, location_id):
    cid = viewer.campaign.id
    await lock_campaign(session, cid)
    hero = await viewer_hero(session, viewer) if not viewer.is_master else None
    if hero:
        await session.refresh(hero)
    elif not viewer.is_master:
        raise AccessDenied("Создать схему может игрок своего героя или мастер")
    from app.core.map import party_map

    here = ((await party_map(session, viewer)).get("here") or {}).get("id")
    if here != location_id:
        raise ValueError("Местоположение изменилось. Обновите карту и попробуйте снова.")
    return dict(created=await ensure_map(session, cid, location_id), location_id=location_id)


async def prepare_party_maps(session, campaign):
    if campaign.ruleset_id != "universal":
        return
    scene = await session.get(Scene, campaign.id)
    locations = {
        location_id or (scene.location_id if scene else None)
        for location_id in await session.scalars(
            select(Character.location_id).where(
                Character.campaign_id == campaign.id,
                Character.status.in_(["active", "approved"]),
                Character.seat_id.is_not(None),
            )
        )
    }
    for location_id in sorted(locations - {None}):
        await ensure_map(session, campaign.id, location_id)
