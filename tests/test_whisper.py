"""Шёпот мастеру: ИИ-мастер отвечает сразу, только автору и строго на вопрос — без хода и повествования для стола."""
# ruff: noqa: F811 — фикстуры из test_master приходят в тесты параметрами

from app.agents.llm import LLMError
from app.db.models import LlmCall, MasterTurn, Message
from tests.game import party
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры
from tests.test_ws import connect, next_of


def whisper(client, head, cid, text):
    """Игрок шепчет мастеру и ждёт ответа (или отказа с причиной) — только своего."""
    with connect(client, head, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "whisper", "text": text}})
        mine = next_of(ws, "message.new")["payload"]
        assert mine["kind"] == "whisper" and mine["state"] == "pending"
        answer = next_of(ws, "message.new")["payload"]
        client.portal.call(client.app.state.master.wait_idle, cid)
    return mine, answer


def test_whisper_answered_privately_without_turn(game_client, admin_g, llm, settings):
    c, (p1, p2), hero = party(game_client, admin_g, players=2)
    llm.replies += [{"text": "Ловушек ты не видишь, но пол у двери подозрительно чистый."}]
    with connect(game_client, p2, c["id"]) as (other, _):
        mine, answer = whisper(game_client, p1, c["id"], "мастер, тут есть ловушки?")
        other.send_json({"type": "actions.get", "payload": {}})
        assert next_of(other, "state.actions")  # другому игроку ни шёпот, ни ответ не пришли
    assert answer["kind"] == "narration" and answer["whisper"] and answer["data"] == {"whisper_reply": mine["id"]}
    assert answer["content"].startswith("Ловушек ты не видишь")

    # один запрос к модели, без инструментов, с вопросом игрока; хода мастера не было
    assert len(llm.requests) == 1 and llm.requests[0]["tools"] is None
    prompt = llm.requests[0]["messages"][1]["content"]
    assert "мастер, тут есть ловушки?" in prompt and "строго на этот вопрос" in prompt
    assert rows(settings, MasterTurn, MasterTurn.campaign_id == c["id"]) == []
    assert [x.purpose for x in rows(settings, LlmCall, LlmCall.campaign_id == c["id"])] == ["whisper"]
    w = rows(settings, Message, Message.id == mine["id"])[0]
    assert w.data == {"answer": "answered"}

    with connect(game_client, p1, c["id"]) as (_, snap):
        states = {m["id"]: m["state"] for m in snap["payload"]["messages"]}
        assert states[mine["id"]] == "answered" and snap["payload"]["pending"] is None
    with connect(game_client, p2, c["id"]) as (_, snap):
        assert {mine["id"], answer["id"]}.isdisjoint(m["id"] for m in snap["payload"]["messages"])


def test_where_am_i_whisper_uses_actual_hero_location(game_client, admin_g, llm, settings):
    from app.db.models import Character, Entity, Scene
    from tests.game import run

    c, (p1,), hero = party(game_client, admin_g)

    async def actual_place(s):
        ch = await s.get(Character, hero["id"])
        scene = await s.get(Scene, c["id"])
        loc = await s.get(Entity, ch.location_id or scene.location_id)
        return loc.name

    here = run(settings, actual_place)
    llm.replies += [{"text": "Вы точно на другом конце света, в тайном логове."}]
    _, answer = whisper(game_client, p1, c["id"], "где я?")
    assert here in answer["content"]
    assert "тайном логове" not in answer["content"]
    assert len(llm.requests) == 0  # этот известный факт сервер берёт непосредственно из мира


def test_turn_does_not_take_whisper(game_client, admin_g, llm):
    c, (p1,), hero = party(game_client, admin_g)
    llm.replies += [{"text": "Дверь заперта изнутри."}]
    whisper(game_client, p1, c["id"], "дверь заперта?")
    llm.replies += [DONE, {"text": "Ты оглядываешь зал."}]
    act(game_client, p1, c["id"], "Осматриваю зал")
    news = llm.requests[1]["messages"][1]["content"].split("Новые реплики игроков:")[1]
    assert "Осматриваю зал" in news and "дверь заперта?" not in news


def test_failed_whisper_explains_reason(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)

    def boom(messages, tools):
        raise LLMError("RateLimitError: слишком много запросов")

    llm.replies += [boom]
    mine, answer = whisper(game_client, p1, c["id"], "сколько стоит факел?")
    assert answer["kind"] == "system" and answer["whisper"]
    assert "Мастер не ответил на шёпот" in answer["content"] and "слишком много запросов" in answer["content"]
    with connect(game_client, p1, c["id"]) as (_, snap):
        states = {m["id"]: m["state"] for m in snap["payload"]["messages"]}
        assert states[mine["id"]] == "failed" and snap["payload"]["pending"] is None
    llm.replies += [{"text": "Одна медная монета."}]
    assert whisper(game_client, p1, c["id"], "сколько стоит факел?")[1]["content"] == "Одна медная монета."
