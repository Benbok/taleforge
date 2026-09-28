# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Связи героев, личные крючки и вступление мастера (проект «Подготовка кампании», разделы 5 и 7.1)."""

from app.agents import prelude
from app.core import bonds, plot
from app.db.models import Character, LlmCall, Message, Scene
from tests.game import FIGHTER, ok, party
from tests.test_api import invite, make_campaign, register
from tests.test_lead import checked, set_plan
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


def test_ai_master_asks_hooks_and_introduces(game_client, admin_g, llm, settings):
    c, (p1, p2), hero = party(game_client, admin_g, players=2, brief={"length": "short"})
    cid = c["id"]
    set_plan(settings, cid, checked())
    url = f"/api/campaigns/{cid}/characters/{hero['id']}/bonds"

    # вопросы мастера под завязку
    llm.replies += [
        {"tool_calls": [(prelude.QUESTIONS_TOOL, {"questions": ["Что у тебя отнял туман?", "Кому ты верен?"]})]}
    ]
    r = ok(game_client.get(url, headers=p1))
    assert r["bonds"]["status"] == "asking" and r["bonds"]["source"] == "default"
    game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    q = llm.requests[0]["messages"][1]["content"]
    assert "Бран" in q and "Бежал из гарнизона" in q and "Злодеи (тайно): Мать Ирса" in q
    r = ok(game_client.get(url, headers=p1))
    assert (
        r["bonds"]["source"] == "master"
        and [x["text"] for x in r["bonds"]["questions"]][0] == "Что у тебя отнял туман?"
    )

    # ответ → личный крючок; неверную привязку сервер возвращает модели
    llm.replies += [
        {"tool_calls": [(prelude.HOOK_TOOL, {"ref": "n_nope", "text": "?"})]},
        {"tool_calls": [(prelude.HOOK_TOOL, {"ref": "npc_warden", "text": "Бертольд сдал брата Брана культу"})]},
    ]
    body = {"answers": [{"id": "q1", "text": "Брата"}, {"id": "q2", "text": "Капитану Марте", "private": True}]}
    ok(game_client.put(url, json=body, headers=p1))
    game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    assert "ref: нужен один из" in llm.requests[2]["messages"][-1]["content"]
    assert "Капитану Марте (лично" in llm.requests[1]["messages"][1]["content"]
    secret = game_client.portal.call(_plot, game_client, cid)
    assert secret["hooks"][hero["id"]]["ref"] == "npc_warden"

    # новая сессия: мастер представляет отряд; каркас и личные ответы в текст для всех не попадают
    llm.replies += [{"text": f"[[{hero['id']}|Бран]] стоит у причала, рядом [[en_x|незнакомец]]."}]
    ok(game_client.post(f"/api/campaigns/{cid}/session/pause", headers=admin_g))
    game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    ok(game_client.post(f"/api/campaigns/{cid}/session/start", headers=admin_g))
    game_client.portal.call(game_client.app.state.master.wait_idle, cid)
    intro_req = llm.requests[3]
    text = intro_req["messages"][1]["content"]
    assert "120–200 слов" in text and "Брата" in text and "Капитану Марте" not in text
    assert "Первая сцена (тайно" in text and "Бертольд сдал брата" in text
    msg = rows(settings, Message, Message.campaign_id == cid, Message.kind == "narration")[-1]
    assert msg.content == f"[[{hero['id']}|Бран]] стоит у причала, рядом незнакомец."
    (scene,) = rows(settings, Scene, Scene.campaign_id == cid)
    assert scene.state["introduced"] == [hero["id"]]

    # новичок посреди сессии: короткое появление перед ходом мастера
    ch2 = ok(game_client.post(f"/api/campaigns/{cid}/characters", json=FIGHTER | {"name": "Гимли"}, headers=p2), 201)
    assert (
        ok(game_client.post(f"/api/campaigns/{cid}/characters/{ch2['id']}/submit", headers=p2))["status"] == "approved"
    )
    llm.replies += [{"text": "Гимли выходит из тумана."}, DONE, DONE, {"text": "Причал пуст."}]
    first = act(game_client, p1, cid, "Жду")
    assert first["content"] == "Гимли выходит из тумана."
    assert "50–100 слов" in llm.requests[4]["messages"][1]["content"]
    assert (
        "Гимли" in llm.requests[4]["messages"][1]["content"]
        and "Бран (" not in llm.requests[4]["messages"][1]["content"]
    )
    purposes = [x.purpose for x in rows(settings, LlmCall) if x.purpose not in ("summary", "parse")]
    assert purposes[:5] == ["bonds", "hook", "hook", "intro", "intro"]
    # ответы о связях видит мастер в ходе
    assert "Связи героев (ответы игроков)" in llm.requests[5]["messages"][0]["content"]


async def _plot(client, cid):
    from app.db.models import CampaignSecret

    async with client.app.state.master.maker() as s:
        return (await s.get(CampaignSecret, cid)).plot


def test_review_links_hero_to_plan(game_client, admin_g, llm, settings):
    c = make_campaign(game_client, admin_g, players=1, brief={"length": "short"})
    set_plan(settings, c["id"], checked())
    p1 = register(game_client, invite(game_client, admin_g, c["id"])["token"], "Арагорн")
    ch = ok(game_client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=p1), 201)
    args = {"character_id": ch["id"], "approve": True, "secret_link": "Гарнизон служит Бертольду"}
    llm.replies += [
        {"tool_calls": [("review_character", args | {"hook_ref": "n_nope"})]},
        {"tool_calls": [("review_character", args | {"hook_ref": "npc_warden"})]},
    ]
    ok(game_client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/submit", headers=p1))
    game_client.portal.call(game_client.app.state.master.wait_idle, c["id"])
    assert "hook_ref" in llm.requests[0]["messages"][1]["content"]
    p = game_client.portal.call(_plot, game_client, c["id"])
    assert p["hooks"][ch["id"]] == {"name": "Бран", "ref": "npc_warden", "text": "Гарнизон служит Бертольду"}
    assert p["character_links"][ch["id"]] == "Гарнизон служит Бертольду"
