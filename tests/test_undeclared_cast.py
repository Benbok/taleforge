# ruff: noqa: F811 — shared integration fixtures
"""Вне боя мастер не творит заклинание, которого игрок в этом ходу не заявлял (кампания c_d45c8e2b5c660e33)."""

from app.agents.master.common import declared_cast
from app.db.models import Event, MasterTurn, Message
from tests.game import party
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401


def _msg(seat, content, intent=None, kind="action"):
    return Message(id="m", campaign_id="c", seq=1, seat_id=seat, kind=kind, content=content, intent=intent)


class _Ch:
    def __init__(self, cid):
        self.id = cid


def test_declared_by_parsed_verb_or_spell_name():
    seats = {"s1": _Ch("ch_1")}
    cast = {"actions": [{"verb": "cast", "spell_id": "spell.goodberry"}]}
    assert declared_cast([_msg("s1", "колдую", cast)], seats, "ch_1", "Добрая ягода")
    assert declared_cast([_msg("s1", "Творю «Добрая ягода» на себя")], seats, "ch_1", "Добрая ягода")
    search = {"actions": [{"verb": "search", "target_id": "en_1"}]}
    assert not declared_cast([_msg("s1", "Обыскиваю: Ящик экспедиции", search)], seats, "ch_1", "Добрая ягода")
    assert not declared_cast([_msg("s2", "Творю «Добрая ягода»")], seats, "ch_1", "Добрая ягода")


def test_model_cannot_cast_undeclared_spell(game_client, admin_g, llm, settings):
    c, (player,), hero = party(game_client, admin_g)
    llm.replies += [
        {"tool_calls": [("cast_spell", {"caster_id": hero["id"], "spell_id": "spell.goodberry"})]},
        DONE,
        DONE,
        {"text": "Ты осматриваешься."},
    ]
    act(game_client, player, c["id"], "Осматриваюсь по сторонам")
    (turn,) = rows(settings, MasterTurn)
    call = next(x for x in turn.trace["calls"] if x["tool"] == "cast_spell")
    assert not call["result"]["ok"] and "не заявлял" in call["result"]["error"]
    assert not [e for e in rows(settings, Event) if e.tool == "cast_spell"]


def test_declared_spell_passes_the_guard(game_client, admin_g, llm, settings):
    c, (player,), hero = party(game_client, admin_g)
    llm.replies += [
        {"tool_calls": [("cast_spell", {"caster_id": hero["id"], "spell_id": "spell.goodberry"})]},
        DONE,
        DONE,
        {"text": "Готово."},
    ]
    act(game_client, player, c["id"], "Творю «Добрая ягода»")
    (turn,) = rows(settings, MasterTurn)
    call = next(x for x in turn.trace["calls"] if x["tool"] == "cast_spell")
    assert "не заявлял" not in (call["result"].get("error") or "")  # дальше решают правила заклинаний
