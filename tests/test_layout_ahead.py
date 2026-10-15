# ruff: noqa: F811
"""Подготовка вперёд (спецификация 2026-10-12, §8): геометрия до двух соседей, без модели и без раскрытия."""


from app.core.world_generation import storage
from app.core.world_generation.service import Orchestrator
from app.db.models import MapMemory, WorldGenerationState
from app.gateway.coordination import InMemoryCoordination
from tests.game import run
from tests.test_layout_passages import _built, _enter
from tests.test_layout_transit import (
    _do_not_run_master_for_unrelated_transit_tests,  # noqa: F401
    _go,
)
from tests.test_map import _map, _play
from tests.test_master import rows
from tests.test_world_generation import _fast_retry, _with_maker  # noqa: F401 — фикстура

WGS = WorldGenerationState


def _geo(settings, cid, area_id):
    return run(settings, lambda s: storage.find(s, cid, area_id, "location_geometry"))


def test_arrival_requests_geometry_of_at_most_two_neighbours(client, admin, settings):
    cid, heads, _hid, _village, _temple, ids = _built(client, admin, settings)
    assert _go(client, heads[0], cid, "in_road_w")["moved"]  # road: соседи brook и narthex
    requested = {k for k, v in ids.items() if _geo(settings, cid, v).requested_at is not None}
    assert requested <= {"road", "brook", "narthex"} and {"brook", "narthex"} <= requested
    assert _geo(settings, cid, ids["nave"]).requested_at is None
    assert not [
        r
        for r in rows(settings, WGS, WGS.phase == "location_initial")
        if r.target_entity_id in (ids["brook"], ids["narthex"])
    ]


def test_secret_neighbour_is_never_prepared_ahead(client, admin, settings):
    cid, heads, hid, _village, _temple, ids = _built(client, admin, settings)
    _play(settings, cid, lambda ctx: _enter(ctx, hid, ids["nave"]))  # мастер ставит героя в неф
    out = _go(client, heads[0], cid, "p_sacristy")  # ризница: соседи — неф и тайник за тайной дверью
    assert out["moved"] and out["area_id"] == ids["sacristy"]
    assert _geo(settings, cid, ids["vault"]).requested_at is None


def test_prepared_neighbour_stays_unknown_to_players(client, admin, settings):
    cid, heads, _hid, _village, _temple, ids = _built(client, admin, settings)
    assert _go(client, heads[0], cid, "in_road_w")["moved"]
    _with_maker(settings, lambda maker: Orchestrator(InMemoryCoordination()).run_due(maker))
    assert _geo(settings, cid, ids["narthex"]).status == "ready"
    packet = _map(client, heads[0], cid)
    outline = next(a for a in packet["location_map"]["areas"] if a["id"] == ids["narthex"])
    assert outline["status"] == "prepared"
    assert outline["sketch"]["features"] == [] and outline["sketch"]["exits"] == []
    assert {m.entity_id for m in rows(settings, MapMemory)} == {ids["road"]}
