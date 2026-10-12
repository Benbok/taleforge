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


def place(sk: dict, objects: list[tuple[str, str]], seed: int) -> tuple[dict, list[str]]:
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
        for i, (c, r) in enumerate(free[:MAX_TRIES]):
            feature = {"id": f"sf_{entity_id}"[:32], "entity_id": entity_id, "name": name, "kind": "object",
                       "cells": [[c, r, c, r]], "cover": "none", "hidden": False}  # fmt: skip
            trial = {**out, "features": [*features, feature]}
            if set(reach.reach_errors(trial)) <= baseline:
                features.append(feature)
                free.pop(i)
                break
        else:
            unplaced.append(entity_id)
    out["features"] = features
    return out, unplaced
