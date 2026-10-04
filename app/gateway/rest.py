"""Голосование за отдых (app/tools/rest.py) со стороны сокета: голос игрока за своего героя и срок голосования.

Голосование живёт в состоянии сцены, а не в памяти процесса: после перезапуска сервера сроки заводятся заново.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from sqlalchemy import select

from app.core.campaigns import NotFound, get_viewer
from app.db.models import Scene, User
from app.gateway.hub import Connection
from app.tools import rest as rest_tools
from app.tools.registry import ToolError
from app.tools.runtime import NOTICE_HOOKS, flush_outbox, open_context, publish_changes

log = logging.getLogger(__name__)


class RestVotes:
    def __init__(self, maker, bus, master, dice_factory) -> None:
        self.maker, self.bus, self.master, self.dice_factory = maker, bus, master, dice_factory
        self._timers: dict[str, asyncio.Task] = {}
        NOTICE_HOOKS["rest.vote"] = self._on_vote

    def _on_vote(self, cid: str, payload: dict[str, Any]) -> None:
        vid = payload["vote_id"]
        if vid in self._timers:
            return
        try:
            self._timers[vid] = asyncio.get_running_loop().create_task(self._expire_at(cid, vid, payload["deadline"]))
        except RuntimeError:  # нет цикла событий (синхронный вызов в тестах): срок проверится при следующем голосе
            pass

    async def _expire_at(self, cid: str, vid: str, deadline: float) -> None:
        try:
            await asyncio.sleep(max(0.0, float(deadline) - time.time()))
            await self._run(cid, None, lambda ctx: rest_tools.expire(ctx, vid))
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("срок голосования за отдых в кампании %s", cid)
        finally:
            self._timers.pop(vid, None)

    async def resume(self) -> None:
        """После перезапуска: снова завести сроки открытых голосований."""
        async with self.maker() as s:
            rows = (await s.scalars(select(Scene))).all()
            pending = [(sc.campaign_id, v) for sc in rows for v in ((sc.state or {}).get("rest_votes") or {}).values()]
        for cid, v in pending:
            self._on_vote(cid, {"vote_id": v["id"], "deadline": v["deadline"]})

    async def stop(self) -> None:
        for t in list(self._timers.values()):
            t.cancel()
        self._timers.clear()

    async def cast(self, user: User, conn: Connection, payload: dict) -> str | None:
        """Голос игрока за своего героя (или за героя ушедшего, которого он ведёт). Возвращает причину отказа."""
        hero, vid = str(payload.get("character_id") or ""), str(payload.get("vote_id") or "")
        choice = str(payload.get("choice") or "")
        hd = payload.get("hit_dice")
        try:
            hit_dice = None if hd in (None, "", "auto") else max(0, int(hd))
        except (TypeError, ValueError):
            return "кости хитов — число или «авто»"

        async def act(ctx):
            ch = ctx.world.characters.get(hero)
            if ch is None:
                raise ToolError("нет такого героя в кампании")
            if ch.seat_id != conn.seat_id and ch.seat_id not in conn.stand_in:
                raise ToolError("голосуют за своего героя: этот герой не ваш")
            return await rest_tools.ballot(ctx, vid, hero, choice, hit_dice)

        return await self._run(conn.campaign_id, user, act)

    async def _run(self, cid: str, user: User | None, fn) -> str | None:
        async with self.maker() as session:
            from app.db.models import Campaign

            c = await session.get(Campaign, cid)
            if c is None:
                return "кампания не найдена"
            if user is not None:
                try:
                    await get_viewer(session, user, cid)
                except NotFound as e:
                    return str(e)
            ctx = await open_context(session, c, self.dice_factory(), turn_id=None, seat_id=None)
            try:
                await fn(ctx)
            except ToolError as e:
                await session.rollback()
                return str(e)
            messages = await flush_outbox(session, ctx)
            await session.commit()
        await publish_changes(self.bus, ctx, messages)
        if "combat_started" in ctx.signals and self.master is not None:
            # засада: первыми могут ходить существа, а игроки увидят, чей ход
            self.master._spawn(self.master.advance(cid, "sync"))
        return None


async def snapshot_votes(session, campaign, seat_id: str | None, stand_in: set[str], is_master: bool) -> list[dict]:
    """Открытые голосования за отдых, которые видит этот зритель: его группы или все — мастеру."""
    sc = await session.get(Scene, campaign.id)
    votes = list(((sc.state or {}).get("rest_votes") or {}).values()) if sc else []
    if not votes:
        return []
    from app.content.catalog import campaign_catalog
    from app.core.world import load_world
    from app.tools.registry import ToolContext

    world = await load_world(session, campaign, await campaign_catalog(session, campaign))
    ctx = ToolContext(session, campaign, world, None, None, None, None)
    out = []
    for v in votes:
        seats = set(rest_tools._audience(ctx, v))
        if is_master or seat_id in seats or stand_in & seats:
            out.append(rest_tools.public(ctx, v))
    return out
