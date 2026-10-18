"""Explicit reference adapters for the adventure bundle.

Every structure that can hold a world id is listed here. Nothing replaces ids by regex over free text:
a known id is replaced only where an adapter says that field holds one, and a leak scan afterwards
refuses to publish if any source id is still present anywhere in the bundle.
"""

import re
from typing import Any

TEXT_REF = re.compile(r"\[\[([^|\]]+)\|([^\]]*)\]\]")

# Entity.state keys copied verbatim: they hold no ids.
PLAIN_STATE = {
    "attitude", "hp", "hp_max", "plot_id", "role", "secret", "display_name", "item", "item_ref", "qty", "dc",
    "visual_key", "route_ports", "passages", "unique", "cell", "mask",
}  # fmt: skip
ADAPTED_STATE = {"areas", "complex", "blueprint", "sketch", "links", "world_object"}


class UnsupportedReference(Exception):
    def __init__(self, where: str):
        super().__init__(where)
        self.where = where


class RefMap:
    """Source id -> logical ref for entities and generation rows; the only place ids are translated."""

    def __init__(self) -> None:
        self.entities: dict[str, str] = {}
        self.generations: dict[str, str] = {}

    def entity(self, source: str | None) -> str | None:
        return None if source is None else self.entities.get(source)

    def known(self) -> set[str]:
        return {*self.entities, *self.generations}


def remap(value: Any, ids: dict[str, str]) -> Any:
    """Replace strings that are exactly a known id. Used only inside adapter-approved structures."""
    if isinstance(value, str):
        return ids.get(value, value)
    if isinstance(value, list):
        return [remap(v, ids) for v in value]
    if isinstance(value, dict):
        return {k: remap(v, ids) for k, v in value.items()}
    return value


def _blueprint(raw: dict, refs: RefMap) -> dict:
    """Blueprint external ends point at Entity ids through ``place_id``; internal areas use area refs."""

    def walk(node: Any) -> Any:
        if isinstance(node, dict):
            return {
                k: (refs.entities.get(v, v) if k == "place_id" and isinstance(v, str) else walk(v))
                for k, v in node.items()
            }
        if isinstance(node, list):
            return [walk(v) for v in node]
        return node

    return walk(raw)


def adapt_state(state: dict, refs: RefMap) -> dict:
    out: dict[str, Any] = {}
    for key, value in (state or {}).items():
        if key == "areas":
            out[key] = {ref: refs.entities.get(i, i) for ref, i in (value or {}).items()}
        elif key == "complex":
            out[key] = {**value, "root_id": refs.entities.get(value.get("root_id"), value.get("root_id"))}
        elif key == "blueprint":
            out[key] = _blueprint(value, refs)
        elif key == "sketch":
            sketch = dict(value)
            sketch["exits"] = [
                {**x, "to": refs.entities.get(x.get("to"), x.get("to"))} for x in sketch.get("exits") or []
            ]
            if isinstance(sketch.get("blueprint"), dict):
                bp = dict(sketch["blueprint"])
                bp["root_id"] = refs.entities.get(bp.get("root_id"), bp.get("root_id"))
                sketch["blueprint"] = bp
            out[key] = sketch
        elif key == "links":
            out[key] = [
                {**x, "to": refs.entities.get(x.get("to"), x.get("to"))} if isinstance(x, dict) else x
                for x in value or []
            ]
        elif key == "world_object":
            wo = dict(value)
            if wo.get("container_id"):
                wo["container_id"] = refs.entities.get(wo["container_id"], wo["container_id"])
            if wo.get("generation_ref"):
                wo["generation_ref"] = refs.generations.get(wo["generation_ref"], wo["generation_ref"])
            out[key] = wo
        elif key in PLAIN_STATE or not isinstance(value, (dict, list)):
            out[key] = value  # scalars hold no structure; the leak scan still checks their text
        else:
            raise UnsupportedReference(f"entity.state.{key}")  # unknown structured field: block, do not guess
    return out


def adapt_text(text: str, refs: RefMap) -> str:
    """Only the explicit ``[[id|name]]`` markup is rewritten, and only for ids this bundle knows."""
    return TEXT_REF.sub(lambda m: f"[[{refs.entities.get(m.group(1), m.group(1))}|{m.group(2)}]]", text or "")


def adapt_plot(plot: dict, refs: RefMap) -> dict:
    """Plot objects carry entity ids in ``entity_id`` fields; everything else is authored text and plot refs."""
    ids = {**refs.entities}

    def walk(node: Any, key: str = "") -> Any:
        if isinstance(node, dict):
            return {k: walk(v, k) for k, v in node.items()}
        if isinstance(node, list):
            return [walk(v, key) for v in node]
        if isinstance(node, str):
            if key == "entity_id":
                return ids.get(node, node)
            return adapt_text(node, refs)
        return node

    return walk(plot)


def find_leaks(value: Any, source_ids: set[str], path: str = "") -> list[str]:
    """Paths of string values that still equal a workspace id."""
    found: list[str] = []
    if isinstance(value, str):
        if value in source_ids:
            found.append(path)
        elif TEXT_REF.search(value):
            found.extend(path for m in TEXT_REF.finditer(value) if m.group(1) in source_ids)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            found.extend(find_leaks(item, source_ids, f"{path}[{i}]"))
    elif isinstance(value, dict):
        for key, item in value.items():
            found.extend(find_leaks(item, source_ids, f"{path}.{key}"))
            if isinstance(key, str) and key in source_ids:
                found.append(f"{path}.{key}")
    return found
