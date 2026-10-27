"""Durable Universal turns and shared provider/status infrastructure."""

from __future__ import annotations

from app.agents.llm import LLMError, LLMReply, decide_model_for, model_for, reply_audit_error
from app.agents.master.common import render
from app.core.llm_diagnostics import message_sizes, reply_metrics, retry_metrics
from app.db.models import AgentConfig, Campaign, LlmCall
from app.gateway.events import envelope
from app.tools.registry import ToolContext


class TurnMixin:
    async def _status(self, cid: str, stage: str) -> None:
        if stage == "idle":
            self._stages.pop(cid, None)
        else:
            self._stages[cid] = (stage, self._audience.get(cid))
        await self.bus.publish(cid, envelope("master.status", cid, {"stage": stage}), self._audience.get(cid))

    async def _states(self, cid: str, ids: list[str], state: str) -> None:
        if ids:
            await self.bus.publish(cid, envelope("message.state", cid, {"ids": ids, "state": state}), None)

    async def run_turn(self, cid: str, place: str | None = None) -> str | None:
        """Ход мастера. ``place`` — группа разделившегося отряда; по умолчанию группа самой ранней реплики."""
        lock = self.turn_lock(cid)
        async with lock:
            if self.players is not None:
                await self.players.take_turns(cid, place)
            try:
                return await self._run_turn(cid, place)
            finally:
                self._audience.pop(cid, None)

    async def _run_turn(self, cid, place=None):
        async with self.maker() as session:
            campaign = await session.get(Campaign, cid)
            if campaign is None:
                return None
            if campaign.ruleset_id != "universal":
                raise ValueError("Unsupported retired game rules")
        from app.agents.master.universal import run_universal_turn

        return await run_universal_turn(self, cid, place)

    async def _save_calls(self, calls: list) -> None:
        if not calls:
            return
        rows = list(calls)
        calls.clear()
        async with self.maker() as s:
            s.add_all(rows)
            await s.commit()

    async def _ask(
        self,
        calls: list,
        cfg: AgentConfig,
        cid: str,
        seat_id: str,
        turn_id: str | None,
        purpose: str,
        messages: list,
        tools: list | None,
        override_model: str | None = None,
        stream_callback=None,
        *,
        prompt_metadata: dict | None = None,
        retry_count: int = 0,
        retry_reasons: tuple[str, ...] = (),
        tool_choice=None,
        max_tokens: int = 8192,
        thinking: bool = True,
    ) -> LLMReply:
        model = override_model or (decide_model_for() if purpose == "decide" else model_for())
        sizes = message_sizes(messages, tools or [])
        sizes.update(prompt_metadata or {})
        sizes.update(retry_metrics(retry_count, retry_reasons))
        try:
            reply = await self.llm.complete(
                messages,
                model=model,
                tools=tools,
                stream_callback=stream_callback,
                max_tokens=max_tokens,
                tool_choice=tool_choice,
                thinking=thinking,
                temperature=0.2 if purpose == "decide" else cfg.temperature,
                api_base=(cfg.settings or {}).get("api_base"),
            )
        except LLMError as e:
            calls.append(
                LlmCall(
                    campaign_id=cid,
                    seat_id=seat_id,
                    turn_id=turn_id,
                    purpose=purpose,
                    model=model,
                    error=str(e)[:2000],
                    cost_known=False,
                    diagnostics=sizes,
                )
            )
            raise
        calls.append(
            LlmCall(
                campaign_id=cid,
                seat_id=seat_id,
                turn_id=turn_id,
                purpose=purpose,
                model=reply.model,
                tokens_in=reply.tokens_in,
                tokens_out=reply.tokens_out,
                **reply_metrics(reply),
                diagnostics=sizes,
                cost=reply.cost,
                latency_ms=reply.latency_ms,
                error=reply_audit_error(reply, require_text=purpose == "narrate"),
            )
        )
        return reply

    async def _system_prompt(self, s, c: Campaign, cfg: AgentConfig, ctx: ToolContext, profile: str = "general") -> str:
        """``profile`` — профиль инструментов решающей фазы хода: остальные роли получают полный текст правил."""
        from app.agents.master.prompt_context import master_prompt_values

        return render("master_system.j2", **await master_prompt_values(ctx, cfg), profile=profile)
