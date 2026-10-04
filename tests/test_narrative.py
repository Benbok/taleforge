"""Объём повествования мастера и подталкивание отряда, который буксует."""
# ruff: noqa: F811 — фикстуры из test_master приходят в тесты параметрами

from app.agents.rhythm import _stalled, stall_note
from app.db.models import GameSession, MasterTurn
from tests.game import party, run
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры

FAIL = {"tool": "roll_check", "result": {"ok": True, "result": {"success": False}}}
WIN = {"tool": "roll_check", "result": {"ok": True, "result": {"success": True}}}
REFUSED = {"tool": "cancel_action", "result": {"ok": True, "result": {}}}


def check(hero, reason="дверь"):
    args = {"character_id": hero["id"], "stat": "athletics", "difficulty": "dc.medium", "reason": reason}
    return {"tool_calls": [("roll_check", args)]}


def test_check_only_turn_asks_for_short_outcome(game_client, admin_g, llm, dice):
    c, (p1,), hero = party(game_client, admin_g)
    dice += [15]
    llm.replies += [check(hero), DONE, {"text": "Дверь со скрипом поддаётся."}]
    assert act(game_client, p1, c["id"], "Вышибаю дверь плечом")["content"] == "Дверь со скрипом поддаётся."
    prompt = llm.requests[-1]["messages"][1]["content"]
    assert "одно-два предложения" in prompt and "только проверки" in prompt


def test_ordinary_turn_is_one_short_paragraph(game_client, admin_g, llm):
    c, (p1,), hero = party(game_client, admin_g)
    llm.replies += [
        {"tool_calls": [("auto_success", {"character_id": hero["id"], "reason": "смотрит"})]},
        DONE,
        {"text": "Зал пуст."},
    ]
    assert act(game_client, p1, c["id"], "Осматриваюсь")["content"] == "Зал пуст."
    prompt = llm.requests[-1]["messages"][1]["content"]
    assert "один короткий абзац" in prompt and "только проверки" not in prompt


def test_stalled_party_gets_new_opportunity(game_client, admin_g, llm, dice, settings):
    c, (p1,), hero = party(game_client, admin_g)
    game = rows(settings, GameSession, GameSession.campaign_id == c["id"])[0]

    async def stuck(s):
        for calls in ([FAIL], [REFUSED], [FAIL, FAIL]):
            s.add(
                MasterTurn(campaign_id=c["id"], session_id=game.id, upto_seq=0, status="done", trace={"calls": calls})
            )
        await s.commit()

    run(settings, stuck)
    llm.replies += [
        {"tool_calls": [("cancel_action", {"character_id": hero["id"], "reason": "решётка"})]},
        DONE,
        {"text": "Решётка не поддаётся, но в коридоре слышны шаги."},
    ]
    assert act(game_client, p1, c["id"], "Снова тяну решётку")["content"].startswith("Решётка")
    decide = llm.requests[0]["messages"][1]["content"]
    assert "буксует уже 3 хода" in decide and "roll_fortune" in decide
    assert "Отряд долго буксовал" in llm.requests[-1]["messages"][1]["content"]
    last = rows(settings, MasterTurn, MasterTurn.campaign_id == c["id"], MasterTurn.status == "done")
    assert any(t.trace.get("stalled") for t in last)


def test_stall_counting():
    assert _stalled({"calls": [FAIL]}) and _stalled({"calls": [REFUSED]})
    assert not _stalled({"calls": [FAIL, WIN]})  # удалось хоть что-то — сдвинулись
    assert not _stalled({"calls": [FAIL, {"tool": "move", "result": {"ok": True}}]})
    assert not _stalled({"calls": []})  # разговор без попыток — не буксование
    assert _stalled({"calls": [FAIL], "combat": ["гоблин бьёт"]}) is None
    assert stall_note(2) == "" and "буксует уже 3" in stall_note(3)
