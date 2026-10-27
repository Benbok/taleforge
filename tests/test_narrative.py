"""Объём повествования мастера и подталкивание отряда, который буксует."""
# ruff: noqa: F811 — фикстуры из test_master приходят в тесты параметрами

from app.agents.rhythm import _stalled, stall_note
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры

FAIL = {"tool": "roll_check", "result": {"ok": True, "result": {"success": False}}}
WIN = {"tool": "roll_check", "result": {"ok": True, "result": {"success": True}}}
REFUSED = {"tool": "cancel_action", "result": {"ok": True, "result": {}}}


def check(hero, reason="дверь"):
    args = {"character_id": hero["id"], "stat": "athletics", "difficulty": "dc.medium", "reason": reason}
    return {"tool_calls": [("roll_check", args)]}


def test_stall_counting():
    assert _stalled({"calls": [FAIL]}) and _stalled({"calls": [REFUSED]})
    assert not _stalled({"calls": [FAIL, WIN]})  # удалось хоть что-то — сдвинулись
    assert not _stalled({"calls": [FAIL, {"tool": "move", "result": {"ok": True}}]})
    assert not _stalled({"calls": []})  # разговор без попыток — не буксование
    assert _stalled({"calls": [FAIL], "combat": ["гоблин бьёт"]}) is None
    assert stall_note(2) == "" and "буксует уже 3" in stall_note(3)
