"""Build deterministic, structured facts for the master decision prompt.

The snapshot is intentionally read-only.  It turns the already loaded live
world into small, addressable facts; narrative memory and chat history remain
separate prompt blocks until their selection policy is proven safe.
"""

from __future__ import annotations

import json

from app.agents.master.context_selection import ContextFact
from app.core.narrative.contracts import FactRef, FactState
from app.core.object_policy import concealed
from app.core.topology import location_exits


def fact_key(ref: FactRef) -> str:
    """Return one deterministic address for a fact and every dependency link."""
    snapshot = ref.snapshot_ref
    address = {
        "campaign_id": ref.campaign_id,
        "namespace": ref.namespace,
        "subject_id": ref.subject_id,
        "key": ref.key,
        "version": ref.version,
        "snapshot": {
            "kind": snapshot.kind,
            "source_id": snapshot.source_id,
            "version": snapshot.version,
            "typed_address": snapshot.typed_address,
        },
    }
    return "fact:" + json.dumps(address, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fact(
    key: str,
    section: str,
    text: str,
    *,
    subjects: set[str] | frozenset[str] = frozenset(),
    dependencies: set[str] | frozenset[str] = frozenset(),
    audience: set[str] | frozenset[str] = frozenset({"master"}),
    mandatory: bool = False,
) -> ContextFact:
    return ContextFact(
        key=key,
        section=section,
        text=text,
        subjects=frozenset(subjects),
        dependencies=frozenset(dependencies),
        audience=frozenset(audience),
        mandatory=mandatory,
    )


def _json(value, limit: int | None = None) -> str:
    text = json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)
    return text if limit is None else text[:limit]


def collect_context_snapshot(ctx, cfg, *, messages, memory, history) -> tuple[ContextFact, ...]:
    """Collect live world facts with stable keys and explicit dependencies.

    ``messages``, ``memory`` and ``history`` are accepted as part of the
    snapshot boundary so callers cannot accidentally read a different turn;
    only structured live-world facts are returned here.  The prompt builder
    receives memory/history separately as mandatory blocks.
    """
    del cfg, messages, memory, history
    world = ctx.world
    scene = world.scene
    viewers = getattr(ctx, "narration_viewer_ids", None)
    current_ids = set(viewers or getattr(world, "crew", set()) or world.characters)
    current_places = {
        world.place_of(world.characters[hero_id])
        for hero_id in current_ids
        if hero_id in world.characters and world.place_of(world.characters[hero_id])
    }
    if not current_places:
        fallback = getattr(world, "focus", None) or getattr(scene, "location_id", None)
        if fallback:
            current_places.add(fallback)
    current_place = sorted(current_places)[0] if current_places else None
    public_subjects: set[str] = set(viewers or ())
    viewer_places = {
        world.place_of(world.characters[hero_id])
        for hero_id in viewers or ()
        if hero_id in world.characters and world.place_of(world.characters[hero_id])
    }
    # A shared narration may only expose a place known to every listener.
    public_places = viewer_places if len(viewer_places) == 1 else set()
    public_subjects.update(public_places)
    public_subjects.update(
        entity.id
        for entity in world.entities.values()
        if entity.location_id in public_places
        and all(not concealed(entity, world.entities, world.revealed.get(hero_id, set())) for hero_id in viewers or ())
    )

    def public(subjects: set[str]) -> frozenset[str]:
        if viewers is not None and subjects & public_subjects:
            return frozenset({"master", "party"})
        return frozenset({"master"})

    facts: list[ContextFact] = []

    for hero in sorted(world.characters.values(), key=lambda item: item.id):
        if hero.status not in {"approved", "active", "dead"}:
            continue
        place = getattr(hero, "location_id", None) or current_place
        subjects = {hero.id, *(x for x in (place,) if x)}
        facts.append(
            _fact(
                f"hero:{hero.id}",
                "heroes",
                f"{hero.name} ({hero.id}); status={hero.status}; place={place or 'unknown'}",
                subjects=subjects,
                audience=public({hero.id}),
                mandatory=hero.id in getattr(world, "crew", set()),
            )
        )
        inventory = world.inventory.get(hero.id, [])
        if inventory:
            facts.append(
                _fact(
                    f"resource:{hero.id}",
                    "resources",
                    f"{hero.name} resources: " + ", ".join(world.item_name(item) for item in inventory),
                    subjects=subjects,
                )
            )

    for entity in sorted(world.entities.values(), key=lambda item: item.id):
        if entity.kind == "location":
            continue
        place = getattr(entity, "location_id", None)
        subjects = {entity.id, *(x for x in (place,) if x)}
        if viewers is None:
            state_text = _json(entity.state or {})
        else:
            from app.tools.runtime import public_entity

            state_text = _json(public_entity(entity))
        facts.append(
            _fact(
                f"target:{entity.id}",
                "targets",
                f"{entity.name} ({entity.id}); kind={entity.kind}; place={place or 'unknown'}; state={state_text}",
                subjects=subjects,
                audience=public({entity.id}),
            )
        )

    for current_place in sorted(current_places):
        place = world.entities.get(current_place)
        if place is not None:
            if viewers is None:
                place_state = place.state or {}
            else:
                from app.core.scene_presentation import scene_presentation

                place_state = scene_presentation(place).model_dump()
            facts.append(
                _fact(
                    f"place:{current_place}",
                    "places",
                    f"Current place {place.name} ({place.id}); state={_json(place_state)}",
                    subjects={current_place},
                    audience=public({current_place}),
                    mandatory=True,
                )
            )
    if not current_places:
        facts.append(
            _fact(
                "place:unknown",
                "places",
                "Current place is not assigned yet",
                audience=frozenset({"master", "party"}) if viewers is not None else frozenset({"master"}),
                mandatory=True,
            )
        )

    for origin in sorted(current_places):
        place = world.entities.get(origin)
        if place is None:
            continue
        for exit_ in location_exits(
            place, getattr(world, "catalog", None), world.entities, geography=getattr(world, "geography", None)
        ):
            entity = world.entities.get(exit_.target_id)
            if entity is None and not exit_.room_ref:
                continue
            visible = (
                origin in public_places
                and entity is not None
                and all(
                    not (entity.state or {}).get("secret")
                    or entity.id in world.revealed.get(hero_id, set())
                    or hero_id in (entity.state or {}).get("visited_by", ())
                    or world.place_of(world.characters[hero_id]) == entity.id
                    for hero_id in viewers or ()
                )
            )
            facts.append(
                _fact(
                    f"route:{origin}:{exit_.target_id or exit_.room_ref}",
                    "routes",
                    f"Reachable place {entity.name if entity is not None else exit_.label} "
                    f"({exit_.target_id or exit_.room_ref}) from {origin}",
                    subjects={origin, *(x for x in (exit_.target_id,) if x)},
                    audience={"master", "party"} if viewers is not None and visible else {"master"},
                )
            )

    for raw_effect in getattr(world, "effects", ()):
        if isinstance(raw_effect, tuple) and len(raw_effect) == 2:
            effect, record = raw_effect
        else:
            effect = raw_effect
            record = world.catalog.find(effect.effect_template_id, "effect_template")
        target = getattr(effect, "target_id", None)
        if not target:
            continue
        facts.append(
            _fact(
                f"effect:{effect.id}",
                "effects",
                f"Effect on {target}: {getattr(record, 'name', effect.effect_template_id)}; "
                f"stacks={effect.stacks}; expires_at={effect.expires_at}",
                subjects={target},
                audience=public({target}),
            )
        )

    for ref in getattr(ctx, "required_actions", ()):
        key = f"action_ref:{ref.source_id}:{ref.part}"
        facts.append(
            _fact(
                key,
                "requests",
                f"action_ref={key}; actor={ref.actor_id}; source={ref.source_kind}",
                subjects={ref.actor_id},
                audience=frozenset({"master", "party"}) if viewers is not None else frozenset({"master"}),
                mandatory=True,
            )
        )

    if world.plot:
        facts.append(
            _fact(
                "plot:live",
                "plot",
                f"Live plot state: {_json(world.plot)}",
                subjects=set(current_places),
            )
        )

    narrative_items: list[FactState] = []
    narrative_subjects: dict[str, set[str]] = {}
    for subject in sorted({*world.characters, *world.entities}):
        entity = world.entities.get(subject)
        subjects = (subject, getattr(entity, "template_id", None)) if entity is not None else (subject,)
        for item in world.narrative_facts(subjects):
            narrative_items.append(item)
            narrative_subjects.setdefault(fact_key(item.ref), {item.ref.subject_id}).add(subject)

    # A dependency may refer to a remote subject which is not present in the scene.
    # Resolve it through the same NarrativeView so instance/template override rules remain authoritative.
    pending = list(narrative_items)
    seen_narrative: set[str] = set()
    while pending:
        item = pending.pop(0)
        key = fact_key(item.ref)
        if key in seen_narrative:
            continue
        seen_narrative.add(key)
        value = getattr(item, "value", None) or getattr(item, "text", None)
        if value:
            facts.append(
                _fact(
                    key,
                    "reactions",
                    str(value),
                    subjects=narrative_subjects.get(key, {item.ref.subject_id}),
                    dependencies={fact_key(dep) for dep in item.depends_on},
                    audience=frozenset(getattr(item, "audience", ()) or {"master"}),
                )
            )
        view = getattr(world, "narrative_view", None)
        if view is not None:
            for dependency in item.depends_on:
                try:
                    pending.append(view.resolve(dependency))
                except KeyError:
                    # The selector will report an unknown dependency if no fact is available.
                    continue

    return tuple(facts)
