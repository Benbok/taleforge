# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Ритм сессии и эпилог: цель на вечер, зацепка на следующий раз, эпилог кампании, темп ваншота."""

from app.agents import rhythm
from app.db.models import Campaign, LlmCall, Message
from tests.game import ok, party
from tests.test_lead import checked, set_plan
from tests.test_master import admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры


def test_oneshot_pacing():
    assert rhythm.pacing_note("short", 50) == ""
    assert "примерно 30 ходов; сыграно 3" in rhythm.pacing_note("oneshot", 3)
    assert "Пора сводить нити" in rhythm.pacing_note("oneshot", 21)
    assert "Время вышло" in rhythm.pacing_note("oneshot", 30)


def narrations(settings, cid):
    return [m.content for m in rows(settings, Message, Message.campaign_id == cid, Message.kind == "narration")]


def test_session_rhythm_and_epilogue(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g, brief={"length": "short"})
    cid = c["id"]
    idle = lambda: game_client.portal.call(game_client.app.state.master.wait_idle, cid)  # noqa: E731
    idle()  # старт сессии в party() прошёл ещё без каркаса
    set_plan(settings, cid, checked())

    llm.replies += [{"tool_calls": [(rhythm.NEXT_TOOL, {"hook": "Туман шепчет имя Брана."})]}]
    ok(game_client.post(f"/api/campaigns/{cid}/session/pause", headers=admin_g))
    idle()
    assert narrations(settings, cid)[-1] == "В следующий раз: Туман шепчет имя Брана."
    assert "Сессия окончена" in llm.requests[0]["messages"][1]["content"]

    llm.replies += [
        {"text": "Бран сходит на берег."},
        {"tool_calls": [(rhythm.GOAL_TOOL, {"goal": "Узнать, куда уходят корабли."})]},
    ]
    ok(game_client.post(f"/api/campaigns/{cid}/session/start", headers=admin_g))
    idle()
    assert narrations(settings, cid)[-2:] == [
        "Бран сходит на берег.",
        "Цель на этот вечер: Узнать, куда уходят корабли.",
    ]
    assert "Сюжет сейчас" in llm.requests[2]["messages"][1]["content"]

    fates = [{"character_id": hero["id"], "text": "Бран стал смотрителем маяка."}]
    llm.replies += [
        {"tool_calls": [(rhythm.EPILOGUE_TOOL, {"chronicle": "Туман ушёл.", "fates": []})]},
        {"tool_calls": [(rhythm.EPILOGUE_TOOL, {"chronicle": "Туман ушёл.", "fates": fates})]},
    ]
    ok(game_client.post(f"/api/campaigns/{cid}/session/end", headers=admin_g))
    idle()
    assert "нет судьбы героев: Бран" in llm.requests[4]["messages"][-1]["content"]
    assert narrations(settings, cid)[-2:] == [
        "Эпилог. Туман ушёл.",
        f"Судьбы героев.\n\n[[{hero['id']}|Бран]]: Бран стал смотрителем маяка.",
    ]
    (camp,) = rows(settings, Campaign, Campaign.id == cid)
    assert camp.status == "ended" and camp.settings["epilogue"]["fates"] == {hero["id"]: "Бран стал смотрителем маяка."}
    purposes = [x.purpose for x in rows(settings, LlmCall) if x.purpose not in ("summary", "parse")]
    assert purposes == ["session_hook", "intro", "session_goal", "epilogue", "epilogue"]


def test_no_rhythm_without_plan(game_client, admin_g, llm, settings):
    c, _, _ = party(game_client, admin_g)
    ok(game_client.post(f"/api/campaigns/{c['id']}/session/pause", headers=admin_g))
    ok(game_client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin_g))
    ok(game_client.post(f"/api/campaigns/{c['id']}/session/end", headers=admin_g))
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    assert llm.requests == [] and narrations(settings, c["id"]) == []
