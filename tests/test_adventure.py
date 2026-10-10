# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Кампания по готовому приключению: каркас из книги, зацепка, комнаты по номерам и сложности проверок книги."""

from pathlib import Path

from app.agents import prelude
from app.agents.master import decision_tools
from app.core import adventure, modules
from app.db.models import AdventureModule, Campaign, CampaignSecret
from tests.game import import_base, ok, party, run
from tests.module_sample import sample
from tests.test_map import _map, _ok, _play

ROOT = Path(__file__).resolve().parents[1] / "content"


GRID = {"cols": 10, "rows": 8, "left": 0.0, "top": 0.0, "right": 1.0, "bottom": 0.8}
CRYPT_MAP = {
    "id": "map1",
    "file": "map1.png",
    "location_id": "location.davos_crypt",
    "grid": GRID,
    "marks": [
        {"number": "1", "x": 0.2, "y": 0.3, "cells": [[0, 0, 3, 5]], "blocked": [[1, 2]]},
        {"number": "2", "x": 0.7, "y": 0.3, "cells": [[6, 0, 9, 5]]},
    ],
}


def publish_sample(settings) -> str:
    draft, errors, _ = modules.check(sample(), ROOT)
    assert errors == []

    async def go(s):
        m = AdventureModule(title=draft["title"], slug=draft["slug"], status="review", draft=draft)
        s.add(m)
        await s.flush()
        mid = m.id
        await modules.publish(s, draft, [CRYPT_MAP], "1.0.0", ROOT, mid)
        m = await s.get(AdventureModule, mid)
        m.pack_id, m.pack_version, m.status = "module-unquiet-dead", "1.0.0", "published"
        await s.commit()
        return mid

    return run(settings, go)


def test_campaign_from_module_runs_room_by_room(client, admin, settings, monkeypatch):
    intros = []

    async def prepare(svc, cid):  # вступление с голосом готовится в фоне сразу после создания
        intros.append(cid)

    monkeypatch.setattr(prelude, "prepare_campaign_intro", prepare)
    import_base(settings)
    mid = publish_sample(settings)
    listed = ok(client.get("/api/modules", headers=admin))
    assert listed[0]["id"] == mid and [h["id"] for h in listed[0]["hooks"]] == ["noble", "board"]

    c, (p1,), hero = party(client, admin, module_id=mid, module_hook="board")
    cid = c["id"]
    assert intros == [cid]
    st = c["settings"]
    assert st["module"]["hook_id"] == "board" and st["leveling"] == "milestone" and st["replan"] is False
    assert st["plan"]["status"] == "ready" and st["creation_rules"]["start_level"] == 1
    assert c["public_intro"].startswith("Скелеты повылезали")
    # каркас взят из книги: архитектор его не перестраивает
    plan = ok(client.get(f"/api/campaigns/{cid}/plan", headers=admin))
    assert plan["status"] == "ready" and plan["can_generate"] is False
    assert client.post(f"/api/campaigns/{cid}/plan", json={}, headers=admin).status_code == 409

    async def secret(s):
        return (await s.get(CampaignSecret, cid)).plot

    client.portal.call(client.app.state.master.wait_idle, None)  # вступление при старте сессии отработало
    p = run(settings, secret)
    assert p["title"] == "Неспокойные мертвецы" and p["module_hook"]["id"] == "board"
    assert "Объявление на доске" in adventure.hook_line(p)

    async def into_crypt(ctx):
        assert "enter_room" in decision_tools(ctx)
        # место первой сцены вступление уже открыло в реестре (prelude._open_first_place)
        crypt = next(x["entity_id"] for x in ctx.world.plot["locations"] if x["id"] == "crypt")
        # и отряд сразу в первой комнате книги: герой на её карте с начала игры, а не после enter_room
        start = ctx.world.entities[ctx.world.scene.location_id]
        assert start.location_id == crypt and str(adventure.room_of(start)["number"]) == "1"
        assert "Комната 1 «Зал Мёртвых»" in adventure.master_block(ctx.world)
        room = await _ok(ctx, "enter_room", {"room": "1"})
        check = await _ok(
            ctx,
            "roll_check",
            {
                "character_id": hero["id"],
                "stat": "perception",
                "difficulty": f"book:{room['room_id']}:1",
                "reason": "скелеты в соседней крипте",
            },
        )
        return crypt, room, check, adventure.master_block(ctx.world)

    crypt, room, check, block = _play(settings, cid, into_crypt)
    assert "Внимательность, СЛ 16" in room["book"] and "комната 2 «Восточная крипта» (en_" in room["book"]
    assert check["dc"] == 16  # сложность из книги, а не со шкалы
    assert "Комната 1 «Зал Мёртвых»" in block and "Выходы" in block

    # игрок видит комнату, где стоит, а соседнюю — только под номером: название из книги может выдать тайну
    m = _map(client, p1, cid)
    places = {x["id"]: x for x in m["places"]}
    assert m["here"]["id"] == room["room_id"] and places[room["room_id"]]["name"] == "Зал Мёртвых"
    assert places[room["room_id"]]["parent_id"] == crypt
    assert "Комната 2" in {x["name"] for x in m["places"]}
    assert [x["name"] for x in m["exits"] if x["id"] != crypt] == ["Комната 2"]
    # карта книги: отряд в комнате 1, непосещённая комната 2 игроку не отмечена, герой стоит на клетке комнаты
    book = m["book"]
    assert book["module_id"] == mid and book["map_id"] == "map1" and book["here"] == "1"
    assert [(r["number"], r["status"]) for r in book["rooms"]] == [("1", "here")]
    (tok,) = book["tokens"]
    assert tok["id"] == hero["id"] and tok["mine"] and tok["room"] == "1"
    assert 0 < tok["x"] < 0.4 and 0 < tok["y"] < 0.6  # внутри клеток комнаты 1
    # схема «Вокруг» комнаты построена по клеткам книги: колонна — стена, выход на восток в комнату 2
    sk = m["sketch"]
    assert (sk["cols"], sk["rows"]) == (4, 6) and [1, 2] in sk["walls"]
    assert [(x["side"], x["name"]) for x in sk["exits"]] == [("e", "Комната 2")]

    async def next_room(ctx):
        r2 = await _ok(ctx, "enter_room", {"room": "2"})
        bad = await __import__("app.tools.registry", fromlist=["execute"]).execute(ctx, "enter_room", {"room": "9"})
        return r2, bad, adventure.master_block(ctx.world)

    r2, bad, block = _play(settings, cid, next_room)
    assert not bad["ok"] and "комната 2 «Восточная крипта»" in bad["error"]
    assert "2 × Скелет (creature.skeleton)" in block and "2к12 см" in block
    m = _map(client, p1, cid)
    names = {x["id"]: x["name"] for x in m["places"]}
    assert names[r2["room_id"]] == "Восточная крипта" and names[room["room_id"]] == "Зал Мёртвых"
    statuses = [(r["number"], r["status"]) for r in m["book"]["rooms"]]
    assert statuses == [("1", "visited"), ("2", "here")] and m["book"]["tokens"][0]["room"] == "2"

    # История исследования не создаёт физический выход из комнаты 2.
    # В старых сохранениях переходы движения уже могли добавить ложные state.links.
    async def explore_and_return(ctx):
        other = await _ok(ctx, "create_location", {"name": "Дальнее хранилище", "parent_id": crypt})
        await _ok(ctx, "move", {"character_ids": [hero["id"]], "location_id": other["location_id"]})
        await _ok(ctx, "move", {"character_ids": [hero["id"]], "location_id": r2["room_id"]})
        return other["location_id"]

    remote = _play(settings, cid, explore_and_return)
    m = _map(client, p1, cid)
    assert remote in {p["id"] for p in m["places"]}  # посещённая локация остаётся в «Местах»
    assert {e["id"] for e in m["exits"]} == {room["room_id"]}
    assert {x["to"] for x in m["sketch"]["exits"] if x.get("to")} == {room["room_id"]}
    assert not any(remote in (x["a"], x["b"]) for x in m["links"])


def test_module_tools_stay_off_in_a_regular_campaign(client, admin, settings):
    import_base(settings)
    c, _, _ = party(client, admin)

    async def tools(ctx):
        return decision_tools(ctx)

    assert "enter_room" not in _play(settings, c["id"], tools)

    async def campaign(s):
        return (await s.get(Campaign, c["id"])).settings

    assert "module" not in run(settings, campaign)


def test_find_room_resilient_matching():
    from app.content.catalog import Entry

    rec = Entry(
        id="location.davos_crypt",
        kind="location_template",
        status="active",
        pack_id="pack1",
        data={
            "name": "Семейный склеп Давоса",
            "rooms": [
                {"id": "r1", "name": "Зал Мёртвых", "number": "1"},
                {"id": "graveyard", "name": "Кладбище у мавзолея"},
            ],
        },
    )
    assert adventure.find_room(rec, "1")["id"] == "r1"
    assert adventure.find_room(rec, "r1")["id"] == "r1"
    assert adventure.find_room(rec, "Зал Мёртвых")["id"] == "r1"
    assert adventure.find_room(rec, "комната 1")["id"] == "r1"
    assert adventure.find_room(rec, "room 1")["id"] == "r1"
    assert adventure.find_room(rec, "room_1")["id"] == "r1"
    assert adventure.find_room(rec, "room_1_graveyard_at_the_mausoleum")["id"] == "r1"
    assert adventure.find_room(rec, "graveyard")["id"] == "graveyard"
    assert adventure.find_room(rec, "Кладбище у мавзолея")["id"] == "graveyard"
