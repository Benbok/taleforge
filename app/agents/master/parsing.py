"""Парсер намерений игроков (раздел 6)."""

from __future__ import annotations

import asyncio

from app.agents import intent as intents
from app.agents.llm import LLMError, LLMReply, parser_model_for
from app.agents.master.common import PARSE_TIMEOUT
from app.config import settings as app_settings
from app.core.campaigns import master_seat
from app.core.chat import active_session
from app.db.models import AgentConfig, Campaign, LlmCall
from app.tools.runtime import open_context


class ParsingMixin:
    """Часть MasterService (app/agents/master/service.py)."""

    # --- парсер намерений (раздел 6) ---

    async def parse_intent(self, cid: str, seat_id: str | None, text: str) -> intents.ParseResult:
        """Разбирает действие игрока до записи в чат. Только при ИИ-мастере: у живого мастера модели нет.
        Любой сбой парсера — реплика проходит без намерения."""
        async with self.maker() as s:
            c = await s.get(Campaign, cid)
            seat = master_seat(c) if c else None
            if c is None or seat is None or seat.occupant_type != "agent" or seat_id is None:
                return intents.ParseResult()
            if await active_session(s, cid) is None:
                return intents.ParseResult()  # вне сессии действие всё равно не примут
            cfg = await s.get(AgentConfig, seat.agent_config_id)
            ctx = await open_context(s, c, self.dice_factory(), turn_id=None, seat_id=seat.id)
            ch = next(
                (
                    x
                    for x in ctx.world.characters.values()
                    if x.seat_id == seat_id and x.status in ("approved", "active")
                ),
                None,
            )
            if ch is None:
                return intents.ParseResult()
            info, values = intents.context_for(ctx.world, ch)
            ch_id, provider, master_seat_id = ch.id, cfg.provider, seat.id
            api_base = (cfg.settings or {}).get("api_base")
            await s.rollback()
        model = parser_model_for()
        call = LlmCall(campaign_id=cid, seat_id=master_seat_id, turn_id=None, purpose="parse", model=model)
        try:
            reply = await asyncio.wait_for(
                self._parse_call(model, info, text, values, api_base, provider=provider), timeout=PARSE_TIMEOUT
            )
        except TimeoutError:
            call.error = f"парсер не ответил за {PARSE_TIMEOUT} с"
            reply = None
        except LLMError as e:
            call.error = str(e)[:2000]
            reply = None
        if reply is not None:
            call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
            call.cost, call.latency_ms = reply.cost, reply.latency_ms
        raw = next((t.arguments for t in (reply.tool_calls if reply else []) if t.name == "submit_intent"), None)
        async with self.maker() as s:
            s.add(call)
            await s.commit()
            if raw is None:
                return intents.ParseResult(notes=["парсер не ответил"])
            c = await s.get(Campaign, cid)
            ctx = await open_context(s, c, self.dice_factory(), turn_id=None, seat_id=seat_id)
            ch = ctx.world.characters.get(ch_id)
            if ch is None:
                return intents.ParseResult()
            return intents.check(raw, ctx.world, ch)

    async def _parse_call(
        self,
        model: str,
        info: str,
        text: str,
        values: dict,
        api_base: str | None = None,
        provider: str | None = None,
    ) -> LLMReply:
        # провайдер кампании теперь «env»: смотрим на активного провайдера сервера
        active = provider if provider not in (None, "env") else app_settings.llm_provider
        tool_choice = {"type": "function", "function": {"name": "submit_intent"}} if active == "gemini" else None
        return await self.llm.complete(
            [
                {"role": "system", "content": intents.PARSER_SYSTEM},
                {"role": "user", "content": f"{info}\n\nРеплика игрока:\n{text}"},
            ],
            model=model,
            tools=[intents.tool_spec(values)],
            tool_choice=tool_choice,
            max_tokens=500,
            temperature=0.0,
            api_base=api_base,
        )
