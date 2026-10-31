"""Trim only model inputs. Authoritative context stays whole for server validation."""

import re
from copy import deepcopy
from dataclasses import asdict

from app.agents.master.prompting.lore import LORE_FIELDS, select_blocks, split_lore, stems


def lore_blocks(context: dict):
    world = context.get("world") or {}
    rules = context.get("world_rules") or {}
    return split_lore({**world, **rules})


def requested_lore(raw, context: dict) -> list[str]:
    requested = raw.get("need_lore") if isinstance(raw, dict) else None
    if not isinstance(requested, list):
        return []
    known = {block.id for block in lore_blocks(context)}
    return list(dict.fromkeys(key for key in requested[:4] if isinstance(key, str) and key in known))


EVIDENCE_BUDGET = 4000
RECENT_NARRATIONS = 2


def _headline(text: str) -> str:
    """The start of a narration, verbatim, so that a quotation taken from it is still found on the server."""
    first = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    return first if len(first) <= 120 else first[:120].rsplit(" ", 1)[0]


def bounded_evidence(parts: dict, source: str, budget: int = EVIDENCE_BUDGET) -> str:
    """Recent narrations in full, older ones as headlines, unless the player's words point at them.

    The server validates quotations against the whole evidence; this text is only what the model reads.
    """
    narrations = parts.get("narrations") or []  # newest first
    words = stems(source)
    head = (parts.get("place") or "")[:1200]
    recent = [text[:1500] for text in narrations[:RECENT_NARRATIONS]][::-1]
    room = budget - len(head) - sum(len(text) + 1 for text in recent)
    older = list(enumerate(narrations[RECENT_NARRATIONS:]))  # index grows with age
    chosen: dict[int, str] = {}
    for index, text in older:  # what the player points at, whole paragraphs, the newest first
        matched = [p[:700] for p in text.split("\n\n") if words and stems(p) & words]
        if matched and room > 0:
            line = "\n\n".join(matched)
            if len(line) + 1 <= room:
                chosen[index] = line
                room -= len(line) + 1
    for index, text in older:  # the rest by their first sentence
        if index in chosen:
            continue
        line = _headline(text)
        if line and len(line) + 1 <= room:
            chosen[index] = line
            room -= len(line) + 1
    ordered = [chosen[index] for index in sorted(chosen, reverse=True)]  # oldest first
    return "\n".join(text for text in [head, *ordered, *recent] if text)


def slice_context(context: dict, source: str, extra_blocks=()) -> dict:
    result = deepcopy(context)
    blocks = lore_blocks(context)
    index, selected = select_blocks(blocks, source, 1500)
    ids = {block.id for block in selected}
    selected.extend(block for block in blocks if block.id in extra_blocks and block.id not in ids)
    result["world_rules"] = {"lore_index": index, "lore": [asdict(block) for block in selected]}
    # The studio also carries copies of laws/powers/world: retaining it would bypass the budget.
    if "world" in result:
        result["world"] = {
            key: value
            for key, value in (context.get("world") or {}).items()
            if key not in LORE_FIELDS and key in {"name", "genre", "tone"}
        }
    words = stems(source)
    for key in ("objects", "inventory"):
        for item in result.get(key) or []:
            if stems(item.get("name", "")) & words:
                continue
            for description in ("description", "appearance"):
                if isinstance(item.get(description), str):
                    item[description] = item[description].split("\n", 1)[0]
    entities = (context.get("scene") or {}).get("entities") or []
    relevant = words | stems(" ".join(entity.get("name", "") for entity in entities))
    evidence = context.get("established_evidence") or ""
    parts = result.pop("evidence_parts", None)
    if parts is not None:
        result["established_evidence"] = bounded_evidence(parts, source)
    elif "established_evidence" in result:
        result["established_evidence"] = "\n\n".join(
            paragraph for paragraph in evidence.split("\n\n") if stems(paragraph) & relevant
        )
    hero = result.get("hero")
    if isinstance(hero, dict):
        compact = {
            key: value
            for key, value in hero.items()
            if key in {"id", "name", "abilities", "trained", "level", "rules_version", "schema_version"}
        }
        identity = (hero.get("description") or {}).get("identity")
        if identity:
            compact["description"] = {"identity": identity}
        result["hero"] = compact
    if "history" in result:
        result["history"] = [line[:400] if isinstance(line, str) else line for line in result["history"][-6:]]
    return result


def review_context(context: dict, raw_intent: dict, extra_blocks=()) -> dict:
    # Independent review must see the rules the first model might have overlooked.
    # These fields are the authority for permission, including restrictions beyond
    # an index summary or the lexical budget. Other lore still uses retrieval.
    normative = [block.id for block in lore_blocks(context) if block.id.split(":", 1)[0] in {"laws", "powers", "world"}]
    sliced = slice_context(context, context["source"], [*extra_blocks, *normative])
    return {
        "source": context["source"],
        "intent": raw_intent,
        "evidence": sliced.get("established_evidence", ""),
        "scene": sliced["scene"],
        "known_exits": sliced.get("known_exits", []),
        "world_rules": sliced["world_rules"],
        "objects": sliced.get("objects", []),
        "inventory": sliced.get("inventory", []),
    }


def slice_narration_context(public: dict) -> dict:
    """Called only after audience filtering. Never add private lore to narration."""
    result = deepcopy(public)
    result["recent_history"] = [
        line[:400] if isinstance(line, str) else line for line in result.get("recent_history", [])[-6:]
    ]
    return result
