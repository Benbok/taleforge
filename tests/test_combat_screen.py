# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Экран боя (этап 7, часть 4): полоса инициативы, открытые спасброски от смерти, кнопка реакции после
переподключения, итог сессии на паузе."""

from tests.game import ok, party
from tests.test_master import DONE, act, admin_g, dice, game_client, llm  # noqa: F401 — фикстуры
from tests.test_ws import connect, next_of


def test_reaction_button_survives_reconnect(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)
    master = game_client.app.state.master
    payload = {
        "prompt_id": "rx_test",
        "character_id": hero["id"],
        "trigger": "«Волк» выходит из ближнего боя",
        "options": [{"id": "opportunity_attack", "label": "Ударить вслед"}, {"id": "skip", "label": "Пропустить"}],
        "expires_at": 4102444800.0,
    }

    async def open_prompt():
        master.coordination.open_prompt("rx_test", c["id"], hero["seat_id"])
        master.coordination.describe_prompt("rx_test", payload)

    game_client.portal.call(open_prompt)
    with connect(game_client, p1, c["id"]) as (_, snap):
        assert snap["payload"]["reaction"] == payload
    with connect(game_client, admin_g, c["id"]) as (_, snap):
        assert snap["payload"]["reaction"] is None  # чужая кнопка не видна
    master.coordination.close_prompt("rx_test")


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
