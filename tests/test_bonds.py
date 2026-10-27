# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Связи героев, личные крючки и вступление мастера (проект «Подготовка кампании», разделы 5 и 7.1)."""

from app.core import bonds, plot
from app.db.models import Character
from tests.game import ok, party
from tests.test_lead import checked
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры


def test_bonds_questions_and_answers():
    ch = Character(name="Бран", sheet={"level": 1})
    assert bonds.ensure_questions(ch) and not bonds.ensure_questions(ch)
    assert [q["id"] for q in bonds.bonds_of(ch)["questions"]] == ["q1", "q2", "q3"]
    b = bonds.answer(
        ch,
        [
            {"id": "q1", "text": "Мой брат пропал в тумане", "private": False},
            {"id": "q2", "text": "Тайна", "private": True},
        ],
    )
    assert set(b["answers"]) == {"q1", "q2"} and ch.sheet["level"] == 1
    assert bonds.public_bonds(ch) == [{"question": bonds.DEFAULT_QUESTIONS[0], "answer": "Мой брат пропал в тумане"}]
    assert "Тайна" not in bonds.render(ch, private=False) and "Тайна (лично" in bonds.render(ch, private=True)
    bonds.answer(ch, [{"id": "q2", "text": ""}])  # пустой ответ снимает прежний
    assert set(bonds.bonds_of(ch)["answers"]) == {"q1"}
    try:
        bonds.answer(ch, [{"id": "q9", "text": "?"}])
        raise AssertionError("неизвестный вопрос принят")
    except bonds.BondsError:
        pass


def test_hooks_in_plan():
    p = checked()
    plot.set_hook(p, "ch_1", "Бран", "npc_warden", "Бертольд продал брата Брана культу")
    assert "Бран (ch_1) → npc_warden: Бертольд продал" in plot.now_block(p)
    plot.close_node(p, "n_arrival", "done", "-")
    try:
        plot.set_hook(p, "ch_1", "Бран", "n_arrival", "-")
        raise AssertionError("крючок к закрытому узлу принят")
    except plot.PlotError:
        pass


def test_without_plan_only_default_questions(game_client, admin_g, llm):
    c, (p1, p2), hero = party(game_client, admin_g, players=2)
    url = f"/api/campaigns/{c['id']}/characters/{hero['id']}/bonds"
    r = ok(game_client.get(url, headers=p1))
    assert r["can_answer"] and r["bonds"]["source"] == "default" and "status" not in r["bonds"]
    assert game_client.get(url, headers=p2).status_code == 403  # чужие вопросы не видно
    body = {"answers": [{"id": "q1", "text": "Ищу брата"}, {"id": "q3", "text": "Боюсь моря", "private": True}]}
    ok(game_client.put(url, json=body, headers=p1))
    other = ok(game_client.get(f"/api/campaigns/{c['id']}/characters/{hero['id']}", headers=p2))
    assert other["bonds"] == [{"question": bonds.DEFAULT_QUESTIONS[0], "answer": "Ищу брата"}]
    assert "Боюсь моря" not in str(other)
    assert ok(game_client.get(url, headers=admin_g))["can_answer"] is False  # владелец проверяет, но не отвечает
    assert game_client.put(url, json=body, headers=admin_g).status_code == 403
    assert llm.requests == []


async def _plot(client, cid):
    from app.db.models import CampaignSecret

    async with client.app.state.master.maker() as s:
        return (await s.get(CampaignSecret, cid)).plot
