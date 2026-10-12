# ruff: noqa: F811
"""Пилот поставки 1 (спецификация 2026-10-12, §10): поле → храм → назад, устройство места сохраняется."""

from app.core import sketch
from app.core.layout import store
from app.core.layout.contracts import terrain_cells
from app.db.models import Character, Entity, WorldGenerationState
from tests.game import run
from tests.test_layout_passages import _built
from tests.test_layout_transit import _go
from tests.test_map import _ok, _play
from tests.test_master import rows
from tests.test_world_generation import _fast_retry  # noqa: F401 — фикстура

WGS = WorldGenerationState


def test_pilot_field_temple_and_back(client, admin, settings):
    cid, heads, hid, village, temple, ids = _built(client, admin, settings)
    head = heads[0]
    assert _go(client, head, cid, "in_road_w")["moved"]

    async def open_doors(ctx):
        await _ok(ctx, "edit_sketch", {"action": "open", "target": "Двери храма", "location_id": ids["road"]})

    _play(settings, cid, open_doors)
    for ref in ("p_narthex", "p_nave", "p_chapel"):
        out = _go(client, head, cid, ref)
        assert out["ok"] and out["moved"], out
    assert run(settings, lambda s: s.get(Character, hid)).location_id == ids["chapel"]
    layouts_before = len(rows(settings, WGS))
    ids_before = dict(ids)

    for ref in ("p_chapel", "p_nave", "p_narthex", "p_brook"):
        assert _go(client, head, cid, ref)["moved"]
    assert run(settings, lambda s: s.get(Character, hid)).location_id == ids["brook"]
    assert len(rows(settings, WGS)) == layouts_before  # возвращение не создаёт новых подготовок
    root = run(settings, lambda s: s.get(Entity, temple))
    assert store.area_ids(root) == ids_before

    road = run(settings, lambda s: s.get(Entity, ids["road"])).state["sketch"]
    brook = run(settings, lambda s: s.get(Entity, ids["brook"])).state["sketch"]
    assert road["environment"] == "outdoor" and not road["walls"] and "mask" not in road
    meanings = {(g["side"], g["meaning"]) for g in road["edges"]}
    assert ("e", "continuation") in meanings and ("w", "boundary") in meanings
    bp = store.blueprint_of(root)
    assert {(11, 3), (11, 4)} <= terrain_cells(bp.area("road"), "road")
    assert {(0, 3), (0, 4)} <= terrain_cells(bp.area("brook"), "road")
    assert any(t["kind"] == "bridge" for t in road["terrain"]) and brook["blueprint"]["area_ref"] == "brook"

    nave = run(settings, lambda s: s.get(Entity, ids["nave"])).state["sketch"]
    assert nave["walls"] == [[1, 2], [1, 6], [6, 2], [6, 6]]  # колонны — геометрия
    door = next(x for x in nave["exits"] if x["passage_ref"] == "p_nave")
    assert door["side"] == "s" and sketch.check(nave, {x["to"] for x in nave["exits"] if x["to"]}) == []
