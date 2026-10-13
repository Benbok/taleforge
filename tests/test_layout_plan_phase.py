# ruff: noqa: F811
"""Структура комплекса из мандата каркаса (спецификация 2026-10-12, §3.2, §8): детерминированно, один раз."""

import pytest

from app.core.layout import spatial, store
from app.core.world_generation import storage
from app.db.models import Campaign, Entity, WorldGenerationState
from tests.game import run
from tests.layout_pilot import pilot_intent
from tests.layout_plan_pilot import temple_mandate
from tests.test_layout_preparation import _areas, _setup
from tests.test_map import _ok, _play
from tests.test_world_generation import _fast_retry, _prepare, _row  # noqa: F401 — фикстура


def _plan_root(settings, cid, mandate=None):
    async def go(ctx):
        root = (await _ok(ctx, "create_location", {"name": "Старый храм"}))["location_id"]
        campaign = await ctx.session.get(Campaign, cid)
        row = await store.reserve_plan_layout(
            ctx.session, campaign, ctx.world.entities[root], mandate or temple_mandate()
        )
        storage.activate(row)
        return root, row.id

    return _play(settings, cid, go)


def test_mandate_builds_complex_once(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    root, ref = _plan_root(settings, cid)
    assert _prepare(settings, cid, ref) == "ready"
    row = _row(settings, ref)
    assert row.quality == "normal" and row.reservation["source"] == "plan" and row.llm_attempt_count == 0
    areas = _areas(settings, root)
    assert set(areas) == {"road", "narthex", "nave", "chapel", "crypt", "vault"}
    bp = store.blueprint_of(run(settings, lambda s: s.get(Entity, root)))
    assert bp.anchors["clue_relic"] == "chapel" and bp.anchors["npc:npc_warden"] == "road"
    before = dict(row.reservation)

    async def again(ctx):
        campaign = await ctx.session.get(Campaign, cid)
        return (await store.reserve_plan_layout(ctx.session, campaign, ctx.world.entities[root], temple_mandate())).id

    assert _play(settings, cid, again) == ref and _row(settings, ref).reservation == before


def test_broken_mandate_blocks_without_areas(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    root, ref = _plan_root(settings, cid)

    async def corrupt(s):
        row = await s.get(WorldGenerationState, ref)
        row.reservation = {**row.reservation, "mandate": {"place": "x"}}
        await s.commit()

    run(settings, corrupt)
    assert _prepare(settings, cid, ref) == "blocked"
    assert _row(settings, ref).last_error == "unsupported_source" and _areas(settings, root) == {}


def test_impossible_candidates_block(client, admin, settings, monkeypatch):
    cid, _heads, _hid = _setup(client, admin, settings)
    root, ref = _plan_root(settings, cid)
    impossible = pilot_intent().model_copy(deep=True)
    impossible.parts[-1].secret = True  # обязательная крипта за тайным ходом: как в поставке 1
    monkeypatch.setattr(spatial, "intent_candidates", lambda m: [impossible])
    assert _prepare(settings, cid, ref) == "blocked"
    assert _row(settings, ref).last_error == "layout_unsatisfiable" and _areas(settings, root) == {}


def test_later_candidate_is_fallback(client, admin, settings, monkeypatch):
    cid, _heads, _hid = _setup(client, admin, settings)
    root, ref = _plan_root(settings, cid)
    real = spatial.intent_candidates
    impossible = pilot_intent().model_copy(deep=True)
    impossible.parts[-1].secret = True
    monkeypatch.setattr(spatial, "intent_candidates", lambda m: [impossible, *real(m)])
    assert _prepare(settings, cid, ref) == "ready"
    row = _row(settings, ref)
    assert row.quality == "fallback" and "fallback:layout" in row.result_manifest["notes"]


def test_home_of_resolves_area_or_keeps_place(client, admin, settings):
    cid, _heads, _hid = _setup(client, admin, settings)
    root, ref = _plan_root(settings, cid)
    entities = run(settings, lambda s: _all(s, cid))
    assert store.home_of(entities, root, "npc:npc_warden") == root  # blueprint ещё нет
    _prepare(settings, cid, ref)
    entities = run(settings, lambda s: _all(s, cid))
    areas = _areas(settings, root)
    assert store.home_of(entities, root, "npc:npc_warden") == areas["road"].id
    assert store.home_of(entities, root, "npc:stranger") == areas["road"].id  # неизвестный — во вход
    assert store.home_of(entities, None, "npc:x") is None


async def _all(s, cid):
    from sqlalchemy import select

    return {e.id: e for e in await s.scalars(select(Entity).where(Entity.campaign_id == cid))}


def test_host_intent_path_is_unchanged(client, admin, settings):
    from tests.test_layout_preparation import _complex

    cid, _heads, _hid = _setup(client, admin, settings)
    _village, temple, ref = _complex(settings, cid)
    assert _prepare(settings, cid, ref) == "ready" and _row(settings, ref).quality == "normal"
    assert len(_areas(settings, temple)) == 8


@pytest.fixture(autouse=True)
def _quiet_retry(_fast_retry):  # noqa: F811
    yield
