"""Bounded recovery of player intent after an unresolved parser result."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from app.agents import intent as intents
from app.agents.llm import LLMError


@dataclass(frozen=True)
class IntentRecoveryResult:
    status: Literal["recovered", "clarification_required"]
    reason: str
    message: str
    parse_result: intents.ParseResult | None = None


async def recover_message_intent(ctx, message) -> IntentRecoveryResult:
    """Reparse one unresolved message once, without authorizing any mutation."""
    try:
        parsed = await ctx.parse_intent(message.campaign_id, message.seat_id, message.content)
    except TimeoutError:
        return IntentRecoveryResult(
            status="clarification_required",
            reason="parser_timeout",
            message="Не удалось вовремя разобрать действие. Уточните, что делает ваш герой.",
        )
    except LLMError:
        return IntentRecoveryResult(
            status="clarification_required",
            reason="parser_error",
            message="Не удалось разобрать действие. Уточните, что делает ваш герой.",
        )

    intent = parsed.intent if isinstance(parsed, intents.ParseResult) else None
    if not isinstance(intent, dict):
        return IntentRecoveryResult(
            status="clarification_required",
            reason="missing_intent",
            message="Не удалось разобрать действие. Уточните, что делает ваш герой.",
            parse_result=parsed if isinstance(parsed, intents.ParseResult) else None,
        )
    expected_actor = getattr(message, "actor_id", None)
    if expected_actor and intent.get("character_id") is not None and intent.get("character_id") != expected_actor:
        return IntentRecoveryResult(
            status="clarification_required",
            reason="foreign_actor",
            message="Нельзя выполнять действие за чужого героя. Уточните, что делает ваш герой.",
            parse_result=parsed,
        )
    actions = intent.get("actions")
    if not isinstance(actions, list) or not actions:
        reason = "speech_only" if intent.get("kind") == "speech" else "empty_actions"
        return IntentRecoveryResult(
            status="clarification_required",
            reason=reason,
            message="В заявке нет исполнимого действия. Уточните, что делает ваш герой.",
            parse_result=parsed,
        )
    if parsed.reject:
        return IntentRecoveryResult(
            status="clarification_required",
            reason="parser_rejected",
            message=parsed.reject,
            parse_result=parsed,
        )
    return IntentRecoveryResult(
        status="recovered",
        reason="validated_reparse",
        message="",
        parse_result=parsed,
    )
