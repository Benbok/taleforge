"""Обстановка участка на его геометрии (спецификация 2026-10-12, §3.4): интерактивный объект — сущность мира, на
эскизе он — связанная деталь в одну клетку, второго объекта рисунок не создаёт. Клетки у проходов и точка входа
участка свободны; каждая расстановка проверяется досягаемостью (app/core/reach.py), поэтому объект не отрезает
выходы и к нему можно подойти. Не поместившийся объект остаётся в мире без клетки — диагностика в manifest.
"""

from __future__ import annotations

import copy
import random

from app.core import reach, sketch

MAX_TRIES = 48  # кандидатов на объект: каждая проверка досягаемости — несколько обходов, транзакция не безгранична


def place(sk: dict, objects: list[tuple[str, str]], seed: int, *, slots: list[dict] | None = None,
          roles: dict[str, str] | None = None,
          sizes: dict[str, tuple[int, int]] | None = None) -> tuple[dict, list[str]]:
    floor = sketch.floor_cells(sk) or {(c, r) for c in range(sk["cols"]) for r in range(sk["rows"])}
    keep = {tuple(sk["party"])}
    for x in sk.get("exits") or []:
        for c, r in sketch.exit_cells(sk, x):
            keep |= {(c + dc, r + dr) for dc in (-1, 0, 1) for dr in (-1, 0, 1)}
    free = sorted(c for c in floor if c not in reach.blocked_cells(sk) and c not in keep)
    random.Random(seed).shuffle(free)
    out = copy.deepcopy(sk)
    features = list(out.get("features") or [])
    unplaced: list[str] = []
    baseline = set(reach.reach_errors(out))  # прежние замечания рисунка не мешают, новых размещение не добавляет
    for entity_id, name in objects:
        width, height = (sizes or {}).get(entity_id, (1, 1))
        if width < 1 or height < 1:
            unplaced.append(entity_id)
            continue
        if any(f.get("entity_id") == entity_id for f in features):
            continue
        bound = False
        for slot in sorted(slots or [], key=lambda s: s["slot_ref"]):
            if slot.get("hidden") or slot.get("role") != (roles or {}).get(entity_id, "prop"):
                continue
            if width > slot.get("max_cols", 1) or height > slot.get("max_rows", 1):
                continue
            if any(f.get("slot_ref") == slot["slot_ref"] and f.get("entity_id") for f in features):
                continue
            footprint = _cells(slot.get("cells") or [])
            original = next((f for f in features if f["id"] == slot.get("feature_id")), None)
            if original is None and slot.get("detail_ref"):
                original = next((f for f in features if f["id"] == slot["detail_ref"]), None)
            if original is not None and original.get("entity_id"):
                continue
            if original is None and len(features) >= sketch.MAX_FEATURES:
                continue
            occupied = set().union(*(_cells(f.get("cells") or []) for f in features if f is not original))
            if not footprint or not footprint <= floor or footprint & (occupied | keep | set(
                    map(tuple, sk.get("walls") or []))):
                continue
            feature = {**(original or {}), "id": (original or {}).get("id", f"sf_{entity_id}"[:32]),
                       "entity_id": entity_id, "name": name, "kind": "object", "cells": slot["cells"],
                       "cover": "none", "hidden": False, "slot_ref": slot["slot_ref"]}
            trial_features = [f for f in features if f is not original] + [feature]
            if set(reach.reach_errors({**out, "features": trial_features})) <= baseline:
                features = trial_features
                out["features"] = features
                bound = True
                break
        if bound:
            continue
        occupied = set().union(*(_cells(f.get("cells") or []) for f in features))
        if len(features) >= sketch.MAX_FEATURES:
            unplaced.append(entity_id)
            continue
        candidates = [cell for cell in free if cell not in occupied]
        for c, r in candidates[:MAX_TRIES]:
            cells = [[c, r, c + width - 1, r + height - 1]]
            footprint = _cells(cells)
            if not footprint <= floor or footprint & (occupied | keep | reach.blocked_cells(out)):
                continue
            feature = {"id": f"sf_{entity_id}"[:32], "entity_id": entity_id, "name": name, "kind": "object",
                       "cells": cells, "cover": "none", "hidden": False}  # fmt: skip
            trial = {**out, "features": [*features, feature]}
            if set(reach.reach_errors(trial)) <= baseline:
                features.append(feature)
                free.remove((c, r))
                break
        else:
            unplaced.append(entity_id)
    out["features"] = features
    return out, unplaced


def _cells(rects: list) -> set[tuple[int, int]]:
    return {(c, r) for c0, r0, c1, r1 in rects for c in range(c0, c1 + 1) for r in range(r0, r1 + 1)}


def sync_objects(ctx, inverse: list, *, include: set[str] | None = None) -> None:
    """Refresh live bindings at the event boundary; observation alone updates remembered maps."""
    entities = ctx.world.entities
    linked = {f["entity_id"] for e in entities.values() if e.kind == "location"
              for f in ((e.state or {}).get("sketch") or {}).get("features", []) if f.get("entity_id")}
    wanted = linked | (include or set())
    sizes = {}
    for room in entities.values():
        for feature in ((room.state or {}).get("sketch") or {}).get("features", []):
            if feature.get("entity_id") and feature.get("cells"):
                cells = _cells(feature["cells"])
                sizes[feature["entity_id"]] = (max(c for c, _ in cells) - min(c for c, _ in cells) + 1,
                                                max(r for _, r in cells) - min(r for _, r in cells) + 1)
    for entity in entities.values():
        if entity.kind == "object" and ((entity.state or {}).get("world_object") or {}).get("generation_ref"):
            wanted.add(entity.id)

    def on_floor(entity, room_id):
        if entity is None or entity.location_id != room_id:
            return False
        st = entity.state or {}
        obj = st.get("world_object") or {}
        return not (obj.get("container_id") or obj.get("physical") == "destroyed" or st.get("hidden")
                    or st.get("secret"))

    for room in list(entities.values()):
        sk = (room.state or {}).get("sketch")
        if room.kind != "location" or not isinstance(sk, dict) or not sk.get("blueprint"):
            continue
        features = [f for f in sk.get("features", []) if not f.get("entity_id")
                    or on_floor(entities.get(f["entity_id"]), room.id)]
        present = {f["entity_id"] for f in features if f.get("entity_id")}
        objects = [entities[key] for key in sorted(wanted) if key not in present
                   and on_floor(entities.get(key), room.id)]
        roles = {e.id: ((e.state or {}).get("world_object") or {}).get("role", "prop") for e in objects}
        new, _ = place({**sk, "features": features}, [(e.id, e.name) for e in objects],
                       0, slots=(room.state or {}).get("object_slots"), roles=roles, sizes=sizes)
        if new == sk:
            continue
        inverse.append({"table": "entities", "id": room.id, "field": "state", "before": copy.deepcopy(room.state)})
        room.state = {**room.state, "sketch": {**new, "edit_rev": int(sk.get("edit_rev") or 0) + 1},
                      "placement_rev": int(room.state.get("placement_rev") or 0) + 1}
        ctx.signals.add("map.changed")
