# ruff: noqa: F811
"""Обстановка участка на его геометрии (спецификация 2026-10-12, §3.4): связанные детали, проходы свободны."""

from app.core import positions as grid
from app.core import reach, sketch
from app.core.layout import furnish
from app.db.models import Entity
from tests.game import run
from tests.test_layout_passages import _built
from tests.test_map import _ok, _play
from tests.test_world_generation import _fast_retry, _generated, _prepare, _row  # noqa: F401 — фикстура

FIELD = {"shape": "room", "cols": 6, "rows": 5, "party": [0, 2], "walls": [], "features": [],
         "exits": [{"name": "Ворота", "side": "w", "at": 2, "kind": "gate", "state": "open", "cells": [[0, 2]]},
                   {"name": "Дверь", "side": "e", "at": 2, "kind": "door", "state": "open", "cells": [[5, 2]]}]}  # fmt: skip  # noqa: E501


def test_place_keeps_passages_free_and_is_deterministic():
    objects = [("en_a", "Сундук"), ("en_b", "Бочка"), ("en_c", "Скамья")]
    sk, unplaced = furnish.place(FIELD, objects, seed=3)
    assert unplaced == [] and sk == furnish.place(FIELD, objects, seed=3)[0]
    linked = [f for f in sk["features"] if f.get("entity_id")]
    assert [f["entity_id"] for f in linked] == ["en_a", "en_b", "en_c"]
    near_exits = {(c + dc, r + dr) for x in FIELD["exits"] for c, r in sketch.exit_cells(FIELD, x)
                  for dc in (-1, 0, 1) for dr in (-1, 0, 1)}  # fmt: skip
    assert not any(tuple(f["cells"][0][:2]) in near_exits for f in linked)
    assert reach.reach_errors(sk) == [] and sketch.check(sk, set()) == []


def test_crowded_area_leaves_objects_unplaced():
    tiny = {**FIELD, "cols": 3, "rows": 1, "party": [0, 0], "exits": []}
    sk, unplaced = furnish.place(tiny, [("en_a", "Сундук"), ("en_b", "Бочка")], seed=1)
    # 3×1, герой в клетке 0: первый объект встаёт в клетку 2,
    # для второго оставшаяся клетка не проходит проверку досягаемости
    assert unplaced == ["en_b"] and [f["entity_id"] for f in sk["features"]] == ["en_a"]


def test_generated_furnishing_is_bound_to_area_cells(client, admin, settings):
    cid, _h, _hid, _v, _t, ids = _built(client, admin, settings)

    async def resolve(ctx):
        ctx.campaign.settings = {**(ctx.campaign.settings or {}), "scene_generation": True}
        out = await _ok(
            ctx, "resolve_location", {"location_id": ids["chapel"], "profile_id": "scene_profile.warehouse"}
        )
        return out["operation_ref"]

    ref = _play(settings, cid, resolve)
    assert _prepare(settings, cid, ref) == "ready"
    made = _generated(settings, ref)
    chapel = run(settings, lambda s: s.get(Entity, ids["chapel"]))
    linked = {f["entity_id"] for f in chapel.state["sketch"]["features"] if f.get("entity_id")}
    notes = _row(settings, ref).result_manifest["notes"]
    assert made and {e.id for e in made} == linked | {n.split(":", 1)[1] for n in notes if n.startswith("unplaced:")}
    assert reach.reach_errors(chapel.state["sketch"]) == []

    moved = sorted(linked)[0]

    async def carry(ctx):
        ctx.world.entities[moved].location_id = ids["nave"]
        return [f.get("entity_id") for f in (grid._sketch(ctx.world, ids["chapel"]) or {}).get("features") or []]

    assert moved not in _play(settings, cid, carry)  # перенесённый объект не оставляет блокирующий рисунок


def test_existing_reach_error_does_not_block_new_objects():
    blocker = {"id": "sf_old", "entity_id": "en_old", "name": "Ящик", "kind": "object",
               "cells": [[5, 2, 5, 2]], "cover": "none", "hidden": False}  # fmt: skip
    base = {**FIELD, "features": [blocker]}
    before = reach.reach_errors(base)
    assert before  # выход уже загорожен прежней деталью
    sk, unplaced = furnish.place(base, [("en_a", "Сундук")], seed=2)
    assert unplaced == [] and set(reach.reach_errors(sk)) <= set(before)
    assert [f["entity_id"] for f in sk["features"]] == ["en_old", "en_a"]


def test_place_tries_a_bounded_number_of_cells(monkeypatch):
    calls = []
    monkeypatch.setattr(reach, "reach_errors", lambda sk: calls.append(1) or (["x"] if len(calls) > 1 else []))
    big = {**FIELD, "cols": 40, "rows": 30, "exits": []}
    _sk, unplaced = furnish.place(big, [("en_a", "Сундук")], seed=1)
    assert unplaced == ["en_a"] and len(calls) == 1 + furnish.MAX_TRIES


def test_plain_room_is_not_furnished():
    from types import SimpleNamespace

    from app.core.world_generation import storage

    for state in ({}, {"sketch": {**FIELD}}):
        place = SimpleNamespace(state=state)
        assert storage._furnish(place, [("en_a", "Сундук")], 1) == []
        assert place.state is state and place.state == state
