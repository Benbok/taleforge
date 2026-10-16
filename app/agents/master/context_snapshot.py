"""Build deterministic, structured facts for the master decision prompt.

The snapshot is intentionally read-only.  It turns the already loaded live
world into small, addressable facts; narrative memory and chat history remain
separate prompt blocks until their selection policy is proven safe.
"""

from __future__ import annotations

import json

from app.agents.master.context_selection import ContextFact


def _fact(
    key: str,
    section: str,
    text: str,
    *,
    subjects: set[str] | frozenset[str] = frozenset(),
    dependencies: set[str] | frozenset[str] = frozenset(),
    mandatory: bool = False,
) -> ContextFact:
    return ContextFact(
        key=key,
        section=section,
        text=text,
        subjects=frozenset(subjects),
        dependencies=frozenset(dependencies),
        audience=frozenset({"master"}),
        mandatory=mandatory,
    )


def _json(value, limit: int = 1200) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, sort_keys=True)[:limit]


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
    current_place = getattr(world, "focus", None) or getattr(scene, "location_id", None)
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
                mandatory=hero.id in getattr(world, "crew", set()),
            )
        )
        inventory = world.inventory.get(hero.id, [])
        if inventory:
            facts.append(
                _fact(
                    f"resource:{hero.id}",
                    "resources",
                    f"{hero.name} resources: "
                    + ", ".join(world.item_name(item) for item in inventory),
                    subjects=subjects,
                )
            )

    for entity in sorted(world.entities.values(), key=lambda item: item.id):
        if entity.kind == "location":
            continue
        place = getattr(entity, "location_id", None)
        subjects = {entity.id, *(x for x in (place,) if x)}
        facts.append(
            _fact(
                f"target:{entity.id}",
                "targets",
                f"{entity.name} ({entity.id}); kind={entity.kind}; place={place or 'unknown'}; "
                f"state={_json(entity.state or {})}",
                subjects=subjects,
            )
        )

    if current_place:
        place = world.entities.get(current_place)
        if place is not None:
            facts.append(
                _fact(
                    f"place:{current_place}",
                    "places",
                    f"Current place {place.name} ({place.id}); state={_json(place.state or {})}",
                    subjects={current_place},
                    mandatory=True,
                )
            )
    else:
        facts.append(
            _fact(
                "place:unknown",
                "places",
                "Current place is not assigned yet",
                mandatory=True,
            )
        )

    for entity in sorted(world.entities.values(), key=lambda item: item.id):
        if entity.kind != "location" or entity.id == current_place:
            continue
        parent = getattr(entity, "location_id", None)
        if parent == current_place:
            facts.append(
                _fact(
                    f"route:{entity.id}",
                    "routes",
                    f"Reachable place {entity.name} ({entity.id}) from {current_place}",
                    subjects={current_place, entity.id},
                )
            )

    for effect, record in getattr(world, "effects", ()):
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
                mandatory=True,
            )
        )

    if world.plot:
        facts.append(
            _fact(
                "plot:live",
                "plot",
                f"Live plot state: {_json(world.plot, 6000)}",
                subjects={current_place} if current_place else set(),
            )
        )

    for subject in sorted({*world.characters, *world.entities}):
        for item in world.narrative_facts((subject,)):
            value = getattr(item, "value", None) or getattr(item, "text", None)
            if not value:
                continue
            facts.append(
                _fact(
                    f"reaction:{subject}:{getattr(item, 'key', 'fact')}",
                    "reactions",
                    str(value),
                    subjects={subject},
                )
            )

    return tuple(facts)
