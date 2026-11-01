"""Persistent scene facts and lazy destinations, independent of action resolution."""

import hashlib

from sqlalchemy import select

from app.core.universal.clock import lock_campaign
from app.core.universal.foes import FALLBACK_FOES, FoeSlot, foe_slots
from app.core.universal.loot import FALLBACK_NAMES, LootSlot, loot_profile, loot_slots, loot_state, shop_slots
from app.core.universal.threads import threads_of
from app.core.world_generation import storage
from app.core.world_generation.contracts import Blocked
from app.db.models import CampaignSecret, Character, Entity, Message, WorldGenerationState
from app.rules.universal.world import WorldScenePlan

VERSION = "universal-scene-v1"


def enabled(campaign):
    return campaign.ruleset_id == "universal" and (campaign.settings or {}).get(
        "universal_world_generation", bool(campaign.adventure_version_id)
    )


def entity_id(campaign_id, location_id, ref):
    return "en_" + hashlib.sha256(f"{VERSION}:{campaign_id}:{location_id}:{ref}".encode()).hexdigest()[:24]


async def cast_view(session, campaign_id, secret):
    """The plot's people with a mark for each of them that already stands in the world, so the scene maker brings in
    the ones still missing where they belong instead of leaving the plot's people as words in a secret."""
    cast = (secret.setting or {}).get("cast") if secret else None
    if not cast:
        return []
    names = [
        row.name.casefold()
        for row in await session.scalars(
            select(Entity).where(Entity.campaign_id == campaign_id, Entity.kind == "creature")
        )
    ]
    return [
        {**person, "introduced": any(person["name"].casefold() in name for name in names)}
        for person in cast
        if isinstance(person, dict) and person.get("name")
    ]


async def recent_actions(session, campaign_id, limit=5):
    """What the heroes said and did lately, oldest first: the scene maker leans the new place towards it."""
    rows = await session.scalars(
        select(Message)
        .where(Message.campaign_id == campaign_id, Message.kind.in_(("action", "speech")))
        .order_by(Message.seq.desc())
        .limit(limit)
    )
    return [m.content[:200] for m in reversed(list(rows))]


async def known_people(session, campaign_id, location_id, limit=12):
    """People the story already has elsewhere, so a scene reuses a name instead of inventing a second one for the
    same person; a person who follows the heroes is told by the name they already carry."""
    rows = await session.scalars(
        select(Entity).where(
            Entity.campaign_id == campaign_id,
            Entity.kind == "creature",
            Entity.location_id.is_not(None),
            Entity.location_id != location_id,
        )
    )
    result = []
    for row in rows:
        state = row.state or {}
        if state.get("hostile") or int(state.get("resources", {}).get("hp", "1")) <= 0 or state.get("hidden"):
            continue
        result.append(dict(name=row.name, about=(row.description or "")[:160]))
        if len(result) == limit:
            break
    return result


async def find_known_person(session, campaign_id, name, location_id):
    """A peaceful, living person of the story already standing in another place under this very name."""
    wanted = name.casefold().strip()
    rows = await session.scalars(
        select(Entity).where(
            Entity.campaign_id == campaign_id, Entity.kind == "creature", Entity.location_id != location_id
        )
    )
    for row in rows:
        state = row.state or {}
        if (
            row.name.casefold().strip() == wanted
            and row.location_id
            and not state.get("hostile")
            and int(state.get("resources", {}).get("hp", "1")) > 0
        ):
            return row
    return None


def _given_name(location):
    """The entry place carries the world's title until its scene is prepared; shown to the model as a title it would
    copy for the place ("Путешествие в мрак бездны"), so it gets the neutral placeholder the story already knows."""
    from app.core.universal.places import START_LOCATION_NAME

    if (location.state or {}).get("studio_entry") and not (location.state.get("universal_scene") or {}).get("ready"):
        return START_LOCATION_NAME
    return location.name


async def reserve_scene(session, campaign, location_id, turn_id=None, source_id=""):
    await lock_campaign(session, campaign.id)
    location = await session.get(Entity, location_id, populate_existing=True)
    if location is None or location.campaign_id != campaign.id or location.kind != "location":
        raise ValueError("Место недоступно в этом прохождении")
    old = await storage.find(session, campaign.id, location_id, "location_initial")
    if old is not None:
        return old
    row = WorldGenerationState(
        campaign_id=campaign.id,
        target_entity_id=location_id,
        phase="location_initial",
        generator_version=VERSION,
        reservation=await scene_reservation(session, campaign, location, turn_id, source_id),
    )
    session.add(row)
    await session.flush()
    storage.activate(row)
    return row


async def scene_reservation(session, campaign, location, turn_id=None, source_id=""):
    location_id = location.id
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
                condition="dead"
                if row.kind == "creature" and int(state.get("resources", {}).get("hp", "1")) <= 0
                else state.get("condition", ""),
                expired=bool((state.get("exploration") or {}).get("expired")),
                hostile=bool(state.get("hostile")),
                remaining_material=(state.get("exploration") or {}).get("amount"),
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
    heroes = [
        dict(id=h.id, name=h.name, condition="incapacitated" if int(h.resources.get("hp", "1")) <= 0 else "active")
        for h in await session.scalars(
            select(Character).where(
                Character.campaign_id == campaign.id,
                Character.location_id == location_id,
                Character.status.in_(["active", "approved"]),
                Character.seat_id.is_not(None),
            )
        )
    ]
    evidence = []
    for message in await session.scalars(
        select(Message)
        .where(Message.campaign_id == campaign.id, Message.kind == "narration")
        .order_by(Message.seq.desc())
        .limit(60)
    ):
        data = message.data or {}
        if message.visible_to is not None or data.get("whisper_reply") or data.get("scope") == "private":
            continue
        place = data.get("location_id") or (data.get("location_ref") or {}).get("id")
        if place == location_id:
            evidence.append(message.content[:6000])
            if len(evidence) == 10:
                break
    context = dict(
        world=(secret.setting or {}).get("studio", {}) if secret else {},
        public_intro=campaign.public_intro,
        difficulty=campaign.difficulty,
        loot_slots=[
            dict(ref=slot.ref, kind=slot.kind, rarity=slot.rarity) for slot in loot_slots(campaign, location.id)
        ],
        shop_slots=[
            dict(ref=slot.ref, kind=slot.kind, rarity=slot.rarity) for slot in shop_slots(campaign, location.id)
        ],
        known_people=await known_people(session, campaign.id, location.id),
        foe_slots=[
            dict(ref=slot.ref, power=slot.power)
            for slot in foe_slots(campaign, location.id, entry=bool((location.state or {}).get("studio_entry")))
        ],
        cast=await cast_view(session, campaign.id, secret),
        threads=threads_of(secret),
        recent_actions=await recent_actions(session, campaign.id),
        location=dict(id=location.id, name=_given_name(location), description=location.description),
        existing_objects=present,
        existing_neighbors=neighbors,
        present_heroes=heroes,
        established_public_evidence=list(reversed(evidence)),
    )
    return dict(
        engine=VERSION,
        context=context,
        foundation=location.description,
        turn_id=turn_id,
        source_id=source_id,
        model_call_limit=6,
    )


async def retry_failed_scene(session, campaign, ref):
    """The authorized chat Retry action rearms only its blocked scene, never a ready world."""
    await lock_campaign(session, campaign.id)
    row = await session.get(WorldGenerationState, ref, populate_existing=True)
    if row is None or row.campaign_id != campaign.id or row.generator_version != VERSION or row.status != "blocked":
        return False
    location = await session.get(Entity, row.target_entity_id, populate_existing=True)
    if location is None or location.campaign_id != campaign.id:
        return False
    before = row.reservation
    refreshed = await scene_reservation(session, campaign, location, before.get("turn_id"), before.get("source_id", ""))
    row.reservation = {
        **refreshed,
        "context": {**refreshed["context"], "loot_slots": before["context"].get("loot_slots", [])},
    }
    storage.retry(row)
    await session.flush()
    return True


async def publish_scene(session, row, plan: WorldScenePlan):
    from app.core.universal.combat_actions import initialize_combatant
    from app.core.universal.objects import ObjectState

    cid = row.campaign_id
    location = await session.get(Entity, row.target_entity_id, populate_existing=True)
    reservation = row.reservation
    if location is None or location.campaign_id != cid:
        raise Blocked("target_missing", "Места больше нет")
    saved = (location.state or {}).get("universal_scene", {})
    if saved.get("ready") and saved.get("generation_ref") == row.id:
        return saved.get("manifest", row.result_manifest)
    if location.description != reservation["foundation"]:
        raise Blocked("stale_context", "Описание места изменилось во время подготовки")
    allowed = {n["id"] for n in reservation["context"]["existing_neighbors"]}
    if any(p.existing_destination_id and p.existing_destination_id not in allowed for p in plan.passages):
        raise Blocked("invalid_destination", "Предложена посторонняя связь")
    made = []
    names = {o["name"].casefold() for o in reservation["context"]["existing_objects"]}
    # one person is one person: a member of the plot's cast who already stands somewhere is not made again here
    placed = [p["name"].casefold() for p in reservation["context"].get("cast", []) if p.get("introduced")]
    foes = {raw["ref"]: FoeSlot(**raw) for raw in reservation["context"].get("foe_slots", [])}
    met = set()
    merchant_id = None
    for spec in plan.objects:
        if spec.name.casefold() in names:
            continue
        if spec.kind != "object" and any(person in spec.name.casefold() for person in placed):
            continue
        if spec.kind == "npc":
            known = await find_known_person(session, cid, spec.name, location.id)
            if known is not None:  # the same person met again, not a second one: they come along, under their name
                known.location_id = location.id
                merchant_id = known.id if spec.merchant else merchant_id
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
            slot = foes.get(spec.ref)
            if slot is not None:  # a place of the server's encounter: always hostile, as strong as the server says
                met.add(slot.ref)
                state.update(hostile=True, attitude="hostile", power=slot.power, temper=spec.temper)
            else:
                attitude = "hostile" if spec.hostile else "neutral"
                state.update(hostile=spec.hostile, attitude=attitude, temper=spec.temper)
        entity = Entity(
            id=key,
            campaign_id=cid,
            location_id=location.id,
            kind="object" if spec.kind == "object" else "creature",
            name=spec.name,
            description=spec.description,
            state=state,
        )
        if spec.merchant:
            merchant_id = key
        session.add(entity)
        await session.flush()
        if entity.kind == "creature":
            await initialize_combatant(session, cid, entity.id)
        made.append(entity.id)
    for slot in foes.values():
        if slot.ref in met:
            continue
        name, description = FALLBACK_FOES[slot.power]  # the model left a place of the encounter empty
        key = entity_id(cid, location.id, "foe:" + slot.ref)
        if await session.get(Entity, key) is not None:
            raise Blocked("identity_conflict", "Существо уже существует")
        entity = Entity(
            id=key,
            campaign_id=cid,
            location_id=location.id,
            kind="creature",
            name=name,
            description=description,
            state=dict(universal_scene_ref=row.id, hidden=False, hostile=True, attitude="hostile", power=slot.power),
        )
        session.add(entity)
        await session.flush()
        await initialize_combatant(session, cid, entity.id)
        made.append(entity.id)
    items = {item.ref: item for item in plan.items}
    for raw in reservation["context"].get("loot_slots", []):
        slot = LootSlot(**raw)
        spec = items.get(slot.ref)
        profile = loot_profile(
            slot,
            spec.name if spec else FALLBACK_NAMES[slot.kind],
            spec.description if spec else "Обычный предмет, оставленный в этом месте.",
            spec.attribute if spec else "str",
        )
        key = entity_id(cid, location.id, "loot:" + slot.ref)
        if await session.get(Entity, key) is not None:
            raise Blocked("identity_conflict", "Предмет уже существует")
        session.add(
            Entity(
                id=key,
                campaign_id=cid,
                location_id=location.id,
                kind="object",
                name=profile.name,
                description=profile.description,
                state=dict(universal_scene_ref=row.id, **loot_state(slot, profile)),
            )
        )
        made.append(key)
    for raw in reservation["context"].get("shop_slots", []):
        if merchant_id is None:  # nobody stands behind the stall: there is no shop here
            break
        slot = LootSlot(**raw)
        spec = items.get(slot.ref)
        profile = loot_profile(
            slot,
            spec.name if spec else FALLBACK_NAMES[slot.kind],
            spec.description if spec else "Товар на прилавке.",
            spec.attribute if spec else "str",
        )
        key = entity_id(cid, location.id, "shop:" + slot.ref)
        if await session.get(Entity, key) is not None:
            raise Blocked("identity_conflict", "Товар уже существует")
        session.add(
            Entity(
                id=key,
                campaign_id=cid,
                location_id=location.id,
                kind="object",
                name=profile.name,
                description=profile.description,
                state=dict(universal_scene_ref=row.id, **loot_state(slot, profile, seller_id=merchant_id)),
            )
        )
        made.append(key)
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
    manifest = dict(entities=made, destinations=destinations, location_id=location.id)
    location.description = foundation + ("\n\n" if foundation else "") + plan.description
    location.state = {
        **location.state,
        "links": links,
        "universal_scene": dict(ready=True, generation_ref=row.id, title=plan.name, manifest=manifest),
    }
    await session.flush()
    from app.core.universal.orientation_generation import ensure_map

    await ensure_map(session, cid, location.id)
    return manifest
