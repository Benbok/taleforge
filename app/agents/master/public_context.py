"""Audience intersection for narration, not the master's private decision context."""

from copy import deepcopy

from sqlalchemy import select

from app.agents.master.universal_narration import recent_history
from app.core.knowledge import Index, Section
from app.core.universal.visibility import shared_observations, visible_entity
from app.db.models import Character, Entity, KnownFact


async def public_context(session, campaign, upto_seq, audience, scene, outcomes):
    heroes = list(
        await session.scalars(
            select(Character).where(
                Character.campaign_id == campaign.id,
                Character.status.in_(["active", "approved"]),
                Character.seat_id.is_not(None),
            )
        )
    )
    if audience is not None:
        heroes = [h for h in heroes if h.seat_id in audience]
    place = (scene.get("location") or {}).get("id")
    # An absent recipient never grants access. Master seats are not player knowledge.
    subjects = {h.id for h in heroes if h.location_id == place}
    entities = []
    for item in scene.get("entities", []):
        row = await session.get(Entity, item["id"])
        if row is None or not heroes:
            continue
        visible = [await visible_entity(session, campaign.id, h.id, row) for h in heroes]
        if not all(visible):
            continue
        subjects.add(row.id)
        entities.append(
            {
                **{k: item[k] for k in ("id", "name", "kind", "condition", "attitude") if k in item},
                "description": row.description,
            }
        )
    location = deepcopy(scene.get("location"))
    if location and heroes and all(h.location_id == place for h in heroes):
        subjects.add(place)
    else:
        location = None
    safe_scene = dict(
        location=location,
        entities=entities,
        mode=scene.get("mode", "free"),
        heroes=[dict(id=h.id, name=h.name) for h in heroes if h.location_id == place],
    )
    facts = deepcopy(outcomes)
    for outcome in facts.values():
        changes = outcome.get("changes", [])
        shared = await shared_observations(session, campaign.id, audience, changes)
        if len(shared) != len(changes):
            outcome["changes"] = shared
            outcome["description"] = " ".join(c.get("description", "") for c in shared) or "Действие обработано."
            outcome["reason"] = outcome["description"]
    # Reuse the project's lexical retrieval, but only AFTER campaign, subject and
    # recipient filtering. Private lore indexes and global summaries never enter.
    known = {}
    for fact in await session.scalars(
        select(KnownFact).where(
            KnownFact.campaign_id == campaign.id,
            KnownFact.subject_id.in_(subjects),
            KnownFact.character_id.in_([h.id for h in heroes]),
        )
    ):
        known.setdefault((fact.subject_id, fact.text), set()).add(fact.character_id)
    required = {h.id for h in heroes}
    sections = [
        Section(str(i), "known_fact", subject, text)
        for i, ((subject, text), owners) in enumerate(known.items())
        if required and required.issubset(owners)
    ]
    query = " ".join([str(safe_scene), str(facts)])
    memory = Index(sections).search(query, 6, visible=("common",))
    return dict(
        outcomes=facts,
        scene=safe_scene,
        recent_history=await recent_history(session, campaign, upto_seq, audience, safe_scene),
        knowledge=[dict(subject_id=s.title, text=s.body) for s in memory],
    )
