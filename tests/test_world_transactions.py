# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Поставка 2 генерации сцен: ревизия мира и guard записи, граница хода с checkpoint, восстановление описания,
квитанции и статус подготовки (docs/world-objects-delivery2.md; спецификация 2026-10-11, §6.1, §6.2, §6.4)."""

import asyncio
from datetime import UTC, datetime

import pytest

from app.core import world_tx
from app.core.chat import system_message
from app.core.world_tx import WorldConflict
from app.db.models import Campaign, Character, Entity, Event, MasterTurn, Seat, WorldGenerationState
from app.db.session import make_engine, make_sessionmaker
from app.rules.dice import Dice
from app.tools.registry import execute
from app.tools.runtime import open_context
from tests.game import import_base, ok, party, run
from tests.test_api import make_campaign
from tests.test_map import _ok, _play
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры хода
from tests.test_ws import connect, next_of


def _roll(hid):
    args = {"character_id": hid, "stat": "athletics", "difficulty": "dc.medium", "reason": "дверь"}
    return {"tool_calls": [("roll_check", args)]}


def run_two(settings, fn):
    """Две сессии одной базы: писатель-соперник и тот, кто прочитал мир раньше."""

    async def go():
        engine = make_engine(settings.database_url)
        try:
            return await fn(make_sessionmaker(engine))
        finally:
            await engine.dispose()

    return asyncio.run(go())


def test_revision_once_per_transaction_chat_does_not_count_savepoint_releases(client, admin, settings):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid, hid = campaign["id"], hero["id"]

    async def go(s):
        rev = await world_tx.read_revision(s, cid)
        ch = await s.get(Character, hid)
        ch.name = "Бран"
        await s.flush()
        ch.name = "Бран Смелый"
        await s.flush()
        assert world_tx.held(s, cid)
        await s.commit()
        assert await world_tx.read_revision(s, cid) == rev + 1  # guard один на транзакцию

        c = await s.get(Campaign, cid)
        await system_message(s, c, "Сообщение мира не меняет", None)  # last_seq и сообщения — не мир
        await s.commit()
        assert await world_tx.read_revision(s, cid) == rev + 1

        nested = await s.begin_nested()
        ch.name = "Бран Хитрый"
        await s.flush()
        assert world_tx.held(s, cid)
        await nested.rollback()
        assert not world_tx.held(s, cid)  # откат точки сохранения откатил и UPDATE ревизии
        ch = await s.get(Character, hid)
        ch.name = "Бран Мудрый"
        await s.flush()
        await s.commit()
        assert await world_tx.read_revision(s, cid) == rev + 2

        c = await s.get(Campaign, cid)
        c.settings = {**(c.settings or {}), "excluded_themes": ["пауки"]}  # разрешения контента — защищены
        await s.commit()
        return await world_tx.read_revision(s, cid) - rev

    assert run(settings, go) == 3


async def _sketch(ctx):
    await _ok(ctx, "create_location", {"name": "Кладовая", "make_current": True})
    box = (await _ok(ctx, "create_container", {"name": "Ларь"}))["container_id"]
    room = {"shape": "room", "cols": 6, "rows": 5, "party": [1, 1], "walls": [], "exits": [], "features": []}
    await _ok(ctx, "sketch_place", room)
    await _ok(ctx, "open_container", {"character_id": next(iter(ctx.world.characters)), "container_id": box})
    return box


async def _edit_sketch(ctx, box, hid):  # noqa: ARG001
    await _ok(ctx, "edit_sketch", {"action": "add_feature", "feature": {"name": "Бочка", "cells": [[4, 3, 4, 3]]}})


async def _hero_leaves(ctx, box, hid):  # noqa: ARG001
    hall = (await _ok(ctx, "create_location", {"name": "Зал", "link_to": [ctx.world.home()]}))["location_id"]
    await _ok(ctx, "move", {"character_ids": [hid], "location_id": hall})


async def _close_parent(ctx, box, hid):
    await _ok(ctx, "open_container", {"character_id": hid, "container_id": box, "opened": False})


async def _seat_rights(ctx, box, hid):  # noqa: ARG001
    seat = next(x for x in ctx.campaign.seats if x.role == "player")
    (await ctx.session.get(Seat, seat.id)).occupant_type = "agent"


async def _content_rights(ctx, box, hid):  # noqa: ARG001
    ctx.campaign.settings = {**(ctx.campaign.settings or {}), "excluded_themes": ["нежить"]}


@pytest.mark.parametrize("rival", [_edit_sketch, _hero_leaves, _close_parent, _seat_rights, _content_rights])
def test_writer_between_snapshot_and_write_conflicts(client, admin, settings, rival):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid, hid = campaign["id"], hero["id"]
    box = _play(settings, cid, _sketch)

    async def go(maker):
        async with maker() as stale:
            c = await stale.get(Campaign, cid)
            ctx = await open_context(stale, c, Dice(seed=1), turn_id=None, seat_id=None)  # снимок мира
            async with maker() as other:
                rc = await other.get(Campaign, cid)
                rctx = await open_context(other, rc, Dice(seed=2), turn_id=None, seat_id=None)
                await rival(rctx, box, hid)
                await other.commit()
            with pytest.raises(WorldConflict):
                await execute(ctx, "update_entity", {"entity_id": box, "note": "старый снимок"})
            await stale.rollback()
        async with maker() as fresh:
            return (await fresh.get(Entity, box)).state

    assert "старый снимок" not in str(run_two(settings, go))  # конфликт, а не перезапись


def _send(client, head, cid, text):
    with connect(client, head, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": text}})
        next_of(ws, "message.new")
    client.portal.call(client.app.state.master.wait_idle, cid)


def test_startup_closes_dead_turns_and_leaves_unrequested_containers(game_client, admin_g, settings):
    c, _heads, hero = party(game_client, admin_g)
    cid = c["id"]

    async def build(ctx):
        box = (await _ok(ctx, "create_container", {"name": "Сундук"}))["container_id"]
        ctx.session.add(WorldGenerationState(campaign_id=cid, target_entity_id=box, phase="container_contents"))
        ctx.session.add(MasterTurn(campaign_id=cid, status="running", upto_seq=0))  # процесс умер в фазе действий

    _play(settings, cid, build)
    game_client.portal.call(lambda: game_client.app.state.master.recover(startup=True))
    (turn,) = rows(settings, MasterTurn)
    assert turn.status == "failed" and turn.trace["error"] == "server restarted"
    (state,) = rows(settings, WorldGenerationState)
    assert state.status == "unprepared" and state.requested_at is None  # закрытое неизученное не трогаем


def _receipt_world(settings, cid, *, hidden=False, key="explore:1"):
    async def build(ctx):
        hall = (await _ok(ctx, "create_location", {"name": "Погреб", "make_current": True}))["location_id"]
        box = (await _ok(ctx, "create_container", {"name": "Бочонок"}))["container_id"]
        if hidden:
            ctx.world.entities[box].state = {**ctx.world.entities[box].state, "hidden": True}
        state = WorldGenerationState(campaign_id=cid, target_entity_id=box, phase="container_contents")
        ctx.session.add(state)
        await ctx.session.flush()
        ctx.session.add(
            Event(
                campaign_id=cid,
                tool="open_container",
                payload={"result": {"accepted": True, "operation_ref": state.id}},
                idempotency_key=key,
            )
        )
        return hall, box, state.id

    return _play(settings, cid, build)


def test_receipt_replay_gets_fresh_status_and_payload_stays(client, admin, settings):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid = campaign["id"]
    _hall, _box, ref = _receipt_world(settings, cid)

    async def replay(ctx):
        return await execute(ctx, "open_container", {"character_id": hero["id"], "container_id": "x"}, key="explore:1")

    first = _play(settings, cid, replay)
    assert first["repeated"] and first["result"] == {"accepted": True, "operation_ref": ref}
    assert first["status"]["status"] == "unexamined"

    async def ready(s):
        row = await s.get(WorldGenerationState, ref)
        row.requested_at = datetime.now(UTC)
        row.status, row.revision = "ready", 1
        await s.commit()

    run(settings, ready)
    again = _play(settings, cid, replay)
    assert again["result"] == first["result"] and again["status"]["status"] == "ready"  # не вечный pending
    (ev,) = rows(settings, Event, Event.idempotency_key == "explore:1")
    assert ev.payload == {"result": {"accepted": True, "operation_ref": ref}}  # квитанция не переписана


def test_generation_status_access_and_states(client, admin, settings):
    import_base(settings)
    campaign, (player,), _hero = party(client, admin)
    cid = campaign["id"]
    _hall, box, ref = _receipt_world(settings, cid)
    url = f"/api/campaigns/{cid}/generation/{ref}"
    assert ok(client.get(url, headers=player))["status"] == "unexamined"

    async def request(s):
        (await s.get(WorldGenerationState, ref)).requested_at = datetime.now(UTC)
        await s.commit()

    run(settings, request)
    assert ok(client.get(url, headers=player))["status"] == "pending"

    async def finish(s):
        row = await s.get(WorldGenerationState, ref)
        row.status, row.revision = "ready", 1
        coin = Entity(
            campaign_id=cid,
            kind="object",
            name="Монета",
            location_id=(await s.get(Entity, box)).location_id,
            state={"world_object": {"generation_ref": ref}},
        )
        s.add(coin)
        await s.commit()
        return coin.id

    coin = run(settings, finish)
    out = ok(client.get(url, headers=player))
    assert out["status"] == "ready" and out["objects"] == [{"id": coin, "name": "Монета"}]
    assert ok(client.get(url, headers=admin))["objects"] == out["objects"]  # владелец без места видит всё

    other = make_campaign(client, admin, players=1)
    assert client.get(f"/api/campaigns/{other['id']}/generation/{ref}", headers=admin).status_code == 404

    _hall2, _box2, secret = _receipt_world(settings, cid, hidden=True, key="explore:2")
    assert client.get(f"/api/campaigns/{cid}/generation/{secret}", headers=player).status_code == 404
    assert ok(client.get(f"/api/campaigns/{cid}/generation/{secret}", headers=admin))["status"] == "unexamined"


class _TestPreparer:
    """Тестовый исполнитель: без предметов и LLM, сразу ready с пустым результатом через world_write."""

    def __init__(self):
        self.calls = []

    async def settle(self, maker, campaign_id, refs):
        self.calls.append(list(refs))
        async with maker() as s:
            await world_tx.world_write(s, campaign_id)
            for ref in refs:
                row = await s.get(WorldGenerationState, ref)
                row.status, row.revision, row.quality = "ready", row.revision + 1, "normal"
            await s.commit()
