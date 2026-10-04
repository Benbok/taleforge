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


class Stream:
    """Черновик сообщения мастера по кускам. Каждый кусок несёт поля сообщения, чтобы клиент показал его
    до message.new; само сообщение уходит в чат только после коммита."""

    def __init__(self, bus, cid: str, msg: Message) -> None:
        self.bus, self.cid = bus, cid
        self.head = {"id": msg.id, "seq": msg.seq, "seat_id": msg.seat_id, "kind": msg.kind}

    async def push(self, chunk: str) -> None:
        await self.bus.publish(self.cid, envelope("message.chunk", self.cid, {**self.head, "chunk": chunk}), None)

    async def reset(self) -> None:
        payload = {**self.head, "chunk": "", "reset": True}
        await self.bus.publish(self.cid, envelope("message.chunk", self.cid, payload), None)
