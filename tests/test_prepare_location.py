# ruff: noqa: F811
"""Явная подготовка места ведущим (спецификация 2026-10-12, §8): структура, геометрия и по желанию обстановка
всех участков без раскрытия и без перемещения героев."""

from app.db.models import MapMemory, WorldGenerationState
from app.tools.registry import execute
from tests.test_layout_develop import _campaign, _develop
from tests.test_map import _play
from tests.test_master import rows
from tests.test_world_generation import _fast_retry, _prepare  # noqa: F401 — фикстура

WGS = WorldGenerationState


def _prep(settings, cid, location_id, **kw):
    return _play(settings, cid, lambda ctx: execute(ctx, "prepare_location", {"location_id": location_id, **kw}))


def test_two_calls_prepare_structure_then_all_geometry(client, admin, settings):
    cid = _campaign(client, admin, settings)  # флаг выключен: ведущий готовит явно
    place = _develop(settings, cid)
    first = _prep(settings, cid, place["entity_id"])
    assert first["ok"] and not first["result"]["blueprint_ready"]
    assert _prepare(settings, cid, first["result"]["structure"]["operation_ref"]) == "ready"
    second = _prep(settings, cid, place["entity_id"])["result"]
    geometry = rows(settings, WGS, WGS.phase == "location_geometry")
    assert len(geometry) == 6 and all(g.requested_at for g in geometry)
    assert second["operation_refs"][0] == first["result"]["structure"]["operation_ref"]
    assert set(second["operation_refs"][1:]) == {g.id for g in geometry}
    assert not rows(settings, WGS, WGS.phase == "location_initial") and not rows(settings, MapMemory)
    assert second["estimate"] == {"structure_calls_max": 0, "furnish_calls_max": 0}


def test_furnish_reserves_every_area_and_estimates_calls(client, admin, settings):
    cid = _campaign(client, admin, settings, scene_generation=True, scene_generation_llm=True,
                    location_layouts_llm=True)  # fmt: skip
    place = _develop(settings, cid)
    structure = _prep(settings, cid, place["entity_id"])["result"]
    assert structure["estimate"]["structure_calls_max"] == 2
    _prepare(settings, cid, structure["structure"]["operation_ref"])
    out = _prep(settings, cid, place["entity_id"], furnish=True)["result"]
    initial = rows(settings, WGS, WGS.phase == "location_initial")
    assert len(initial) == 6
    activated = [r for r in initial if r.requested_at is not None]  # профиль, не прошедший проверку, — blocked
    assert out["estimate"]["furnish_calls_max"] == 2 * len(activated)


def test_refuses_visited_books_and_places_without_space(client, admin, settings):
    cid = _campaign(client, admin, settings)
    visited = _develop(settings, cid, here=True)
    assert "посещ" in _prep(settings, cid, visited["entity_id"])["error"]
    tavern = _develop(settings, cid, sketch_id="loc_tavern")
    assert "пространств" in _prep(settings, cid, tavern["entity_id"])["error"]


def test_ai_master_does_not_see_it():
    from app.tools.master.generation import HOST_TOOLS

    assert {"prepare_location", "preparation_cost"} <= HOST_TOOLS
