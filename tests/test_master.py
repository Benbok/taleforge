"""Ход ИИ-мастера целиком, с моделью на заданных ответах: инструменты, контракт намерения, аудитор разметки,
откат при сбое, учёт вызовов модели и проверка персонажа."""

from dataclasses import replace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents import prelude
from app.agents.llm import LLMError, ScriptedLLM
from app.db.models import CampaignSecret, Character, Event, LlmCall, MasterTurn
from app.main import create_app
from tests.conftest import login
from tests.game import FIGHTER, QueueDice, import_base, ok, party, run
from tests.test_adventure import publish_sample
from tests.test_api import invite, make_campaign, register
from tests.test_ws import connect, next_of

DONE = {"text": "готово"}


@pytest.fixture
def llm():
    return ScriptedLLM([])


@pytest.fixture
def dice():
    return []


@pytest.fixture
def game_client(settings, llm, dice):
    import_base(settings)
    with TestClient(create_app(settings, llm=llm, dice_factory=lambda: QueueDice(dice))) as c:
        yield c


@pytest.fixture
def admin_g(game_client):
    root = login(game_client, "root", "rootpass")
    r = game_client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root)
    assert r.status_code == 201, r.text
    return login(game_client, "Arty", "secret1")


def act(client, head, cid, text):
    """Игрок пишет действие и ждёт повествования мастера."""
    from app.db.models import Message

    with connect(client, head, cid) as (ws, _):
        ws.send_json({"type": "message.send", "payload": {"kind": "action", "text": text}})
        for _ in range(40):
            e = ws.receive_json()
            if (
                e["type"] == "message.new"
                and e["payload"]["kind"] in ("narration", "system")
                and not e["payload"].get("whisper")
            ):
                if e["payload"]["kind"] == "system" and "повторите" not in e["payload"]["content"]:
                    continue
                # ход дописывает учёт вызовов модели уже после повествования: ждём, чтобы не спорить за SQLite
                client.portal.call(client.app.state.master.wait_idle, cid)
                msg_id = e["payload"]["id"]

                async def get_msg(msg_id=msg_id):
                    async with client.app.state.sessionmaker() as s:
                        m = await s.get(Message, msg_id)
                        return m.content if m else ""

                content = client.portal.call(get_msg)
                return {**e["payload"], "content": content}
    raise AssertionError("мастер не ответил")


def rows(settings, model, *where):
    async def go(s):
        return (await s.scalars(select(model).where(*where))).all()

    return run(settings, go)


def test_turn_with_tool_and_markup_audit(game_client, admin_g, llm, dice, settings):
    c, (p1,), hero = party(game_client, admin_g)
    dice += [14]
    llm.replies += [
        {
            "tool_calls": [
                (
                    "roll_check",
                    {"character_id": hero["id"], "stat": "athletics", "difficulty": "dc.medium", "reason": "дверь"},
                )
            ]
        },
        DONE,
        {"text": f"[[{hero['id']}|Бран]] вышибает дверь, за ней [[en_ghost|призрак]]."},
        {"text": f"[[{hero['id']}|Бран]] вышибает дверь, за ней снова [[en_ghost|призрак]]."},
    ]
    n = act(game_client, p1, c["id"], "Вышибаю дверь плечом")
    assert n["kind"] == "narration"
    assert f"[[{hero['id']}|Бран]]" in n["content"] and "en_ghost" not in n["content"] and "призрак" in n["content"]

    decide = llm.requests[0]
    assert any(t["function"]["name"] == "roll_check" for t in decide["tools"])
    assert "review_character" not in {t["function"]["name"] for t in decide["tools"]}
    assert "Вышибаю дверь плечом" in decide["messages"][1]["content"]
    assert llm.requests[2]["tools"] is None  # повествование — без инструментов
    # результат броска ушёл модели
    tool_msg = next(m for m in llm.requests[1]["messages"] if m["role"] == "tool")
    assert '"ok": true' in tool_msg["content"] and '"total": 19' in tool_msg["content"]

    (turn,) = rows(settings, MasterTurn)
    assert turn.status == "done" and turn.trace["audit"]["regenerated"] and turn.trace["audit"]["stripped"]
    assert turn.trace["closed"] == [hero["id"]]
    (ev,) = rows(settings, Event, Event.tool == "roll_check")
    assert ev.turn_id == turn.id
    calls = rows(settings, LlmCall)
    assert [x.purpose for x in calls] == ["parse", "decide", "decide", "emotion", "narrate", "narrate"]


def test_silent_model_gets_auto_cancel(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)
    llm.replies += [DONE, DONE, {"text": "Ничего не происходит."}]
    n = act(game_client, p1, c["id"], "Лезу на башню")
    assert n["content"] == "Ничего не происходит."
    # после молчания модель переспросили про незакрытое действие
    assert "Не закрыты действия" in llm.requests[1]["messages"][-1]["content"]
    (ev,) = rows(settings, Event, Event.tool == "cancel_action")
    assert ev.target_id == hero["id"]


def test_narration_corrects_unregistered_numbered_enemies(game_client, admin_g, llm, settings):
    """Названные мастером враги не становятся настоящими без spawn_entity."""
    c, (p1,), _ = party(game_client, admin_g)
    llm.replies += [
        DONE,
        DONE,
        {"text": "Скелет 1 и Скелет 2 приближаются с мечами."},
        {"text": "Никого из противников рядом пока нет."},
    ]
    msg = act(game_client, p1, c["id"], "Бью ближайшего скелета")
    assert "Скелет 1" not in msg["content"]
    (turn,) = rows(settings, MasterTurn)
    assert turn.trace["audit"]["unregistered_actors"] == ["Скелет 1", "Скелет 2"]
    assert turn.trace["audit"]["regenerated"] is True
    assert "не зарегистрированы в текущей сцене" in llm.requests[-1]["messages"][-1]["content"]
    assert rows(settings, Event, Event.tool == "spawn_entity") == []


def test_narration_blocks_repeated_unregistered_enemies(game_client, admin_g, llm, settings):
    c, (p1,), _ = party(game_client, admin_g)
    llm.replies += [
        DONE,
        DONE,
        {"text": "Скелет 1 бежит на вас."},
        {"text": "Скелет 1 уже стоит перед вами."},
    ]
    msg = act(game_client, p1, c["id"], "Осматриваюсь")
    assert "Скелет 1" not in msg["content"]
    assert "отсутствуют в реестре мира" in msg["content"]
    (turn,) = rows(settings, MasterTurn)
    assert turn.trace["audit"]["blocked_actors"] == ["Скелет 1"]


def test_unregistered_named_actors_accepts_russian_case_declensions():
    from types import SimpleNamespace

    from app.agents.master.continuity import unregistered_named_actors

    class FakeWorld:
        def in_scene_entities(self):
            return [SimpleNamespace(name="Скелет 1")]

        characters = {"c1": SimpleNamespace(name="Иван")}
        entities = {}

    world = FakeWorld()
    assert unregistered_named_actors("Иван атакует Скелета 1 посохом.", world) == []
    assert unregistered_named_actors("Удар нанесён Скелету 1 в череп.", world) == []
    assert unregistered_named_actors("Бой со Скелетом 1 продолжается.", world) == []
    assert unregistered_named_actors("На Скелете 1 видны трещины.", world) == []
    assert unregistered_named_actors("Скелет 2 поднимает меч.", world) == ["Скелет 2"]
    assert unregistered_named_actors("Иван бьёт Зомби 1.", world) == ["Зомби 1"]


def test_failed_enter_room_does_not_spawn_or_claim_arrival(game_client, admin_g, llm, settings, monkeypatch):
    """Отказ входа прерывает batch: враги не появляются в прежней комнате."""

    async def no_intro(*_args, **_kw):
        return None

    monkeypatch.setattr(prelude, "prepare_campaign_intro", no_intro)
    mid = publish_sample(settings)
    c, (p1,), hero = party(game_client, admin_g, module_id=mid, module_hook="board")
    game_client.portal.call(game_client.app.state.master.wait_idle, None)
    (before,) = rows(settings, Character, Character.id == hero["id"])
    initial = before.location_id
    llm.replies += [
        {
            "tool_calls": [
                ("enter_room", {"room": "99"}),
                ("spawn_entity", {"creature_template_id": "creature.skeleton", "name": "Скелет 1"}),
            ]
        },
        DONE,
        DONE,
        {"text": "Вы вошли в комнату 99; скелет уже смотрит вам в глаза."},
    ]
    message = act(game_client, p1, c["id"], "Вхожу в комнату 99; внутри скелет.")
    (after,) = rows(settings, Character, Character.id == hero["id"])
    assert after.location_id == initial
    assert rows(settings, Event, Event.tool == "spawn_entity") == []
    (turn,) = rows(settings, MasterTurn)
    diag = [(x["tool"], x["result"].get("ok")) for x in turn.trace["calls"]]
    assert diag[:2] == [("enter_room", False), ("spawn_entity", False)], (diag, [bool(q["tools"]) for q in llm.requests])
    assert "не выполнено после ошибки перехода" in turn.trace["calls"][1]["result"]["error"]
    assert "не состоялся" in message["content"].lower()
    assert "вы вошли" not in message["content"].lower()
    assert initial in message["content"] or before.name in message["content"] or "остался" in message["content"]


def test_transition_retry_can_succeed(game_client, admin_g, llm, settings, monkeypatch):
    """Ранний отказ не перечёркивает успешный повтор и спавн в НОВОЙ комнате."""

    async def no_intro(*_args, **_kw):
        return None

    monkeypatch.setattr(prelude, "prepare_campaign_intro", no_intro)
    mid = publish_sample(settings)
    c, (p1,), hero = party(game_client, admin_g, module_id=mid, module_hook="board")
    game_client.portal.call(game_client.app.state.master.wait_idle, None)
    llm.replies += [
        {
            "tool_calls": [
                ("enter_room", {"room": "99"}),
                ("spawn_entity", {"creature_template_id": "creature.skeleton", "name": "Ненастоящий"}),
            ]
        },
        {
            "tool_calls": [
                ("enter_room", {"room": "2"}),
                ("spawn_entity", {"creature_template_id": "creature.skeleton", "name": "Скелет 1"}),
            ]
        },
        DONE,
        {"text": "Герой входит в Восточную крипту. Здесь появился Скелет 1."},
    ]
    message = act(game_client, p1, c["id"], "Перехожу в комнату 2.")
    (hero_now,) = rows(settings, Character, Character.id == hero["id"])
    (turn,) = rows(settings, MasterTurn)
    entered = rows(settings, Event, Event.tool == "enter_room", Event.turn_id == turn.id)
    assert len(entered) == 1 and hero_now.location_id == entered[0].target_id, [
        (x.tool, x.target_id) for x in entered
    ]
    assert [c["tool"] for c in turn.trace["calls"][:4]] == [
        "enter_room",
        "spawn_entity",
        "enter_room",
        "spawn_entity",
    ]
    assert [c["result"]["ok"] for c in turn.trace["calls"][:4]] == [False, False, True, True]
    assert hero["id"] in turn.trace["closed"]  # enter_room без character_ids закрыл реальное действие
    spawned = rows(settings, Event, Event.tool == "spawn_entity")
    assert len(spawned) == 1 and spawned[0].turn_id == turn.id
    assert "Восточную крипту" in message["content"]
    assert "не состоялся" not in message["content"]


def test_failed_turn_rolls_back(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)
    llm.replies += [
        {"tool_calls": [("spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин"})]},
        # дальше ответы кончаются: модель «упала» посреди хода
    ]
    n = act(game_client, p1, c["id"], "Осматриваюсь")
    assert n["kind"] == "system" and "повторите" in n["content"]
    (turn,) = rows(settings, MasterTurn)
    assert turn.status == "failed" and "LLMError" in turn.trace["error"]
    assert rows(settings, Event, Event.tool == "spawn_entity") == []  # гоблин не остался в мире
    calls = rows(settings, LlmCall)
    assert len(calls) == 3 and calls[-1].error


def test_ai_master_reviews_character(game_client, admin_g, llm, settings):  # noqa: ARG001
    c = make_campaign(game_client, admin_g, players=1)
    p1 = register(game_client, invite(game_client, admin_g, c["id"])["token"], "Арагорн")
    ch = ok(game_client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=p1), 201)
    llm.replies += [
        {
            "tool_calls": [
                (
                    "review_character",
                    {"character_id": ch["id"], "approve": True, "comment": "Годится", "secret_link": "Гарнизон ищет"},
                )
            ]
        }
    ]
    with connect(game_client, p1, c["id"]) as (ws, _):
        res = ok(game_client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/submit", headers=p1))
        assert res["status"] == "submitted"
        e = next_of(ws, "character.reviewed")
    assert e["payload"]["status"] == "approved" and e["payload"]["comment"] == "Годится"
    # тайная связь — только в скрытых данных мастера
    (secret,) = rows(settings, CampaignSecret)
    assert secret.plot["character_links"][ch["id"]] == "Гарнизон ищет"
    view = ok(game_client.get(f"/api/campaigns/{c['id']}/characters/{ch['id']}", headers=p1))
    assert "Гарнизон" not in str(view)


def test_failed_ai_review_is_visible_and_owner_can_approve(game_client, admin_g, llm, settings):  # noqa: ARG001
    """Модель недоступна: герой не висит молча, игрок и владелец видят причину, владелец проверяет сам."""
    c = make_campaign(game_client, admin_g, players=1)
    p1 = register(game_client, invite(game_client, admin_g, c["id"])["token"], "Арагорн")
    ch = ok(game_client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=p1), 201)

    def down(messages, tools):
        raise LLMError("AuthenticationError: invalid x-api-key")

    llm.replies += [down]
    base = f"/api/campaigns/{c['id']}/characters"
    with connect(game_client, p1, c["id"]) as (ws, _):
        ok(game_client.post(f"{base}/{ch['id']}/submit", headers=p1))
        e = next_of(ws, "character.review_failed")
    assert "отклонил ключ" in e["payload"]["error"]
    mine = ok(game_client.get(f"{base}/{ch['id']}", headers=p1))
    assert mine["reviewer"] == "ai" and "отклонил ключ" in mine["review_error"]
    # владелец (мастер — ИИ) видит героя на проверке целиком
    listed = {x["id"]: x for x in ok(game_client.get(base, headers=admin_g))}
    assert listed[ch["id"]]["status"] == "submitted" and "sheet" in listed[ch["id"]]
    # повтор проверки ИИ после смены модели
    llm.replies += [
        {"tool_calls": [("review_character", {"character_id": ch["id"], "approve": False, "comment": "Имя?"})]}
    ]
    assert game_client.post(f"{base}/{ch['id']}/review/retry-ai", headers=admin_g).status_code == 202
    game_client.portal.call(game_client.app.state.master.wait_idle)
    back = ok(game_client.get(f"{base}/{ch['id']}", headers=p1))
    assert back["status"] == "draft" and back["review_comment"] == "Имя?"
    ok(game_client.post(f"{base}/{ch['id']}/submit", headers=p1))
    game_client.portal.call(game_client.app.state.master.wait_idle)  # ответов у модели нет — снова сбой
    assert ok(game_client.get(f"{base}/{ch['id']}", headers=p1))["review_error"]
    approved = ok(game_client.post(f"{base}/{ch['id']}/review", json={"approve": True}, headers=admin_g))
    assert approved["status"] == "approved"


def test_master_log_for_admins_with_secret_switch(game_client, admin_g, llm, dice):
    c, (p1,), hero = party(game_client, admin_g)
    dice += [14, 3]
    check = {"character_id": hero["id"], "difficulty": "dc.medium"}
    llm.replies += [
        {
            "tool_calls": [
                ("roll_check", {**check, "stat": "athletics", "reason": "дверь"}),
                ("roll_check", {**check, "stat": "perception", "reason": "засада"}),
                ("whisper", {"character_id": hero["id"], "text": "Ты слышишь шорох за дверью"}),
            ]
        },
        DONE,
        {"text": f"[[{hero['id']}|Бран]] вышибает дверь."},
    ]
    act(game_client, p1, c["id"], "Вышибаю дверь и прислушиваюсь")
    url = f"/api/campaigns/{c['id']}/master-log"

    assert game_client.get(url, headers=p1).status_code == 403  # игрок журнал не видит

    log = ok(game_client.get(url, headers=admin_g))
    assert log["secrets_visible"] is True
    (turn,) = log["turns"]
    assert turn["status"] == "done" and turn["session_id"]
    athletics, perception, whisper = turn["calls"]
    assert athletics["tool"] == "roll_check" and not athletics["secret"]
    assert athletics["result"]["total"] == 19 and athletics["result"]["success"] is True
    assert athletics["args"]["reason"] == "дверь"
    assert perception["secret"] and perception["result"]["stat"] == "perception"
    assert whisper["secret"] and "шорох" in whisper["args"]["text"]
    assert [x["purpose"] for x in turn["llm"]] == ["decide", "decide", "emotion", "narrate"]
    assert turn["audit"] == {"regenerated": False, "stripped": []}
    assert [x["purpose"] for x in log["service_llm"]] == ["parse"]

    # Переключатель: секретное остаётся в журнале только как факт, без содержимого
    game_client.app.state.settings = replace(game_client.app.state.settings, master_log_secrets=False)
    log = ok(game_client.get(url, headers=admin_g))
    assert log["secrets_visible"] is False
    athletics, perception, whisper = log["turns"][0]["calls"]
    assert athletics["result"]["total"] == 19
    assert perception == {"tool": "roll_check", "secret": True}
    assert whisper == {"tool": "whisper", "secret": True}
