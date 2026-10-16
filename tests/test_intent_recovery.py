"""Recovery keeps an unresolved player request executable without granting effects."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.agents import intent as intents
from app.agents.llm import LLMError
from app.agents.master.intent_recovery import recover_message_intent


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
