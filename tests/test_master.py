"""Ход ИИ-мастера целиком, с моделью на заданных ответах: инструменты, контракт намерения, аудитор разметки,
откат при сбое, учёт вызовов модели и проверка персонажа."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents.llm import ScriptedLLM
from app.main import create_app
from tests.conftest import login
from tests.game import QueueDice, import_base, run
from tests.test_ws import connect

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
                text = e["payload"]["content"]
                # конец хода: откат («повторите действие») или сохранённое действие без описания
                if e["payload"]["kind"] == "system" and "повторите" not in text and "сохранено" not in text:
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
