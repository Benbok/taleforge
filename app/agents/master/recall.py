"""Память мастера (раздел 9): блок памяти, сводки, пересказ пропущенного (раздел 11)."""

from __future__ import annotations

import logging

from sqlalchemy import select

from app.agents import intent as intents
from app.agents import memory
from app.agents.llm import LLMError, parser_model_for
from app.agents.master.common import CATCH_UP_SYSTEM, MARKUP
from app.agents.master.helpers import _names, _who
from app.core.campaigns import master_seat
from app.core.chat import active_session, next_seq, visible
from app.db.models import AgentConfig, Campaign, Character, LlmCall, Message, Summary
from app.gateway.events import envelope, publish_message
from app.tools.registry import ToolContext
from app.tools.runtime import open_context

log = logging.getLogger(__name__)


class RecallMixin:
    """Часть MasterService (app/agents/master/service.py)."""

    # --- память (раздел 9) ---

    async def _memory_block(self, s, c: Campaign, ctx: ToolContext, new: list[Message]) -> str:
        """Сводка кампании и фрагменты правил и лора, найденные по новым репликам и месту действия."""
        parts = []
        last = await memory.latest(s, c.id)
        text = memory.render_content(last.content) if last else ""
        if text:
            parts.append("Сводка кампании (без чисел: числа только в таблице сцены):\n" + text)
        loc = ctx.world.entities.get(ctx.world.home() or "")
        query = " ".join(
            [m.content for m in new]
            + [intents.describe(m.intent) for m in new if m.intent]
            + ([loc.name] if loc else [])
        )
        found = memory.knowledge_block(ctx.world.catalog, query)
        if found:
            parts.append(found)
        return "".join(p + "\n\n" for p in parts)

    async def summarize(self, cid: str, kind: str = "rolling", *, session_id: str | None = None, force=False):
        """Новая версия сводки. ``rolling`` — только если набралось ``summary_every`` публичных сообщений,
        ``session`` — в конце сессии, если есть что добавить. Сбой модели сводку просто пропускает."""
        if cid in self._summarizing:
            return None
        self._summarizing.add(cid)
        try:
            async with self.maker() as s:
                c = await s.get(Campaign, cid)
                seat = master_seat(c) if c else None
                if c is None or seat is None or seat.occupant_type != "agent":
                    return None
                prev = await memory.latest(s, cid)
                after = prev.upto_seq if prev else 0
                every = int((c.settings or {}).get("summary_every") or memory.SUMMARY_EVERY)
                rows = await memory.public_messages(s, cid, after)
                if not rows or (kind == "rolling" and not force and len(rows) < every):
                    return None
                cfg = await s.get(AgentConfig, seat.agent_config_id)
                ctx = await open_context(s, c, self.dice_factory(), turn_id=None, seat_id=seat.id)
                char_by_seat = {ch.seat_id: ch for ch in ctx.world.characters.values() if ch.seat_id}
                names = await _names(s, c)
                prompt = memory.summary_input(prev, rows, lambda m: _who(m, char_by_seat, names))
                upto = rows[-1].seq
                prev_version = prev.version if prev else 0
                model = parser_model_for()
                master_seat_id = seat.id
                api_base = (cfg.settings or {}).get("api_base")
                await s.rollback()
            call = LlmCall(campaign_id=cid, seat_id=master_seat_id, turn_id=None, purpose="summary", model=model)
            content = None
            try:
                reply = await self.llm.complete(
                    [{"role": "system", "content": memory.SUMMARY_SYSTEM}, {"role": "user", "content": prompt}],
                    model=model,
                    tools=[memory.tool_spec()],
                    max_tokens=2000,
                    temperature=0.2,
                    api_base=api_base,
                )
                call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
                call.cost, call.latency_ms = reply.cost, reply.latency_ms
                raw = next((t.arguments for t in reply.tool_calls if t.name == "submit_summary"), None)
                content = memory.check(raw) if raw is not None else None
                if content is None:
                    call.error = "сводка не прошла схему"
            except LLMError as e:
                call.error = str(e)[:2000]
            async with self.maker() as s:
                s.add(call)
                row = None
                if content is not None:
                    row = Summary(
                        campaign_id=cid,
                        session_id=session_id,
                        kind=kind,
                        version=prev_version + 1,
                        upto_seq=upto,
                        content=content,
                    )
                    s.add(row)
                await s.commit()
                row_id = row.id if row else None
            if row_id and kind == "session":
                # итог сессии всем за столом: сводка строится только из публичных сообщений
                await self.bus.publish(cid, envelope("session.summary", cid, memory.public_summary(content)), None)
            return row_id
        except Exception:  # noqa: BLE001 — сводка не должна ронять ход
            log.exception("сводка кампании %s не удалась", cid)
            return None
        finally:
            self._summarizing.discard(cid)

    # --- сводка пропущенного (раздел 11) ---

    async def catch_up(self, cid: str, seat_id: str, from_seq: int) -> str | None:
        """Игрок вернулся после офлайна: короткая сводка того, что он пропустил, только ему. Пишет дешёвая модель
        ИИ-мастера; у живого мастера модели нет — тогда без модели: сколько пропущено и последняя сцена."""

        async with self.maker() as s:
            c = await s.get(Campaign, cid)
            if c is None:
                return None
            q = select(Message).where(Message.campaign_id == cid, Message.seq > from_seq).order_by(Message.seq)
            rows = [m for m in (await s.scalars(q.limit(200))).all() if visible(m, seat_id) and m.kind != "ooc"]
            if not rows:
                return None
            seat = master_seat(c)
            cfg = await s.get(AgentConfig, seat.agent_config_id) if seat.agent_config_id else None
            chars = (await s.scalars(select(Character).where(Character.campaign_id == cid))).all()
            char_by_seat = {ch.seat_id: ch for ch in chars if ch.seat_id}
            names = await _names(s, c)
            lines = [_who(m, char_by_seat, names) + ": " + MARKUP.sub(r"\2", m.content) for m in rows]
            last = next((m.content for m in reversed(rows) if m.kind == "narration"), None)
            master_seat_id, missed = seat.id, len(rows)
            api_base = (cfg.settings or {}).get("api_base") if cfg is not None else None
            model = parser_model_for() if cfg is not None else None
            await s.rollback()
        text = None
        if model is not None:
            call = LlmCall(campaign_id=cid, seat_id=master_seat_id, turn_id=None, purpose="catchup", model=model)
            try:
                reply = await self.llm.complete(
                    [{"role": "system", "content": CATCH_UP_SYSTEM}, {"role": "user", "content": "\n".join(lines)}],
                    model=model,
                    max_tokens=1500,
                    temperature=0.2,
                    api_base=api_base,
                )
                call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
                call.cost, call.latency_ms = reply.cost, reply.latency_ms
                text = MARKUP.sub(r"\2", reply.text or "").strip()[:1200] or None
                if text is None:
                    call.error = "пустая сводка"
            except LLMError as e:
                call.error = str(e)[:2000]
            async with self.maker() as s:
                s.add(call)
                await s.commit()
        if text is None:
            text = f"Пропущено сообщений: {missed}."
            if last is not None:
                scene = MARKUP.sub(r"\2", last).strip()
                text += " Последнее от мастера: «" + (scene[:400] + "…" if len(scene) > 400 else scene) + "»"
        async with self.maker() as s:
            msg = Message(
                campaign_id=cid,
                session_id=(g.id if (g := await active_session(s, cid)) else None),
                seq=await next_seq(s, cid),
                kind="system",
                visible_to=[seat_id],
                content="Пока вас не было. " + text,
                data={"catch_up": True},
            )
            s.add(msg)
            await s.commit()
        await publish_message(self.bus, msg)
        return msg.id
