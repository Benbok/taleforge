# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Экран боя (этап 7, часть 4): полоса инициативы, открытые спасброски от смерти, кнопка реакции после
переподключения, итог сессии на паузе."""

import asyncio

from app.db.models import Character
from tests.game import party, run
from tests.test_combat import _setup
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, ok  # noqa: F401 — фикстуры
from tests.test_ws import connect, next_of


def test_snapshot_has_initiative_strip_without_creature_numbers(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g, master={"type": "owner"})
    gob = _setup(settings, c["id"], hero["id"], "creature.goblin", zone="near", name="Гоблин-лучник")
    with connect(game_client, p1, c["id"]) as (_, snap):
        order = snap["payload"]["scene"]["order"]
    assert [x["id"] for x in order] == [gob, hero["id"]]
    assert order[0] == {"id": gob, "initiative": 20, "name": "Гоблин-лучник", "side": "enemy", "out": None}
    assert order[1]["side"] == "hero" and order[1]["seat_id"] == hero["seat_id"] and order[1]["out"] is None
    assert "hp" not in str(order)


def test_death_saves_are_open_to_the_table(game_client, admin_g, llm, settings):
    c, (p1, p2), hero = party(game_client, admin_g, players=2)

    async def down(s):
        ch = await s.get(Character, hero["id"])
        ch.resources = {**ch.resources, "hp": 0, "death_saves": [1, 2]}
        await s.commit()

    run(settings, down)
    with connect(game_client, p2, c["id"]) as (_, snap):
        me = next(h for h in snap["payload"]["heroes"] if h["id"] == hero["id"])
    assert me["hp"] == 0 and me["death_saves"] == [1, 2]


def test_reaction_button_survives_reconnect(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)
    master = game_client.app.state.master
    payload = {"prompt_id": "rx_test", "character_id": hero["id"], "trigger": "«Волк» выходит из ближнего боя"}

    async def open_prompt():
        fut = asyncio.get_running_loop().create_future()
        master._reactions["rx_test"] = (c["id"], hero["seat_id"], fut, payload)

    game_client.portal.call(open_prompt)
    with connect(game_client, p1, c["id"]) as (_, snap):
        assert snap["payload"]["reaction"] == payload
    with connect(game_client, admin_g, c["id"]) as (_, snap):
        assert snap["payload"]["reaction"] is None  # чужая кнопка не видна
    master._reactions.pop("rx_test")


def test_session_summary_on_pause(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)
    llm.replies += [DONE, DONE, {"text": "Дорога пуста."}]
    act(game_client, p1, c["id"], "Иду по дороге на север")
    with connect(game_client, p1, c["id"]) as (ws, snap):
        assert snap["payload"]["summary"] is None  # идёт сессия
        ok(game_client.post(f"/api/campaigns/{c['id']}/session/pause", headers=admin_g))
        game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
        summary = next_of(ws, "session.summary")["payload"]
    assert summary["recap"] == "Герои продолжают путь." and summary["events"]
    with connect(game_client, p1, c["id"]) as (_, snap):
        assert snap["payload"]["summary"]["recap"] == "Герои продолжают путь."
