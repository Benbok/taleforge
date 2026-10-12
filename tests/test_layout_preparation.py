# ruff: noqa: F811
"""Подготовка комплекса (спецификация 2026-10-12, §3.2, §8): структура и геометрия фазами подготовки мира."""

import asyncio

from sqlalchemy import select

from app.core import sketch
from app.core.layout import store
from app.core.world_generation import storage
from app.core.world_generation.service import Orchestrator
from app.db.models import Entity, Event, WorldGenerationState
from app.gateway.coordination import InMemoryCoordination
from tests.game import import_base, party, quiet, run
from tests.layout_pilot import pilot_intent
from tests.test_map import _ok, _play
from tests.test_master import rows
from tests.test_world_generation import _fast_retry, _prepare, _row, _with_maker  # noqa: F401 — фикстура

WGS = WorldGenerationState


def _complex(settings, cid, mutate=None):
    """Деревня (текущая сцена), храм рядом и принятая подготовка комплекса по пилотному замыслу."""

    async def go(ctx):
        village = (await _ok(ctx, "create_location", {"name": "Деревня", "make_current": True}))["location_id"]
        temple = (await _ok(ctx, "create_location", {"name": "Старый храм", "link_to": [village]}))["location_id"]
        intent = pilot_intent(village).model_dump(mode="json")
        if mutate:
            mutate(intent)
        out = await _ok(ctx, "prepare_complex", {"location_id": temple, "intent": intent})
        return village, temple, out["operation_ref"]

    return _play(settings, cid, go)


def _areas(settings, temple) -> dict[str, Entity]:
    async def go(s):
        found = (await s.scalars(select(Entity).where(Entity.location_id == temple))).all()
        return {store.complex_of(e)["area_ref"]: e for e in found if store.complex_of(e)}

    return run(settings, go)


def _activate(settings, cid, area_id) -> str:
    async def go(s):
        row = await storage.find(s, cid, area_id, "location_geometry")
        storage.activate(row)
        await s.commit()
        return row.id

    return run(settings, go)


def _setup(client, admin, settings):
    import_base(settings)
    campaign, heads, hero = party(client, admin)
    quiet(client)
    return campaign["id"], heads, hero["id"]


def test_layout_publishes_areas_once(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    village, temple, ref = _complex(settings, cid)
    assert _prepare(settings, cid, ref) == "ready"
    areas = _areas(settings, temple)
    assert set(areas) == {"road", "brook", "narthex", "nave", "chapel", "sacristy", "vault", "crypt"}
    assert areas["vault"].state.get("secret") and areas["road"].name == "Дорога у храма"
    root = run(settings, lambda s: s.get(Entity, temple))
    assert store.blueprint_of(root).entry == "road" and store.area_ids(root) == {k: v.id for k, v in areas.items()}
    assert store.passage_live(root, "p_narthex") == {"state": "closed", "hidden": False}
    geometry = rows(settings, WGS, WGS.phase == "location_geometry")
    assert len(geometry) == 8 and all(g.status == "unprepared" and g.requested_at is None for g in geometry)
    assert _row(settings, ref).result_manifest["areas"] == {k: v.id for k, v in areas.items()}
    assert _prepare(settings, cid, ref) == "ready"

    async def again(ctx):
        return await _ok(ctx, "prepare_complex", {"location_id": temple,
                                                 "intent": pilot_intent(village).model_dump(mode="json")})  # fmt: skip

    assert _play(settings, cid, again)["operation_ref"] == ref
    assert len(_areas(settings, temple)) == 8 and len(rows(settings, Event, Event.tool == "prepare_layout")) == 1


def test_concurrent_layout_makes_one_blueprint(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    _village, temple, ref = _complex(settings, cid)

    async def both(maker):
        a, b = Orchestrator(InMemoryCoordination()), Orchestrator(InMemoryCoordination())
        return await asyncio.gather(a.prepare(maker, cid, ref), b.prepare(maker, cid, ref))

    outcomes = _with_maker(settings, both)
    assert "ready" in outcomes and set(outcomes) <= {"ready", "leased"}
    assert len(_areas(settings, temple)) == 8


def test_geometry_builds_sketch_and_keeps_manual(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    _village, temple, ref = _complex(settings, cid)
    _prepare(settings, cid, ref)
    areas = _areas(settings, temple)
    road_ref = _activate(settings, cid, areas["road"].id)
    assert _prepare(settings, cid, road_ref) == "ready"
    road = run(settings, lambda s: s.get(Entity, areas["road"].id))
    sk = road.state["sketch"]
    assert sk["blueprint"]["area_ref"] == "road" and sk["shape"] == "open" and sk["edges"]
    assert {x["passage_ref"] for x in sk["exits"]} == {"in_road_w", "p_brook", "p_narthex"}

    manual = {"shape": "room", "cols": 6, "rows": 4, "party": [3, 3], "walls": [], "exits": [], "features": []}

    async def draw(s):  # отряд не в притворе, поэтому sketch_place недоступен: ручной эскиз кладём как его результат
        narthex = await s.get(Entity, areas["narthex"].id)
        narthex.state = {**narthex.state, "sketch": {**manual, "edit_rev": 1}}
        await s.commit()

    run(settings, draw)
    narthex_ref = _activate(settings, cid, areas["narthex"].id)
    assert _prepare(settings, cid, narthex_ref) == "ready"
    assert _row(settings, narthex_ref).result_manifest["notes"] == ["manual_preserved"]
    narthex = run(settings, lambda s: s.get(Entity, areas["narthex"].id))
    assert "blueprint" not in narthex.state["sketch"] and narthex.state["sketch"]["party"] == [3, 3]


def test_unsatisfiable_layout_blocks_without_areas(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)

    def secret_crypt(intent):
        intent["parts"][-1]["secret"] = True

    _village, temple, ref = _complex(settings, cid, secret_crypt)
    assert _prepare(settings, cid, ref) == "blocked"
    assert _row(settings, ref).last_error == "layout_unsatisfiable"
    assert _areas(settings, temple) == {}


def test_location_initial_of_area_waits_for_its_geometry(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    _village, temple, ref = _complex(settings, cid)
    _prepare(settings, cid, ref)
    chapel = _areas(settings, temple)["chapel"].id

    async def resolve(ctx):
        return (await _ok(ctx, "resolve_location", {"location_id": chapel, "profile_id": "minimal"}))["operation_ref"]

    initial = _play(settings, cid, resolve)
    assert _prepare(settings, cid, initial) == "ready"
    geometry = run(settings, lambda s: storage.find(s, cid, chapel, "location_geometry"))
    assert geometry.status == "ready" and geometry.completed_at <= _row(settings, initial).completed_at
    chapel_sk = run(settings, lambda s: s.get(Entity, chapel)).state["sketch"]
    assert sketch.check(chapel_sk, {x["to"] for x in chapel_sk["exits"] if x["to"]}) == []
