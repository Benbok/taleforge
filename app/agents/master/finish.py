"""Фаза повествования хода и восстановление прерванных ходов (спецификация генерации сцен, §6.4;
docs/world-objects-delivery2.md).

Действия хода уже зафиксированы (``MasterTurn.generation_checkpoint``). Здесь только ожидание подготовок мира,
описание и его сохранение в зарезервированную строку. Инструменты, бой, расходы и шёпоты не повторяются: мир и
события хода перечитываются из БД. Попытка описания записывается до вызова модели, после двух неудач ход
получает ``failed``, а игроки — сообщение, что действие сохранено. Восстановитель дописывает ходы после
рестарта, затем проверяет каждые 15 секунд и по локальному сигналу; БД — очередь, сигнал только ускоряет.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Protocol

from sqlalchemy import func, select

from app.agents.master import checkpoint
from app.core import preparation
from app.core.campaigns import master_seat
from app.core.chat import next_seq, system_message
from app.core.linker import link_text
from app.db.models import AgentConfig, Campaign, Event, LlmCall, MasterTurn, Message, Scene, now
from app.gateway.events import Stream, envelope, publish_message
from app.tools.runtime import open_context

log = logging.getLogger(__name__)

RECOVERY_EVERY = 15.0  # секунд между проверками восстановителя
SAVED_NOT_TOLD = (
    "Действие выполнено и сохранено, но мастер не смог его описать. Результат уже в листах героев и на карте; "
    "описание можно повторить из управления кампанией."
)
UNAVAILABLE = (
    "Подготовка мира для части действий не завершена. Опиши только подтверждённое результатами; "
    "о находках, которых ещё нет, не говори и скажи, что исследование пока недоступно."
)


class Preparer(Protocol):
    """Исполнитель подготовок мира (поставка 3). ``settle`` доводит фазы до ready/blocked или возвращается раньше."""

    async def settle(self, maker, campaign_id: str, refs: list[str]) -> None: ...

    async def run_due(self, maker) -> None: ...


class FinishMixin:
    """Часть MasterService (app/agents/master/service.py)."""

    preparer: Preparer | None = None

    def signal_recovery(self) -> None:
        signal = getattr(self, "_recovery_signal", None)
        if signal is not None:
            signal.set()

    async def _narrate_turn(self, cid: str, turn_id: str, *, resume: bool = False) -> list[Message]:
        """Довести ход с зафиксированными действиями до ``done`` или ``failed``. Возвращает сообщения для
        публикации: повествование и заметки о разделении отряда, либо сообщение о сохранённом действии."""
        calls: list[LlmCall] = []
        try:
            while True:
                async with self.maker() as s:
                    turn = await s.get(MasterTurn, turn_id)
                    if turn is None or turn.status != "running" or not checkpoint.resumable(turn.generation_checkpoint):
                        return []
                    cp = dict(turn.generation_checkpoint)
                    if cp["stage"] in ("effects_committed", "preparing"):
                        refs = list(cp.get("operation_refs") or [])
                        if refs and cp["stage"] == "effects_committed":
                            cp["stage"] = "preparing"
                            turn.generation_checkpoint = dict(cp)  # новый объект: JSON сохраняется только при замене
                            await s.commit()
                        cp["unavailable"] = await self._settle_preparation(cid, refs) if refs else []
                        cp["stage"] = "narration_pending"
                    if resume and await self._over_limit(s, cid):
                        turn.generation_checkpoint = dict(cp)  # новый объект: JSON сохраняется только при замене
                        await s.commit()
                        return await self._narration_failed(cid, turn_id, "spend_limit")
                    if int(cp.get("attempts", 0)) >= checkpoint.MAX_NARRATION_ATTEMPTS:
                        turn.generation_checkpoint = dict(cp)  # новый объект: JSON сохраняется только при замене
                        await s.commit()
                        return await self._narration_failed(cid, turn_id, "attempts")
                    cp["attempts"] = int(cp.get("attempts", 0)) + 1  # слот попытки — до сетевого вызова
                    turn.generation_checkpoint = dict(cp)  # новый объект: JSON сохраняется только при замене
                    await s.commit()
                try:
                    told = await self._compose_narration(cid, turn_id, cp, calls)
                except Exception as e:  # noqa: BLE001 — сбой описания не отменяет сохранённых действий
                    log.warning("описание хода %s не удалось (попытка %s)", turn_id, cp["attempts"], exc_info=True)
                    async with self.maker() as s:
                        turn = await s.get(MasterTurn, turn_id)
                        turn.trace = {**(turn.trace or {}), "narration_error": f"{type(e).__name__}: {e}"}
                        await s.commit()
                    continue
                return await self._finish_narration(cid, turn_id, *told)
        finally:
            if calls:
                async with self.maker() as s:
                    s.add_all(calls)
                    await s.commit()

    async def _over_limit(self, s, cid: str) -> bool:
        c = await s.get(Campaign, cid)
        limit = (c.settings or {}).get("spend_limit_usd") if c else None
        if limit is None:
            return False
        spent = (await s.scalar(select(func.sum(LlmCall.cost)).where(LlmCall.campaign_id == cid))) or 0.0
        return spent >= float(limit)

    async def _settle_preparation(self, cid: str, refs: list[str]) -> list[str]:
        """Ждать терминального статуса подготовок; вернуть те, что не готовы (blocked или так и не начаты)."""
        if self.preparer is not None:
            try:
                await self.preparer.settle(self.maker, cid, refs)
            except Exception:  # noqa: BLE001
                log.warning("подготовка мира %s не завершилась", refs, exc_info=True)
        async with self.maker() as s:
            statuses = {ref: await preparation.brief_status(s, cid, ref) for ref in refs}
        return [ref for ref, st in statuses.items() if st.get("status") != "ready"]

    async def _compose_narration(self, cid: str, turn_id: str, cp: dict, calls: list) -> tuple[str, dict, Any, Any]:
        """Описание по свежему миру и событиям хода из БД; инструменты не вызываются."""
        inputs = cp.get("inputs") or {}
        async with self.maker() as s:
            c = await s.get(Campaign, cid)
            turn = await s.get(MasterTurn, turn_id)
            seat = master_seat(c)
            cfg = await s.get(AgentConfig, seat.agent_config_id)
            ctx = await open_context(s, c, self.dice_factory(), turn_id=turn_id, seat_id=seat.id, focus=cp.get("place"))
            ids = list(cp.get("event_ids") or [])
            found = {ev.id: ev for ev in await s.scalars(select(Event).where(Event.id.in_(ids)))} if ids else {}
            ctx.events = [found[i] for i in ids if i in found]
            system = await self._system_prompt(s, c, cfg, ctx) + (inputs.get("mood") or "")
            head = await s.get(Message, cp["narration_message_id"])
            tool_attempts = (turn.trace or {}).get("calls") or []
        meet = inputs.get("meet") or ""
        if cp.get("unavailable"):
            meet = f"{meet}\n\n{UNAVAILABLE}" if meet else UNAVAILABLE
        stream = Stream(self.bus, cid, head, to=self._audience_for(c, cp.get("audience")))
        voice_task = None
        if self._tts_ready(c):
            voice_task = asyncio.create_task(
                self._voice(
                    calls,
                    cfg,
                    c,
                    seat.id,
                    turn_id,
                    system,
                    ctx,
                    inputs.get("combat_notes") or [],
                    news=inputs.get("news") or "",
                )
            )
        try:
            narration, audit = await self._narrate(
                calls,
                cfg,
                c,
                seat.id,
                turn_id,
                system,
                inputs.get("convo") or "",
                inputs.get("news") or "",
                ctx,
                inputs.get("combat_notes") or [],
                inputs.get("plot_notes") or [],
                stream=stream,
                stalled=bool(inputs.get("stalled")),
                meet=meet,
                tool_attempts=tool_attempts,
            )
        except BaseException:
            if voice_task is not None:
                voice_task.cancel()
            raise
        voice_line, voice_data = await voice_task if voice_task is not None else (None, None)
        return narration, audit, voice_line, voice_data

    @staticmethod
    def _audience_for(c: Campaign, audience: list[str] | None) -> list[str] | None:
        """Аудитория перепроверяется перед публикацией: места, которых в кампании больше нет, текст не получают."""
        if audience is None:
            return None
        seats = {x.id for x in c.seats}
        return [x for x in audience if x in seats]

    async def _finish_narration(self, cid: str, turn_id: str, narration: str, audit, voice_line, voice_data):
        async with self.maker() as s:
            turn = await s.get(MasterTurn, turn_id)
            if turn is None or turn.status != "running":
                return []  # ход уже дописан или закрыт: второго повествования нет
            cp = dict(turn.generation_checkpoint or {})
            c = await s.get(Campaign, cid)
            msg = await s.get(Message, cp["narration_message_id"])
            msg.content = await link_text(s, cid, narration)
            msg.visible_to = self._audience_for(c, cp.get("audience"))
            place = cp.get("place")
            data = {"place": place} if msg.visible_to is not None and place is not None else {}
            if voice_data:
                data["voice"] = {**voice_data, "text": voice_line}
            msg.data = data or None
            party = [await system_message(s, c, text, None) for text in (cp.get("inputs") or {}).get("party_notes", [])]
            turn.status, turn.finished_at, turn.narration_message_id = "done", now(), msg.id
            turn.trace = {**(turn.trace or {}), "audit": audit, "voice_line": voice_line}
            turn.generation_checkpoint = {**cp, "stage": "done"}
            await s.commit()
        return [msg, *party]

    async def _narration_failed(self, cid: str, turn_id: str, reason: str) -> list[Message]:
        """Описание не удалось: действия остаются, строка повествования убирается, игроки узнают, что действие
        сохранено. Автовосстановитель такой ход больше не трогает."""
        async with self.maker() as s:
            turn = await s.get(MasterTurn, turn_id)
            if turn is None or turn.status != "running":
                return []
            cp = dict(turn.generation_checkpoint or {})
            c = await s.get(Campaign, cid)
            draft = await s.get(Message, cp.get("narration_message_id"))
            if draft is not None:
                await s.delete(draft)
            msg = await system_message(s, c, SAVED_NOT_TOLD, None)
            party = [await system_message(s, c, text, None) for text in (cp.get("inputs") or {}).get("party_notes", [])]
            turn.status, turn.finished_at = "failed", now()
            turn.trace = {**(turn.trace or {}), "narration_failed": reason}
            turn.generation_checkpoint = {**cp, "stage": "narration_pending"}
            await s.commit()
            audience = self._audience_for(c, cp.get("audience"))
        if cp.get("narration_message_id"):
            await self.bus.publish(
                cid, envelope("message.withdrawn", cid, {"id": cp["narration_message_id"]}), audience
            )
        return [msg, *party]

    # --- явный повтор описания и восстановитель ---

    async def reopen_narration(self, cid: str, turn_id: str) -> bool:
        """Повтор описания ходу, у которого оно не удалось: тот же id сообщения, новые две попытки."""
        async with self.maker() as s:
            turn = await s.get(MasterTurn, turn_id)
            cp = dict((turn.generation_checkpoint if turn else None) or {})
            if (
                turn is None
                or turn.campaign_id != cid
                or turn.status != "failed"
                or cp.get("stage") != "narration_pending"
            ):
                return False
            if await s.get(Message, cp["narration_message_id"]) is None:
                c = await s.get(Campaign, cid)
                s.add(
                    Message(
                        id=cp["narration_message_id"],
                        campaign_id=cid,
                        session_id=turn.session_id,
                        seq=await next_seq(s, cid),
                        seat_id=master_seat(c).id,
                        kind="narration",
                        visible_to=[],
                        content="",
                        data={"pending": True},
                    )
                )
            turn.status, turn.finished_at = "running", None
            turn.generation_checkpoint = {**cp, "attempts": 0}
            await s.commit()
        self._spawn(self._resume(cid, turn_id))
        return True

    async def _resume(self, cid: str, turn_id: str) -> None:
        async with self.turn_lock(cid):
            told = await self._narrate_turn(cid, turn_id, resume=True)
            async with self.maker() as s:
                names = {}
                ids = [m.id for m in await s.scalars(select(Message).where(Message.turn_id == turn_id))]
        for m in told:
            await publish_message(self.bus, m, names)
        if told:
            # Generated SFX belong after the recovered text, just as in the normal publish_changes path.
            from app.sfx.playback import arm

            async with self.maker() as s:
                c = await s.get(Campaign, cid)
                turn = await s.get(MasterTurn, turn_id)
                ctx = await open_context(
                    s,
                    c,
                    self.dice_factory(),
                    turn_id=turn_id,
                    seat_id=master_seat(c).id,
                    focus=(turn.generation_checkpoint or {}).get("place"),
                )
            await arm(ctx)
            await self._states(cid, ids, "answered")

    async def recover(self, *, startup: bool = False) -> None:
        """Ходы с зафиксированными действиями дописываются. При старте сервера ход без checkpoint — от умершего
        процесса, его транзакция не закоммичена: он закрывается как откатившийся."""
        async with self.maker() as s:
            running = (await s.scalars(select(MasterTurn).where(MasterTurn.status == "running"))).all()
            todo = []
            dropped: list[tuple[str, Message, list[str]]] = []
            for turn in running:
                if checkpoint.resumable(turn.generation_checkpoint):
                    todo.append((turn.campaign_id, turn.id))
                    continue
                if not startup:
                    continue  # ход идёт в этом процессе прямо сейчас
                turn.status, turn.finished_at = "failed", now()
                turn.trace = {**(turn.trace or {}), "rolled_back": True, "error": "server restarted"}
                c = await s.get(Campaign, turn.campaign_id)
                msg = await system_message(
                    s, c, "Мастер не смог завершить ход. Ничего не изменилось: повторите действие.", None
                )
                sc = await s.get(Scene, turn.campaign_id)
                if sc is not None and (sc.state or {}).get("submitted"):
                    sc.state = {**sc.state, "submitted": False}
                ids = [m.id for m in await s.scalars(select(Message).where(Message.turn_id == turn.id))]
                dropped.append((turn.campaign_id, msg, ids))
            await s.commit()
        for cid, msg, ids in dropped:
            await publish_message(self.bus, msg)
            await self._states(cid, ids, "failed")
        for cid, turn_id in todo:
            if self.turn_lock(cid).locked():
                continue  # свой ход кампания допишет сама
            try:
                await self._resume(cid, turn_id)
            except Exception:  # noqa: BLE001
                log.exception("восстановление хода %s не удалось", turn_id)
        run_due = getattr(self.preparer, "run_due", None)
        if run_due is not None:  # активированные подготовки без хода: исследование с панели, прерванный lease
            try:
                await run_due(self.maker)
            except Exception:  # noqa: BLE001
                log.exception("подготовка мира не удалась")

    def start_recovery(self) -> None:
        self._recovery_signal = asyncio.Event()

        async def loop() -> None:
            try:
                await self.recover(startup=True)
            except Exception:  # noqa: BLE001
                log.exception("восстановление ходов при старте не удалось")
            while True:
                try:
                    await asyncio.wait_for(self._recovery_signal.wait(), RECOVERY_EVERY)
                except TimeoutError:
                    pass
                self._recovery_signal.clear()
                try:
                    await self.recover()
                except Exception:  # noqa: BLE001
                    log.exception("восстановление ходов не удалось")

        self._recovery = asyncio.create_task(loop())
