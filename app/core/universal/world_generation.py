"""Persistent scene facts and lazy destinations, independent of action resolution."""

import hashlib

from sqlalchemy import select

from app.core.universal.clock import lock_campaign
from app.core.world_generation import storage
from app.core.world_generation.contracts import Blocked
from app.db.models import CampaignSecret, Entity, WorldGenerationState
from app.rules.universal.world import WorldScenePlan

VERSION = "universal-scene-v1"


def enabled(campaign):
    return campaign.ruleset_id == "universal" and (campaign.settings or {}).get(
        "universal_world_generation", bool(campaign.adventure_version_id)
    )


def entity_id(campaign_id, location_id, ref):
    return "en_" + hashlib.sha256(f"{VERSION}:{campaign_id}:{location_id}:{ref}".encode()).hexdigest()[:24]


async def reserve_scene(session, campaign, location_id, turn_id=None, source_id=""):
    await lock_campaign(session, campaign.id)
    location = await session.get(Entity, location_id, populate_existing=True)
    if location is None or location.campaign_id != campaign.id or location.kind != "location":
        raise ValueError("Место недоступно в этом прохождении")
    old = await storage.find(session, campaign.id, location_id, "location_initial")
    if old is not None:
        return old
    secret = await session.get(CampaignSecret, campaign.id)
    present = []
    for row in await session.scalars(
        select(Entity).where(
            Entity.campaign_id == campaign.id,
            Entity.location_id == location_id,
        )
    ):
        state = row.state or {}
        if state.get("universal_item") or (state.get("exploration") or {}).get("owner_id"):
            continue
        present.append(
            dict(
                id=row.id,
                name=row.name,
                description=row.description,
                kind=row.kind,
                hidden=bool(state.get("hidden") or state.get("secret")),
            )
        )
    neighbors = []
    for link in (location.state or {}).get("links", []):
        target = await session.get(Entity, link.get("to"))
        if target and target.campaign_id == campaign.id and target.kind == "location":
            neighbors.append(
                dict(
                    id=target.id,
                    name=target.name,
                    label=link.get("label"),
                    state=link.get("state"),
                    hidden=bool(link.get("hidden")),
                )
            )
    context = dict(
        world=(secret.setting or {}).get("studio", {}) if secret else {},
        public_intro=campaign.public_intro,
        difficulty=campaign.difficulty,
        location=dict(id=location.id, name=location.name, description=location.description),
        existing_objects=present,
        existing_neighbors=neighbors,
    )
    row = WorldGenerationState(
        campaign_id=campaign.id,
        target_entity_id=location_id,
        phase="location_initial",
        generator_version=VERSION,
        reservation=dict(
            engine=VERSION, context=context, foundation=location.description, turn_id=turn_id, source_id=source_id
        ),
    )
    session.add(row)
    await session.flush()
    storage.activate(row)
    return row


async def publish_scene(session, row, plan: WorldScenePlan):
    from app.core.universal.combat_actions import initialize_combatant
    from app.core.universal.objects import ObjectState

    cid = row.campaign_id
    location = await session.get(Entity, row.target_entity_id, populate_existing=True)
    reservation = row.reservation
    if location is None or location.campaign_id != cid:
        raise Blocked("target_missing", "Места больше нет")
    if location.description != reservation["foundation"]:
        raise Blocked("stale_context", "Описание места изменилось во время подготовки")
    allowed = {n["id"] for n in reservation["context"]["existing_neighbors"]}
    if any(p.existing_destination_id and p.existing_destination_id not in allowed for p in plan.passages):
        raise Blocked("invalid_destination", "Предложена посторонняя связь")
    made = []
    names = {o["name"].casefold() for o in reservation["context"]["existing_objects"]}
    for spec in plan.objects:
        if spec.name.casefold() in names:
            continue
        key = entity_id(cid, location.id, "object:" + spec.ref)
        if await session.get(Entity, key) is not None:
            raise Blocked("identity_conflict", "Объект уже существует")
        state = dict(universal_scene_ref=row.id, hidden=spec.hidden)
        if spec.kind == "object":
            prop = ObjectState(
                template="structure" if spec.template == "prop" else spec.template,
                material=spec.material,
                amount=spec.amount,
                capacity_ml=300 if spec.template == "vessel" else 0,
            )
            state["exploration"] = prop.model_dump(mode="json")
        else:
            state.update(hostile=spec.hostile, attitude="hostile" if spec.hostile else "neutral")
        entity = Entity(
            id=key,
            campaign_id=cid,
            location_id=location.id,
            kind="object" if spec.kind == "object" else "creature",
            name=spec.name,
            description=spec.description,
            state=state,
        )
        session.add(entity)
        await session.flush()
        if entity.kind == "creature":
            await initialize_combatant(session, cid, entity.id)
        made.append(entity.id)
    links = list((location.state or {}).get("links", []))
    destinations = {}
    for spec in plan.passages:
        target_id = spec.existing_destination_id or entity_id(cid, location.id, "place:" + spec.ref)
        target = await session.get(Entity, target_id)
        if spec.existing_destination_id:
            if target is None or target.campaign_id != cid or target.kind != "location":
                raise Blocked("invalid_destination", "Место назначения недоступно")
            destinations[spec.ref] = target_id
            continue  # An established connection/state is never rewritten by generation.
        if target is not None:
            raise Blocked("identity_conflict", "Место уже существует")
        passage = dict(
            to=target_id,
            label=spec.name,
            kind=spec.kind,
            state=spec.state,
            hidden=spec.hidden,
            bearing=spec.bearing,
            universal_passage=entity_id(cid, location.id, "passage:" + spec.ref),
        )
        target = Entity(
            id=target_id,
            campaign_id=cid,
            kind="location",
            name=spec.destination,
            description=spec.description,
            state=dict(
                secret=spec.hidden,
                universal_scene=dict(ready=False, origin=location.id),
                links=[{**passage, "to": location.id, "label": "Назад: " + spec.name, "bearing": None}],
            ),
        )
        session.add(target)
        links.append(passage)
        destinations[spec.ref] = target_id
    foundation = location.description or ""
    location.description = foundation + ("\n\n" if foundation else "") + plan.description
    location.state = {
        **location.state,
        "links": links,
        "universal_scene": dict(ready=True, generation_ref=row.id, title=plan.name),
    }
    await session.flush()
    return dict(entities=made, destinations=destinations, location_id=location.id)
