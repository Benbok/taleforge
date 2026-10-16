"""Recovery keeps an unresolved player request executable without granting effects."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.agents import intent as intents
from app.agents.llm import LLMError, ScriptedLLM
from app.agents.master.intent_recovery import recover_message_intent
from app.db.models import MasterTurn, Message
from app.main import create_app
from tests.conftest import login
from tests.game import QueueDice, import_base, party, run
from tests.test_ws import connect, wait_message_result


@pytest.fixture
def dice():
    return []


@pytest.fixture
def llm():
    return ScriptedLLM([])


@pytest.fixture
def game_client(settings, llm, dice):
    import_base(settings)
    with TestClient(create_app(settings, llm=llm, dice_factory=lambda: QueueDice(dice))) as client:
        yield client


@pytest.fixture
def admin_g(game_client):
    root = login(game_client, "root", "rootpass")
    response = game_client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root)
    assert response.status_code == 201, response.text
    return login(game_client, "Arty", "secret1")


def rows(settings, model, *where):
    async def query(session):
        return (await session.scalars(select(model).where(*where))).all()

    return run(settings, query)


def _message(*, actor_id: str = "hero-1"):
    return SimpleNamespace(
        campaign_id="campaign-1",
        seat_id="seat-1",
        actor_id=actor_id,
        content="Открываю дверь",
    )


def _parsed(actor_id: str = "hero-1") -> intents.ParseResult:
    return intents.ParseResult(
        intent={
            "kind": "action",
            "character_id": actor_id,
            "actions": [{"verb": "interact", "target_id": "door-1"}],
            "confidence": 0.95,
            "problem": "none",
        },
        kind="action",
    )


def test_recovery_accepts_one_validated_reparse_without_mutating_the_message():
    calls = []

    async def parse_intent(campaign_id, seat_id, content):
        calls.append((campaign_id, seat_id, content))
        return _parsed()

    ctx = SimpleNamespace(parse_intent=parse_intent)
    message = _message()

    result = asyncio.run(recover_message_intent(ctx, message))

    assert result.status == "recovered"
    assert result.reason == "validated_reparse"
    assert result.parse_result.intent["character_id"] == "hero-1"
    assert calls == [("campaign-1", "seat-1", "Открываю дверь")]
    assert not hasattr(message, "intent")


def test_recovery_requires_clarification_when_reparse_has_no_mechanical_actions():
    async def parse_intent(*args):
        return intents.ParseResult(intent={"kind": "action", "actions": [], "confidence": 0.95})

    result = asyncio.run(recover_message_intent(SimpleNamespace(parse_intent=parse_intent), _message()))

    assert result.status == "clarification_required"
    assert result.reason == "empty_actions"
    assert "уточните" in result.message.lower()


def test_recovery_rejects_a_reparse_for_a_different_hero():
    async def parse_intent(*args):
        return _parsed(actor_id="hero-2")

    result = asyncio.run(recover_message_intent(SimpleNamespace(parse_intent=parse_intent), _message()))

    assert result.status == "clarification_required"
    assert result.reason == "foreign_actor"


def test_recovery_converts_parser_timeout_to_clarification():
    async def parse_intent(*args):
        raise TimeoutError("parser timed out")

    result = asyncio.run(recover_message_intent(SimpleNamespace(parse_intent=parse_intent), _message()))

    assert result.status == "clarification_required"
    assert result.reason == "parser_timeout"


def test_recovery_converts_provider_400_to_safe_clarification():
    async def parse_intent(*args):
        raise LLMError("400 invalid request schema")

    result = asyncio.run(recover_message_intent(SimpleNamespace(parse_intent=parse_intent), _message()))

    assert result.status == "clarification_required"
    assert result.reason == "parser_error"
    assert "400" not in result.message


def _intent_reply(*actions):
    return {
        "tool_calls": [
            (
                "submit_intent",
                {"kind": "action", "actions": list(actions), "confidence": 1.0, "problem": "none"},
            )
        ]
    }


def test_empty_parser_result_preserves_original_request_for_master(game_client, admin_g, llm, settings):
    campaign, (player,), hero = party(game_client, admin_g)
    game_client.app.state.master.notify = lambda campaign_id: None
    llm.replies += [_intent_reply(), _intent_reply()]

    with connect(game_client, player, campaign["id"]) as (ws, _):
        ws.send_json(
            {
                "type": "message.send",
                "payload": {"kind": "action", "text": "Открываю дверь", "client_id": "recover-error"},
            }
        )
        event = wait_message_result(ws, client_id="recover-error", timeout_s=2.0)

    assert event["type"] == "message.new"
    assert len(llm.requests) == 1
    (message,) = rows(settings, Message, Message.kind == "action")
    assert message.intent["character_id"] == hero["id"]
    assert message.intent["parser_fallback"] is True
    assert message.content == "Открываю дверь"
    assert rows(settings, MasterTurn) == []


def test_gateway_recovery_saves_validated_message_for_its_owner(game_client, admin_g, llm, settings):
    campaign, (player,), hero = party(game_client, admin_g)
    game_client.app.state.master.notify = lambda campaign_id: None
    llm.replies += [_intent_reply({"verb": "inspect"})]

    with connect(game_client, player, campaign["id"]) as (ws, _):
        ws.send_json(
            {
                "type": "message.send",
                "payload": {"kind": "action", "text": "Осматриваюсь", "client_id": "recover-ok"},
            }
        )
        event = wait_message_result(ws, client_id="recover-ok", timeout_s=2.0)

    assert event["type"] == "message.new"
    saved = rows(settings, Message, Message.kind == "action")
    assert len(saved) == 1
    assert saved[0].seat_id is not None
    assert saved[0].intent["character_id"] == hero["id"]
    assert saved[0].intent["actions"][0]["verb"] == "inspect"
    assert len(llm.requests) == 1
