"""Deterministic selection of context facts for each master role.

The selector is deliberately independent of the database and the model.  Callers
turn existing world, action, and narrative structures into ``ContextFact`` rows;
this module only applies visibility, subject relevance, and dependency closure.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextFact:
    key: str
    section: str
    text: str
    subjects: frozenset[str]
    dependencies: frozenset[str]
    audience: frozenset[str]
    mandatory: bool = False


@dataclass(frozen=True)
class ContextSelection:
    facts: tuple[ContextFact, ...]
    expansion_reasons: tuple[str, ...] = ()


def _visible(fact: ContextFact, *, role: str, audience: frozenset[str]) -> bool:
    if role == "decide":
        # The master may use both private and public facts.  Public audience
        # markers (``party`` or a character id) do not make a fact unavailable
        # to the decision stage.
        return True
    return bool(fact.audience & audience)


def select_context(
    facts: tuple[ContextFact, ...],
    *,
    role: str,
    subjects: frozenset[str],
    audience: frozenset[str],
    uncertain: bool = False,
) -> ContextSelection:
    """Select relevant facts and close their declared dependencies.

    An unknown dependency is treated conservatively: all facts in that section
    remain available, because dropping one could hide a rule or consequence.
    """
    by_key = {fact.key: fact for fact in facts}
    selected: set[str] = set()
    reasons: list[str] = []

    if uncertain:
        selected.update(fact.key for fact in facts if _visible(fact, role=role, audience=audience))
        reasons.append("uncertain_request")
    else:
        for fact in facts:
            related = not fact.subjects or bool(fact.subjects & subjects)
            if (fact.mandatory or related) and _visible(fact, role=role, audience=audience):
                selected.add(fact.key)

    pending = list(selected)
    while pending:
        key = pending.pop()
        fact = by_key.get(key)
        if fact is None:
            continue
        for dependency in fact.dependencies:
            dep = by_key.get(dependency)
            if dep is None:
                marker = f"unknown_dependency:{dependency}"
                if marker not in reasons:
                    reasons.append(marker)
                for candidate in facts:
                    if candidate.section == fact.section and _visible(candidate, role=role, audience=audience):
                        if candidate.key not in selected:
                            selected.add(candidate.key)
                            pending.append(candidate.key)
                continue
            if _visible(dep, role=role, audience=audience) and dep.key not in selected:
                selected.add(dep.key)
                pending.append(dep.key)

    ordered = tuple(fact for fact in facts if fact.key in selected)
    return ContextSelection(ordered, tuple(reasons))


async def collect_decision_facts(ctx, cfg, inputs: dict) -> tuple[ContextFact, ...]:
    """Adapt already assembled structured facts without making an LLM call.

    Integrators may provide ``context_facts`` directly.  The request is always
    retained as a mandatory fact so an uncertain parser cannot erase player text.
    """
    provided = tuple(inputs.get("context_facts") or ())
    facts = [item for item in provided if isinstance(item, ContextFact)]
    request = inputs.get("request")
    if isinstance(request, str) and request:
        facts.append(
            ContextFact(
                key="request",
                section="request",
                text=request,
                subjects=frozenset(inputs.get("subjects") or ()),
                dependencies=frozenset(),
                audience=frozenset({"master", "party"}),
                mandatory=True,
            )
        )
    return tuple(facts)

