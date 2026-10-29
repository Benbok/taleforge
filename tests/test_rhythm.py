# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Ритм сессии и эпилог: цель на вечер, зацепка на следующий раз, эпилог кампании, темп ваншота."""

from app.agents import rhythm
from app.db.models import Message
from tests.game import ok, party
from tests.test_master import admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры


def test_oneshot_pacing():
    assert rhythm.pacing_note("short", 50) == ""
    assert "примерно 30 ходов; сыграно 3" in rhythm.pacing_note("oneshot", 3)
    assert "Пора сводить нити" in rhythm.pacing_note("oneshot", 21)
    assert "Время вышло" in rhythm.pacing_note("oneshot", 30)


def narrations(settings, cid):
    return [m.content for m in rows(settings, Message, Message.campaign_id == cid, Message.kind == "narration")]


def test_no_rhythm_without_plan(game_client, admin_g, llm, settings):
    c, _, _ = party(game_client, admin_g)
    ok(game_client.post(f"/api/campaigns/{c['id']}/session/pause", headers=admin_g))
    ok(game_client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin_g))
    ok(game_client.post(f"/api/campaigns/{c['id']}/session/end", headers=admin_g))
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    # a failed session greeting is retried at the next start; nothing else asks the model without a plan
    assert all("Игра только начинается" in str(r["messages"]) for r in llm.requests)
    assert narrations(settings, c["id"]) == []
