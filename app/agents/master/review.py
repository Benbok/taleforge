"""Проверка персонажа ИИ-мастером (раздел 5.1)."""

from __future__ import annotations

import asyncio
import json
import logging
import uuid

from app.agents.llm import LLMError, reply_audit_error
from app.agents.master.common import _world_choices
from app.agents.master.optimization import optimization_flags
from app.agents.providers import explain
from app.core.campaigns import Conflict, master_seat
from app.db.models import AgentConfig, Campaign, Character, Event, LlmCall, now
from app.gateway.events import envelope
from app.tools.registry import execute, tool_specs
from app.tools.runtime import open_context

log = logging.getLogger(__name__)


class ReviewMixin:
    """Часть MasterService (app/agents/master/service.py)."""

    # --- проверка персонажа ИИ-мастером (раздел 5.1) ---

    async def _claim_character_review(self, cid: str, character_id: str) -> tuple[str, bool]:
        from app.core.characters import ensure_character_admission_allowed

        lock = self.turn_lock(cid)
        if lock.locked():
            raise Conflict("Проверка доступна до старта сессии или на паузе после завершения хода мастера")
        async with lock:
            key = (cid, character_id)
            async with self.maker() as s:
                c = await s.get(Campaign, cid)
                ch = await s.get(Character, character_id)
                if c is None or ch is None or ch.campaign_id != cid or ch.status != "submitted":
                    raise Conflict("Персонаж не на проверке")
                if master_seat(c).occupant_type != "agent":
                    raise Conflict("Героя проверяет живой мастер")
                await ensure_character_admission_allowed(s, c)
                if key in self._reviews:
                    return self._reviews[key], False
                attempt = uuid.uuid4().hex
                started = now()
                self._reviews[key] = attempt
                try:
                    s.add(
                        Event(
                            campaign_id=cid,
                            target_id=character_id,
                            tool="review_started",
                            created_at=started,
                            payload={
                                "attempt_id": attempt,
                                "process_id": self.review_process_id,
                                "submitted_at": ch.updated_at.isoformat() if ch.updated_at else None,
                            },
                        )
                    )
                    await s.commit()
                except BaseException:
                    self._reviews.pop(key, None)
                    raise
        try:
            await self.bus.publish(
                cid,
                envelope(
                    "character.review_started",
                    cid,
                    {"character_id": character_id, "attempt_id": attempt, "started_at": started.isoformat()},
                ),
                None,
            )
        except BaseException:
            self._reviews.pop(key, None)
            raise
        return attempt, True

    async def start_character_review(self, cid: str, character_id: str) -> str:
        attempt, created = await self._claim_character_review(cid, character_id)
        if created:
            self._spawn(self._run_character_review(cid, character_id, attempt))
        return attempt

    async def review_character(self, cid: str, character_id: str) -> str | None:
        try:
            attempt, created = await self._claim_character_review(cid, character_id)
        except Conflict:
            # Preserve the legacy internal return value on a session-resume race.
            async with self.maker() as s:
                ch = await s.get(Character, character_id)
                c = await s.get(Campaign, cid)
                if ch is not None and ch.status == "submitted" and c is not None:
                    if not optimization_flags(c.settings or {})["compact_review"]:
                        return ch.status
            return None
        if created:
            return await self._run_character_review(cid, character_id, attempt)
        return "submitted"

    async def _run_character_review(self, cid: str, character_id: str, attempt: str) -> str | None:
        calls: list[LlmCall] = []
        error = None
        status = None
        cancelled = False
        try:
            attempted, status = await self._review(cid, character_id, calls, attempt_id=attempt)
            if attempted and not status:
                reason = (calls[-1].diagnostics or {}).get("review_outcome") if calls else None
                error = {
                    "no_tool_call": "Модель не вызвала review_character за две попытки.",
                    "unknown_tool": "Модель выбрала недоступный инструмент проверки.",
                    "invalid_arguments": "Модель передала неверные аргументы проверки героя.",
                    "rule_denial": "Правила кампании отклонили решение проверки.",
                }.get(reason, "модель не вынесла решения за три попытки")
        except asyncio.CancelledError:
            error, cancelled = "Проверка прервана.", True
        except LLMError as e:
            error = explain(str(e))
        except Conflict as e:
            error = str(e)
        except Exception as e:  # noqa: BLE001 — сбой проверки не должен теряться молча
            log.exception("проверка героя %s сорвалась", character_id)
            error = f"Проверка прервана: {type(e).__name__}"
        finally:
            try:
                async with self.maker() as s:
                    s.add_all(calls)
                    s.add(
                        Event(
                            campaign_id=cid,
                            target_id=character_id,
                            tool="review_failed" if error else "review_finished",
                            payload={
                                "attempt_id": attempt,
                                "process_id": self.review_process_id,
                                "error": error,
                                "status": status,
                            },
                        )
                    )
                    await s.commit()
            finally:
                if self._reviews.get((cid, character_id)) == attempt:
                    self._reviews.pop((cid, character_id), None)
        if error:
            await self.bus.publish(
                cid,
                envelope(
                    "character.review_failed",
                    cid,
                    {"character_id": character_id, "error": error, "attempt_id": attempt},
                ),
                None,
            )
        if cancelled:
            raise asyncio.CancelledError
        return status

    async def _review(
        self, cid: str, character_id: str, calls: list, *, attempt_id: str | None = None
    ) -> tuple[bool, str | None]:
        """ИИ-проверка героя. Сессия БД не держится во время обращения к модели: в SQLite открытая транзакция
        не даёт другим писать, и игроки получали «database is locked», пока модель думала."""
        from app.core.campaigns import Conflict
        from app.core.characters import ensure_character_admission_allowed, full_view

        lock = self.turn_lock(cid)
        async with lock:
            async with self.maker() as s:
                c = await s.get(Campaign, cid)
                compact = optimization_flags(c.settings or {})["compact_review"]
                seat = master_seat(c)
                if seat.occupant_type != "agent":
                    return False, None
                seat_id = seat.id
                cfg = await s.get(AgentConfig, seat.agent_config_id)
                ctx = await open_context(s, c, self.dice_factory(), turn_id=None, seat_id=seat_id)
                ch = ctx.world.characters.get(character_id)
                if ch is None or ch.status != "submitted":
                    return False, None
                try:
                    await ensure_character_admission_allowed(s, c)
                except Conflict:
                    if compact:
                        raise
                    return False, ch.status
                sheet = full_view(ch, ctx.world.catalog, ctx.world.inventory.get(ch.id, []), [])
                world = _world_choices(ctx.world.catalog)
                system = await self._system_prompt(s, c, cfg, ctx)
                tools = tool_specs(ctx.world, ["review_character"])
                s.expunge(cfg)  # нужен и после закрытия сессии: провайдер, модель, настройки
        msgs = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    "Игрок прислал персонажа на проверку. Правила сервер уже проверил. Оцени историю и "
                    "соответствие сеттингу и вызови review_character: одобри или верни с комментарием. "
                    "Соответствие миру проверяй по его фактам: класс и происхождение взяты из списков мира, но "
                    "история, внешность и характер не должны вводить то, чего в мире нет (чужие расы, народы, "
                    "боги, магия или земли, противоречащие лору). Возвращай только за явное противоречие и "
                    "в комментарии назови его и предложи, как поправить в духе мира; стиль и мелочи не повод.\n"
                    + world
                    + "\n"
                    "Можешь тайно связать историю героя с сюжетом через secret_link, а если есть каркас — "
                    "привязать эту связь к узлу, NPC, злодею или месту каркаса через hook_ref.\n\n"
                    + json.dumps(sheet, ensure_ascii=False, default=str)
                ),
            },
        ]
        ask_options = {}
        if compact:
            from app.agents.master.prompt_context import build_prompt_bundle

            async with self.maker() as s:
                c = await s.get(Campaign, cid)
                ctx = await open_context(s, c, self.dice_factory(), turn_id=None, seat_id=seat_id)
                bundle = await build_prompt_bundle(
                    ctx, cfg, role="review", inputs={"request": msgs[1]["content"], "legacy_messages": msgs}
                )
            msgs = bundle.messages
            ask_options = {"tool_choice": "required", "prompt_metadata": bundle.metadata("review")}
        for response_index in range(2 if compact else 3):
            reply = await self._ask(calls, cfg, cid, seat_id, None, "review", msgs, tools, **ask_options)

            def audit(outcome: str, results: list | None = None, *, reply=reply, response_index=response_index) -> None:
                if not compact or not calls:
                    return
                calls[-1].diagnostics = {
                    **(calls[-1].diagnostics or {}),
                    "review_outcome": outcome,
                    "review_attempt_id": attempt_id,
                    "response_index": response_index,
                    "tool_results": results or [],
                }
                if outcome != "applied":
                    calls[-1].error = reply_audit_error(reply, reason=outcome)

            msgs.append(reply.message or {"role": "assistant", "content": reply.text})
            if not reply.tool_calls:
                audit("no_tool_call")
                msgs.append({"role": "user", "content": "Вызови review_character."})
                continue
            async with lock:
                async with self.maker() as s:
                    c = await s.get(Campaign, cid)
                    ctx = await open_context(s, c, self.dice_factory(), turn_id=None, seat_id=seat_id)
                    ch = ctx.world.characters.get(character_id)
                    if ch is None or ch.status != "submitted":
                        return False, None  # пока модель думала, героя проверил человек или игрок его отозвал
                    try:
                        await ensure_character_admission_allowed(s, c)
                    except Conflict:
                        if compact:
                            raise
                        return False, ch.status  # сессия возобновилась или начался бой: оставляем submitted
                    status = None
                    results = []
                    for call in reply.tool_calls:
                        args = {**call.arguments, "character_id": ch.id}
                        r = (
                            await execute(ctx, "review_character", args)
                            if call.name == "review_character"
                            else {"ok": False, "error": "здесь доступен только review_character"}
                        )
                        msgs.append(
                            {
                                "role": "tool",
                                "tool_call_id": call.id,
                                "content": json.dumps(r, ensure_ascii=False, default=str),
                            }
                        )
                        failure = r.get("failure") or {}
                        outcome = (
                            "applied"
                            if r.get("ok")
                            else "unknown_tool"
                            if call.name != "review_character"
                            else "invalid_arguments"
                            if failure.get("category") == "invalid_arguments"
                            else "rule_denial"
                        )
                        results.append(
                            {
                                "tool": call.name[:64],
                                "ok": bool(r.get("ok")),
                                "code": failure.get("code"),
                                "category": failure.get("category"),
                            }
                        )
                        audit(outcome, results)
                        if r.get("ok"):
                            status = r["result"]["status"]
                            if compact:
                                break
                    await s.commit()
                    if not status:
                        continue
                    if ch.seat_id:
                        full = full_view(ch, ctx.world.catalog, ctx.world.inventory.get(ch.id, []), ctx.world.effects)
                        await self.bus.publish(
                            cid,
                            envelope(
                                "character.reviewed",
                                cid,
                                {
                                    "character": full,
                                    "status": status,
                                    "comment": ch.review_comment,
                                    **({"attempt_id": attempt_id} if attempt_id else {}),
                                },
                            ),
                            [ch.seat_id],
                        )
                    return True, status
        return True, None
