"""Ответы мастера на шёпот вне хода."""

from __future__ import annotations

import asyncio
import logging
import re

from sqlalchemy import func, select

from app.agents.llm import LLMError
from app.agents.master.common import MARKUP, WHISPER_HISTORY, render
from app.agents.master.helpers import _names, _render_history, _who
from app.agents.providers import explain
from app.core.campaigns import master_seat
from app.core.chat import active_session, next_seq, visible
from app.core.linker import link_text
from app.db.models import AgentConfig, Campaign, LlmCall, Message
from app.gateway.events import publish_message
from app.tools.runtime import open_context

log = logging.getLogger(__name__)


class WhisperMixin:
    """Часть MasterService (app/agents/master/service.py)."""

    # --- шёпот мастеру ---

    async def answer_whispers(self, cid: str) -> list[str]:
        """Шёпот мастеру — вопрос вне хода. ИИ-мастер отвечает сразу и только автору: коротко, строго на вопрос,
        без повествования для стола и без изменений мира. Ход мастера шёпоты не берёт. Возвращает id ответов."""
        out: list[str] = []
        async with self._whisper_locks.setdefault(cid, asyncio.Lock()):
            while (mid := await self._next_whisper(cid)) is not None:
                if answer := await self._answer_whisper(cid, mid):
                    out.append(answer)
        return out

    async def _next_whisper(self, cid: str) -> str | None:
        async with self.maker() as s:
            c = await s.get(Campaign, cid)
            if c is None or master_seat(c).occupant_type != "agent":
                return None
            game = await active_session(s, cid)
            if game is None:
                return None
            players = {x.id for x in c.seats if x.role == "player"}
            q = (
                select(Message)
                .where(Message.campaign_id == cid, Message.session_id == game.id, Message.kind == "whisper")
                .order_by(Message.seq)
            )
            for m in await s.scalars(q):
                if m.seat_id in players and (m.data or {}).get("answer") == "pending":
                    m.data = {**m.data, "answer": "processing"}  # второй вызов этот шёпот уже не возьмёт
                    await s.commit()
                    return m.id
        return None

    async def _answer_whisper(self, cid: str, mid: str) -> str | None:
        calls: list[LlmCall] = []
        await self._states(cid, [mid], "processing")
        reply_msg = error = None
        try:
            async with self.maker() as s:
                c = await s.get(Campaign, cid)
                m = await s.get(Message, mid)
                if c is None or m is None:
                    return None  # игрок отменил шёпот
                seat = master_seat(c)
                limit = (c.settings or {}).get("spend_limit_usd")
                if limit is not None:
                    spent = (await s.scalar(select(func.sum(LlmCall.cost)).where(LlmCall.campaign_id == cid))) or 0.0
                    if spent >= float(limit):
                        raise LLMError("лимит расходов на модели в настройках кампании исчерпан")
                cfg = await s.get(AgentConfig, seat.agent_config_id)
                ctx = await open_context(s, c, self.dice_factory(), turn_id=None, seat_id=seat.id)
                char_by_seat = {ch.seat_id: ch for ch in ctx.world.characters.values() if ch.seat_id}
                names = await _names(s, c)
                rows = await s.scalars(
                    select(Message)
                    .where(Message.campaign_id == cid, Message.seq < m.seq, Message.kind.notin_(("ooc", "roll")))
                    .order_by(Message.seq.desc())
                    .limit(WHISPER_HISTORY * 4)
                )
                seen = [x for x in rows if visible(x, m.seat_id)][:WHISPER_HISTORY]
                system = await self._system_prompt(s, c, cfg, ctx)
                prompt = render(
                    "whisper.j2",
                    who=_who(m, char_by_seat, names),
                    scene=ctx.world.scene_table(),
                    convo=_render_history(list(reversed(seen)), char_by_seat, names),
                    question=m.content,
                )
                known = set(ctx.world.characters) | set(ctx.world.entities)
                seat_id, author, session_id = seat.id, m.seat_id, m.session_id
                s.expunge(cfg)
                await s.rollback()  # база не держится, пока думает модель
            reply = await self._ask(
                calls,
                cfg,
                cid,
                seat_id,
                None,
                "whisper",
                [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
                None,
            )
            text = MARKUP.sub(lambda x: x.group(0) if x.group(1) in known else x.group(2), reply.text or "").strip()
            text = re.sub(r"\[\[[^\]]*$", "", text).rstrip()
            if not text:
                raise LLMError("модель вернула пустой ответ")
        except LLMError as e:
            error = explain(str(e))
        except Exception as e:  # noqa: BLE001 — сбой ответа на шёпот не должен ронять очередь
            log.exception("ответ на шёпот %s не удался", mid)
            error = f"{type(e).__name__}: {e}"
        async with self.maker() as s:
            s.add_all(calls)
            m = await s.get(Message, mid)
            if m is None:
                await s.commit()
                return None
            m.data = {**(m.data or {}), "answer": "failed" if error else "answered"}
            if error:
                reply_msg = Message(
                    campaign_id=cid,
                    session_id=m.session_id,
                    seq=await next_seq(s, cid),
                    kind="system",
                    visible_to=[m.seat_id],
                    content=f"Мастер не ответил на шёпот: {error}. Спросите ещё раз.",
                )
            else:
                reply_msg = Message(
                    campaign_id=cid,
                    session_id=session_id,
                    seq=await next_seq(s, cid),
                    seat_id=seat_id,
                    kind="narration",
                    visible_to=[author, seat_id],
                    content=await link_text(s, cid, text),
                    data={"whisper_reply": mid},
                )
            s.add(reply_msg)
            await s.commit()
        await publish_message(self.bus, reply_msg)
        await self._states(cid, [mid], "failed" if error else "answered")
        return None if error else reply_msg.id
