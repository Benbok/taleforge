"""Конверт событий WebSocket (ТЗ, раздел 12): {type, campaign_id, seq, payload}."""

from __future__ import annotations

from typing import Any

from app.core.chat import message_payload
from app.db.models import Message

PROTOCOL_VERSION = 1


def envelope(type_: str, campaign_id: str | None, payload: dict[str, Any], seq: int | None = None) -> dict[str, Any]:
    return {"type": type_, "campaign_id": campaign_id, "seq": seq, "payload": payload}


async def publish_message(bus, msg: Message, names: dict[str, str] | None = None, state: str | None = None) -> None:
    await bus.publish(
        msg.campaign_id,
        envelope("message.new", msg.campaign_id, message_payload(msg, names, state), msg.seq),
        msg.visible_to,
    )
