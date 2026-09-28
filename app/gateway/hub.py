"""Доставка событий подключённым клиентам кампании.

Событие публикуется в шину вместе со списком мест, которым оно видно. Каждый процесс сервера
сам фильтрует его для своих сокетов: шёпот и скрытое мастера не уходят в чужой сокет (ТЗ, раздел 12).
С одним процессом хватает шины в памяти; при нескольких воркерах — Redis pub/sub (REDIS_URL).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Protocol

from starlette.websockets import WebSocket

log = logging.getLogger(__name__)


@dataclass(eq=False)
class Connection:
    websocket: WebSocket
    user_id: str
    campaign_id: str
    seat_id: str | None
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    async def send(self, envelope: dict[str, Any]) -> None:
        async with self.send_lock:
            await self.websocket.send_json(envelope)


class Hub:
    """Сокеты этого процесса, сгруппированные по кампаниям."""

    def __init__(self) -> None:
        self._by_campaign: dict[str, set[Connection]] = defaultdict(set)

    def add(self, conn: Connection) -> None:
        self._by_campaign[conn.campaign_id].add(conn)

    def remove(self, conn: Connection) -> None:
        conns = self._by_campaign.get(conn.campaign_id)
        if conns is not None:
            conns.discard(conn)
            if not conns:
                del self._by_campaign[conn.campaign_id]

    def online_users(self, campaign_id: str) -> set[str]:
        return {c.user_id for c in self._by_campaign.get(campaign_id, ())}

    async def deliver(self, campaign_id: str, envelope: dict[str, Any], visible_to: list[str] | None) -> None:
        for conn in list(self._by_campaign.get(campaign_id, ())):
            if visible_to is not None and conn.seat_id not in visible_to:
                continue
            try:
                await conn.send(envelope)
            except Exception:  # noqa: BLE001 — оборванный сокет уберёт его собственный обработчик
                log.debug("не удалось отправить в сокет", exc_info=True)


class Bus(Protocol):
    async def publish(self, campaign_id: str, envelope: dict[str, Any], visible_to: list[str] | None) -> None: ...

    async def start(self) -> None: ...

    async def stop(self) -> None: ...


class MemoryBus:
    def __init__(self, hub: Hub) -> None:
        self.hub = hub

    async def publish(self, campaign_id: str, envelope: dict[str, Any], visible_to: list[str] | None) -> None:
        await self.hub.deliver(campaign_id, envelope, visible_to)

    async def start(self) -> None:
        pass

    async def stop(self) -> None:
        pass


class RedisBus:
    CHANNEL = "taleforge:campaign"

    def __init__(self, hub: Hub, url: str) -> None:
        import redis.asyncio as redis

        self.hub = hub
        self.redis = redis.from_url(url)
        self._task: asyncio.Task | None = None

    async def publish(self, campaign_id: str, envelope: dict[str, Any], visible_to: list[str] | None) -> None:
        data = json.dumps({"campaign_id": campaign_id, "envelope": envelope, "visible_to": visible_to})
        await self.redis.publish(self.CHANNEL, data)

    async def start(self) -> None:
        pubsub = self.redis.pubsub()
        await pubsub.subscribe(self.CHANNEL)

        async def pump() -> None:
            async for item in pubsub.listen():
                if item.get("type") != "message":
                    continue
                try:
                    data = json.loads(item["data"])
                    await self.hub.deliver(data["campaign_id"], data["envelope"], data["visible_to"])
                except Exception:  # noqa: BLE001
                    log.exception("не удалось разобрать событие из Redis")

        self._task = asyncio.create_task(pump())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
        await self.redis.aclose()
