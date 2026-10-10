# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Закрытое описание места: мастер описывает, техническая модель строит по нему эскиз, мастер видит и правит."""

from app.agents import surveyor
from tests.game import party
from tests.test_map import _map, _ok, _play
from tests.test_master import admin_g, dice, game_client, llm  # noqa: F401 — фикстуры хода
from tests.test_sketch import CELL

LAYOUT = (
    "Тесная камера 30 на 20 футов. Отряд у южной стены, у запертой решётки, за ней коридор. В северной стене "
    "узкое окно во двор. У северо-западного угла нары, под ними лаз — тайный."
)


def _draft(**over):
    return {**{k: v for k, v in CELL.items() if k != "features"}, "features": CELL["features"][:1], **over}


def test_master_describes_a_place_and_the_sketch_is_built(game_client, admin_g, llm, settings):
    c, (p1,), _ = party(game_client, admin_g)
    cid = c["id"]

    async def describe(ctx):
        cell = (await _ok(ctx, "create_location", {"name": "Камера", "make_current": True}))["location_id"]
        done = await _ok(ctx, "describe_place", {"layout": LAYOUT})
        return cell, done, ctx.world.scene_table(), sorted(ctx.signals)

    cell, done, table, signals = _play(settings, cid, describe)
    assert "строится" in done["note"] and signals == ["map.changed", f"sketch:{cell}"]
    assert "эскиз строится по закрытому описанию" in table and "Тесная камера" in table

    # первая попытка налезает на стену — модель получает ошибку и исправляется
    bad = _draft(features=[{"name": "Нары", "kind": "furniture", "cells": [[4, 0, 5, 0]]}])
    llm.replies += [{"tool_calls": [("submit_sketch", bad)]}, {"tool_calls": [("submit_sketch", _draft())]}]
    built = game_client.portal.call(surveyor.draw, game_client.app.state.master, cid, cell)
    assert built["cols"] == 6 and [f["name"] for f in built["features"]] == ["Нары"]
    sketch_calls = [r for r in llm.requests if r["tools"] and r["tools"][0]["function"]["name"] == "submit_sketch"]
    assert "Тесная камера" in sketch_calls[0]["messages"][1]["content"]
    assert "«Нары» стоит на стене (5, 0)" in sketch_calls[1]["messages"][-1]["content"]

    async def look(ctx):
        return ctx.world.scene_table()

    table = _play(settings, cid, look)
    assert "помещение 6×4 клеток" in table and "построен по описанию" in table
    m = _map(game_client, p1, cid)
    assert m["sketch"]["cols"] == 6 and [x["name"] for x in m["sketch"]["exits"]] == ["Дверь решётки", "Узкое окно"]


def test_sketch_drawn_by_master_after_description_is_kept(game_client, admin_g, llm, settings):
    c, _, _ = party(game_client, admin_g)
    cid = c["id"]

    async def describe(ctx):
        cell = (await _ok(ctx, "create_location", {"name": "Камера", "make_current": True}))["location_id"]
        await _ok(ctx, "describe_place", {"layout": LAYOUT})
        await _ok(ctx, "sketch_place", {**CELL, "rows": 5})  # мастер успел нарисовать сам
        return cell

    cell = _play(settings, cid, describe)
    llm.replies.append({"tool_calls": [("submit_sketch", _draft())]})
    assert game_client.portal.call(surveyor.draw, game_client.app.state.master, cid, cell) is None

    async def look(ctx):
        return ctx.world.entities[cell].state["sketch"]

    kept = _play(settings, cid, look)
    assert kept["rows"] == 5 and not kept.get("auto")
