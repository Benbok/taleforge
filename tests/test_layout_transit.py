# ruff: noqa: F811
"""Переход между участками (спецификация 2026-10-12, §5, §7, §8): сначала подготовка, потом проверка и шаг."""

import pytest

from app.core.layout import transit
from app.db.models import Character
from tests.game import run
from tests.test_layout_passages import _built
from tests.test_map import _play
from tests.test_world_generation import _fast_retry, _prepare  # noqa: F401 — фикстура
from tests.test_ws import connect, next_of


@pytest.fixture(autouse=True)
def _do_not_run_master_for_unrelated_transit_tests(client, monkeypatch):
    monkeypatch.setattr(client.app.state.master, "notify", lambda _campaign_id: None)


def _go(client, head, cid, ref):
    with connect(client, head, cid) as (ws, _):
        ws.send_json({"type": "map.traverse", "payload": {"passage_ref": ref, "request_id": "r1"}})
        return next_of(ws, "map.traverse.result")["payload"]


def _place(settings, hid):
    return run(settings, lambda s: s.get(Character, hid)).location_id


def test_finish_rechecks_the_hero(client, admin, settings, monkeypatch):
    cid, heads, hid, _v, _t, ids = _built(client, admin, settings)

    async def begin(ctx):
        return (await transit.begin(ctx, [hid], "in_road_w", [], by_player=True)).to_json()

    req = _play(settings, cid, begin)
    assert req["by_player"]
    monkeypatch.setattr(transit.mod, "can_act", lambda _m: "condition.stunned")

    async def finish(ctx):
        return await transit.finish(ctx, transit.Request.from_json(req))

    out = _play(settings, cid, finish)
    assert not out["moved"] and "не может двигаться" in out["reason"]
    assert _place(settings, hid) != ids["road"]


def test_initial_transaction_failure_answers_player(client, admin, settings, monkeypatch):
    from tests.test_world_generation import _with_maker

    cid, _heads, hid, village, _t, _ids = _built(client, admin, settings)

    async def broken(*args, **kwargs):
        raise RuntimeError("сбой записи")

    monkeypatch.setattr(transit, "begin", broken)

    async def go(maker):
        return await transit.traverse(maker, None, client.app.state.dice_factory, cid, hid, "in_road_w")

    out, published = _with_maker(settings, go)
    assert out == {"ok": False, "error": "переход не удался"} and published == []
    assert _place(settings, hid) is None


@pytest.mark.parametrize("failure", ["get_viewer", "viewer_hero"])
def test_viewer_failure_answers_player(client, admin, settings, monkeypatch, failure):
    from types import SimpleNamespace

    from app.core import inspect
    from app.gateway import ws

    cid, _heads, _hid, _v, _t, _ids = _built(client, admin, settings)
    sent = []

    async def send(event):
        sent.append(event)

    async def broken(*args, **kwargs):
        raise RuntimeError("сбой чтения зрителя")

    async def viewer(*args, **kwargs):
        return SimpleNamespace()

    monkeypatch.setattr(ws, "get_viewer", broken if failure == "get_viewer" else viewer)
    monkeypatch.setattr(inspect, "viewer_hero", broken)
    conn = SimpleNamespace(campaign_id=cid, send=send)
    client.portal.call(ws._traverse, client.app, None, conn, {"passage_ref": "in_road_w", "request_id": "r1"})
    assert len(sent) == 1 and sent[0]["type"] == "map.traverse.result"
    assert sent[0]["payload"] == {"request_id": "r1", "ok": False, "error": "переход не удался"}


@pytest.mark.parametrize("failure", ["not_found", "no_hero"])
def test_traverse_refusal_is_sent_after_read_transaction_closes(client, admin, settings, monkeypatch, failure):
    from contextlib import asynccontextmanager
    from types import SimpleNamespace

    from app.core import inspect
    from app.core.campaigns import NotFound
    from app.gateway import ws

    cid, _heads, _hid, _v, _t, _ids = _built(client, admin, settings)
    original = client.app.state.sessionmaker
    active, sent, transactions = [], [], []

    @asynccontextmanager
    async def maker():
        async with original() as s:
            active.append(s)
            try:
                yield s
            finally:
                active.remove(s)

    async def viewer(session, *args):
        from app.db.models import Campaign

        await session.get(Campaign, cid)  # реальная read transaction
        if failure == "not_found":
            raise NotFound("кампания недоступна")
        return SimpleNamespace()

    async def no_hero(*args):
        return None

    async def send(event):
        sent.append(event)
        transactions.append(any(s.in_transaction() for s in active))

    monkeypatch.setattr(client.app.state, "sessionmaker", maker)
    monkeypatch.setattr(ws, "get_viewer", viewer)
    monkeypatch.setattr(inspect, "viewer_hero", no_hero)
    conn = SimpleNamespace(campaign_id=cid, send=send)
    client.portal.call(ws._traverse, client.app, None, conn, {"passage_ref": "in_road_w", "request_id": "refused"})
    assert len(sent) == 1 and sent[0]["payload"]["ok"] is False
    assert transactions == [False]
