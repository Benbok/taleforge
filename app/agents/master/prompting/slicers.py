"""Trim only model inputs. Authoritative context stays whole for server validation."""

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
    if "established_evidence" in result:
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
