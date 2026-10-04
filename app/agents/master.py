"""ИИ-мастер: ход от реплик игроков до повествования (ТЗ, разделы 5, 7, 7.1, 9).

Ход мастера:
1. Сбор реплик. Мастер отвечает на пакет: когда написали все игроки с персонажами или истекло окно сбора.
2. Фаза решения. Модель видит таблицу сцены из БД и вызывает инструменты (не больше 8). Каждый вызов проверяет
   валидатор, результат с кубиками возвращается модели. Контракт намерения: на каждое действие игрока нужен
   вызов или явный отказ; если модель промолчала, её просят ещё раз, потом код сам фиксирует отказ.
3. Фаза повествования. Отдельный запрос без инструментов: только результаты хода и сцена.
4. Аудитор разметки. Сущности в тексте размечены [[id|текст]]; id не из реестра — повтор, затем разметка снимается.
5. Транзакция хода. События, шёпоты и повествование фиксируются вместе. Сбой — откат всего хода.

Не вошли в этап 3: парсер намерений и маршрутизатор механик (этап 4), сводки и поиск по правилам (этап 5).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jinja2
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents import character, memory, rhythm
from app.agents import intent as intents
from app.agents.llm import LLM, LLMError, LLMReply, model_for, parser_model_for
from app.agents.providers import explain
from app.core import audio, bonds, combat, persona, plot
from app.core.brief import brief_text
from app.core.campaigns import master_seat
from app.core.chat import TURN_KINDS, active_session, next_seq, system_message, visible
from app.core.linker import link_text
from app.db.models import (
    AgentConfig,
    Campaign,
    CampaignSecret,
    Character,
    Event,
    LlmCall,
    MasterTurn,
    Message,
    Scene,
    Summary,
    User,
    as_utc,
    now,
)
from app.gateway.events import envelope, publish_message
from app.rules.dice import Dice
from app.tools import fortune as fortune_tools
from app.tools import plot as plot_tools
from app.tools import progress as progress_tools
from app.tools import standing as standing_tools
from app.tools.audio import AUDIO_TOOLS
from app.tools.registry import REGISTRY, ToolContext, execute, tool_specs
from app.tools.runtime import flush_outbox, open_context, publish_changes

log = logging.getLogger(__name__)

MAX_CALLS = 8  # вызовов инструментов за ход (раздел 7)
PARSE_TIMEOUT = 30  # секунд: дольше — реплика уходит мастеру без разбора
MAX_STEPS = 12  # обращений к модели в фазе решения
HISTORY = 20  # последних сообщений в контексте (раздел 9)
PLAYER_KINDS = TURN_KINDS  # шёпот мастеру ход не берёт: на него отвечает answer_whispers
WHISPER_HISTORY = 12  # сообщений, видимых шепчущему, в контексте ответа на шёпот
CATCH_UP_SYSTEM = (
    "Игрок текстовой ролевой игры ненадолго выпал из сети. Тебе дают сообщения, которые он пропустил. "
    "Перескажи ему по-русски в 2–4 предложениях, что произошло и на чём остановились, обращаясь на «вы». "
    "Без чисел хитов и урона, ничего не выдумывай: только то, что есть в сообщениях."
)
ROLL_TOOLS = (
    "roll_check",
    "resolve_attack",
    "cast_spell",
    "death_save",
    "apply_hazard",
    "set_scene_mode",
    "rest",
    "use_item",
)
MARKUP = re.compile(r"\[\[([^|\]]+)\|([^\]]+)\]\]")
DECISION_TOOLS = [n for n in REGISTRY if n != "review_character"]


def decision_tools(ctx: ToolContext) -> list[str]:
    """Инструменты фазы решения. Инструменты сюжета — только когда у кампании есть каркас, звука — когда владелец
    включил его и библиотека не пуста."""
    off = set() if plot.has_plan(ctx.world.plot) else set(plot_tools.PLOT_TOOLS)
    if not audio.enabled(ctx.campaign):
        off |= set(AUDIO_TOOLS)
    return [n for n in DECISION_TOOLS if n not in off]


_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(Path(__file__).parent / "prompts"),
    autoescape=False,
    keep_trailing_newline=False,
)


def render(name: str, **kw: Any) -> str:
    return _env.get_template(name).render(**kw).strip()


def _routable_cast(ctx: ToolContext, intent: dict | None) -> dict | None:
    """Заклинание из книги героя с ясной целью сервер творит сам; площадные остаются мастеру (кто в области)."""
    from app.core.spells import spell_catalog
    from app.rules.dnd5e.spells import target_kind

    args = intents.routable_cast(intent)
    if args is None:
        return None
    spell = spell_catalog(ctx.world.catalog).spells.get(args["spell_id"])
    if spell is None or target_kind(spell) == "area":
        return None
    if target_kind(spell) == "enemy" and not args.get("target_ids"):
        return None
    return args


def _world_choices(cat) -> str:
    """Классы и происхождения мира кампании — рамка, по которой ИИ-мастер сверяет историю героя."""
    origins = ", ".join(e.name for e in cat.by_kind("origin")) or "—"
    classes = ", ".join(e.name for e in cat.by_kind("class")) or "—"
    return f"Происхождения мира: {origins}. Классы мира: {classes}."


class MasterService:
    """Очередь ходов ИИ-мастера по кампаниям. Один ход кампании за раз; реплики, пришедшие во время хода,
    уходят в следующий пакет."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        bus,
        llm: LLM,
        dice_factory=Dice,
        media_dir: Path | None = None,
        tts: Any = None,
    ):
        self.maker = sessionmaker
        self.bus = bus
        self.llm = llm
        self.dice_factory = dice_factory
        self.media_dir = media_dir
        self.tts = tts
        self._tasks: dict[str, asyncio.Task] = {}
        self._pending: set[str] = set()
        self._locks: dict[str, asyncio.Lock] = {}
        self._background: set[asyncio.Task] = set()
        self._timers: dict[str, asyncio.Task] = {}  # таймер хода героя в бою, по кампаниям
        # prompt_id → (кампания, место, ответ, кнопка): открытую кнопку снимок отдаёт и после переподключения
        self._reactions: dict[str, tuple[str, str, asyncio.Future, dict]] = {}
        self._summarizing: set[str] = set()
        self._intro_locks: dict[str, asyncio.Lock] = {}
        self.presence = None  # app/gateway/presence.py: кто из игроков ушёл во время сессии (раздел 11)
        self.players = None  # app/agents/player.py: ИИ-игроки (раздел 5.2)
        self._seen: dict[str, tuple[frozenset, str]] = {}  # павшие герои и режим сцены: для сильных событий
        self._whisper_locks: dict[str, asyncio.Lock] = {}

    # --- очередь ---

    def notify(self, campaign_id: str) -> None:
        """Пришла реплика игрока: запустить сбор пакета или отметить, что после текущего хода нужен ещё один.
        Шёпоты мастеру ход не ждут: на них мастер отвечает сразу и отдельно."""
        self._spawn(self.answer_whispers(campaign_id))
        task = self._tasks.get(campaign_id)
        if task is not None and not task.done():
            self._pending.add(campaign_id)
            return
        self._tasks[campaign_id] = asyncio.create_task(self._loop(campaign_id))

    def schedule_review(self, campaign_id: str, character_id: str) -> None:
        self._spawn(self.review_character(campaign_id, character_id))

    def schedule_summary(self, campaign_id: str, kind: str = "rolling", session_id: str | None = None) -> None:
        self._spawn(self.summarize(campaign_id, kind, session_id=session_id))

    def schedule_bonds(self, campaign_id: str, character_id: str) -> None:
        from app.agents import prelude

        self._spawn(prelude.ask_questions(self, campaign_id, character_id))

    def schedule_hook(self, campaign_id: str, character_id: str) -> None:
        from app.agents import prelude

        self._spawn(prelude.make_hook(self, campaign_id, character_id))

    def schedule_session_open(self, campaign_id: str, session_id: str | None) -> None:
        """Старт сессии: вступление для новых героев, затем цель на вечер (ИИ-мастер с каркасом)."""
        from app.agents import rhythm

        async def run() -> None:
            await self.introduce(campaign_id)
            if session_id:
                await self._safe(rhythm.session_goal(self, campaign_id, session_id), "цель на вечер")

        self._spawn(run())

    def schedule_session_close(self, campaign_id: str, session_id: str | None, ended: bool) -> None:
        """Конец сессии: сводка, затем зацепка на следующий раз или, при завершении кампании, эпилог."""
        from app.agents import rhythm

        async def run() -> None:
            # сначала сводка сессии: эпилог и зацепка опираются на неё, а запись по очереди не спорит за базу
            await self._safe(self.summarize(campaign_id, "session", session_id=session_id), "сводка сессии")
            await self._safe(
                character.chronicle(self, campaign_id, "сессия закончилась", session_id=session_id), "летопись"
            )
            if ended:
                await self._safe(rhythm.epilogue(self, campaign_id), "эпилог")
            else:
                await self._safe(rhythm.session_hook(self, campaign_id, session_id), "зацепка на следующую сессию")

        self._spawn(run())

    async def _safe(self, coro, what: str):
        try:
            return await coro
        except Exception:  # noqa: BLE001 — ритм сессии не должен ронять сервер
            log.exception("%s не удалось", what)
            return None

    async def introduce(self, campaign_id: str) -> str | None:
        """Вступление для ещё не представленных героев; одно на кампанию за раз."""
        from app.agents import prelude

        async with self._intro_locks.setdefault(campaign_id, asyncio.Lock()):
            try:
                return await prelude.introduce(self, campaign_id)
            except Exception:  # noqa: BLE001 — без вступления игра всё равно идёт
                log.exception("вступление в кампании %s не удалось", campaign_id)
                return None

    def schedule_replan(self, campaign_id: str) -> None:
        """Пересмотр оставшихся актов после закрытия акта (раздел 3): в фоне, ход его не ждёт."""
        from app.agents import architect

        self._spawn(architect.revise(self, campaign_id))

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._background.add(t)
        t.add_done_callback(self._background.discard)

    async def wait_idle(self, campaign_id: str | None = None) -> None:
        # ход может запустить фоновую задачу в самом конце (пересмотр каркаса), поэтому проверяем по кругу
        while True:
            agents = self.players._tasks if self.players is not None else set()
            if self._background:
                await asyncio.wait(set(self._background))
            elif agents:
                await asyncio.wait(set(agents))
            elif (t := self._tasks.get(campaign_id)) is not None and not t.done():
                await asyncio.wait({t})
            else:
                return

    def wake_players(self, cid: str) -> None:
        """Новое повествование в ответ живому игроку: ИИ-игроки могут откликнуться."""
        if self.players is not None:
            self.players.after_narration(cid)

    async def stop(self) -> None:
        tasks = [*self._tasks.values(), *self._background, *self._timers.values()]
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    async def _loop(self, cid: str) -> None:
        try:
            while True:
                self._pending.discard(cid)
                while True:
                    delay = await self._collect_delay(cid)
                    if delay is None or delay <= 0:
                        break
                    await asyncio.sleep(min(delay, 1.0))
                if delay is None:
                    if cid not in self._pending:
                        break
                    continue
                await self.run_turn(cid)
                if cid not in self._pending:
                    break
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("очередь мастера кампании %s", cid)
        finally:
            self._tasks.pop(cid, None)

    async def _collect_delay(self, cid: str) -> float | None:
        """Сколько ещё ждать реплик. None — ход не нужен: мастер не ИИ, сессии нет или новых реплик нет."""
        async with self.maker() as s:
            c = await s.get(Campaign, cid)
            if c is None or master_seat(c).occupant_type != "agent" or await active_session(s, cid) is None:
                return None
            new = await _new_player_messages(s, c)
            if not new:
                return None
            sc = await s.get(Scene, cid)
            if sc is not None and sc.mode == "combat" and sc.turn_order:
                # в бою мастер отвечает сразу на действие героя, чей ход; остальное ждёт этого ответа
                st = sc.state or {}
                cur = await s.get(Character, sc.turn_order[int(st.get("turn", 0)) % len(sc.turn_order)]["id"])
                if cur is not None and any(m.kind == "action" and m.seat_id == cur.seat_id for m in new):
                    return 0
                return None
            agents = {x.id for x in c.seats if x.occupant_type == "agent"}
            players = {
                ch.seat_id
                for ch in await s.scalars(
                    select(Character).where(Character.campaign_id == cid, Character.status.in_(("approved", "active")))
                )
                if ch.seat_id
            }
            if self.presence is not None:
                players -= self.presence.away(cid)  # ушедшего игрока не ждём
            players -= agents  # живые игроки закрывают окно сбора; ИИ ходит синхронно перед мастером
            wrote = {m.seat_id for m in new}
            if players and players <= wrote:
                return 0
            window = float((c.settings or {}).get("collect_window_sec", 60))
            waited = (datetime.now(UTC) - as_utc(new[0].created_at)).total_seconds()
            return max(0.0, window - waited)

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

    # --- ход ---

    async def _status(self, cid: str, stage: str) -> None:
        await self.bus.publish(cid, envelope("master.status", cid, {"stage": stage}), None)

    async def _states(self, cid: str, ids: list[str], state: str) -> None:
        if ids:
            await self.bus.publish(cid, envelope("message.state", cid, {"ids": ids, "state": state}), None)

    async def run_turn(self, cid: str) -> str | None:
        lock = self._locks.setdefault(cid, asyncio.Lock())
        async with lock:
            if self.players is not None:
                await self.players.take_turns(cid)
            return await self._run_turn(cid)

    async def _run_turn(self, cid: str) -> str | None:
        async with self.maker() as s:
            c = await s.get(Campaign, cid)
            if c is None:
                return None
            seat = master_seat(c)
            if seat.occupant_type != "agent":
                return None
            game = await active_session(s, cid)
            if game is None:
                return None
            new = await _new_player_messages(s, c)
            if not new:
                return None
            limit = (c.settings or {}).get("spend_limit_usd")
            if limit is not None:
                spent = (await s.scalar(select(func.sum(LlmCall.cost)).where(LlmCall.campaign_id == cid))) or 0.0
                if spent >= float(limit):
                    msg = await system_message(s, c, "Лимит расходов на модели исчерпан: мастер молчит.", game)
                    turn = MasterTurn(
                        campaign_id=cid,
                        session_id=game.id,
                        status="failed",
                        upto_seq=new[-1].seq,
                        trace={"error": "spend_limit"},
                        finished_at=now(),
                    )
                    s.add(turn)
                    await s.commit()
                    await publish_message(self.bus, msg)
                    await self._states(cid, [m.id for m in new], "failed")
                    return None
            turn = MasterTurn(campaign_id=cid, session_id=game.id, upto_seq=new[-1].seq, trace={"from_seq": new[0].seq})
            s.add(turn)
            await s.commit()
            turn_id = turn.id
            ids = [m.id for m in new]

        await self._states(cid, ids, "processing")
        await self.introduce(cid)  # новичок за столом: мастер сначала представляет его
        calls: list[LlmCall] = []
        replan = False
        await self._status(cid, "listening")
        try:
            async with self.maker() as s:
                published = await self._play(s, cid, turn_id, calls)
            if published["skipped"]:
                return turn_id
            await publish_changes(self.bus, published["ctx"], published["messages"], published["names"])
            await self._states(cid, published["ids"], "answered")
            await self.after_turn(published["ctx"])
            replan = "replan" in published["ctx"].signals
            if self.players is not None:
                self.players.reset_round(cid)
            self.schedule_summary(cid)  # сводка обновится, если набралось summary_every сообщений
        except Exception as e:  # noqa: BLE001 — сбой хода не должен ронять сервер; ход откатывается целиком
            log.exception("ход мастера %s не удался", turn_id)
            async with self.maker() as s:
                t = await s.get(MasterTurn, turn_id)
                t.status, t.finished_at = "failed", now()
                t.trace = {**(t.trace or {}), "error": f"{type(e).__name__}: {e}"}
                c = await s.get(Campaign, cid)
                msg = await system_message(
                    s, c, "Мастер не смог завершить ход. Ничего не изменилось: повторите действие.", None
                )
                sc = await s.get(Scene, cid)
                if sc is not None and (sc.state or {}).get("submitted"):
                    sc.state = {**sc.state, "submitted": False}  # заявку можно повторить
                await s.commit()
            await publish_message(self.bus, msg)
            await self._states(cid, ids, "failed")
        finally:
            await self._status(cid, "idle")
            if calls:
                async with self.maker() as s:
                    s.add_all(calls)
                    await s.commit()
        if replan:
            self.schedule_replan(cid)  # после учёта вызовов: пересмотр пишет в ту же кампанию
        return turn_id

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
    ) -> LLMReply:
        model = model_for(cfg.provider, cfg.model)
        try:
            reply = await self.llm.complete(
                messages,
                model=model,
                tools=tools,
                max_tokens=8192,
                temperature=0.2 if purpose == "decide" else cfg.temperature,
                api_base=(cfg.settings or {}).get("api_base"),
            )
        except LLMError as e:
            calls.append(
                LlmCall(
                    campaign_id=cid, seat_id=seat_id, turn_id=turn_id, purpose=purpose, model=model, error=str(e)[:2000]
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
                cost=reply.cost,
                latency_ms=reply.latency_ms,
            )
        )
        return reply

    async def _play(self, s, cid: str, turn_id: str, calls: list) -> dict:
        c = await s.get(Campaign, cid)
        turn = await s.get(MasterTurn, turn_id)
        seat = master_seat(c)
        cfg = await s.get(AgentConfig, seat.agent_config_id)
        ctx = await open_context(s, c, self.dice_factory(), turn_id=turn_id, seat_id=seat.id)
        new = await _player_messages(s, c, int(turn.trace.get("from_seq", 0)), turn.upto_seq)
        names = await _names(s, c)
        if not new:  # все реплики пакета отменены, пока ход начинался: модель не зовём
            turn.status, turn.finished_at = "skipped", now()
            await s.commit()
            return {"ctx": ctx, "messages": [], "names": names, "ids": [], "skipped": True}
        history = await _history(s, c, new[0].seq if new else turn.upto_seq + 1)
        char_by_seat = {
            ch.seat_id: ch
            for ch in ctx.world.characters.values()
            if ch.seat_id and ch.status in ("approved", "active", "dead")
        }

        system = await self._system_prompt(s, c, cfg, ctx)
        convo = _render_history(history, char_by_seat, names)
        news = _render_new(new, char_by_seat, names)
        required = {
            char_by_seat[m.seat_id].id
            for m in new
            if m.kind == "action"
            and m.seat_id in char_by_seat
            and char_by_seat[m.seat_id].status in ("approved", "active")
        }
        hero_turn = combat.current_character(ctx)  # в бою: чей ход закрывает этот ответ мастера
        combat_note = ""
        if hero_turn is not None:
            combat_note = (
                f"\n\nИдёт бой, раунд {ctx.world.scene.round}. Сейчас ход {hero_turn.name} ({hero_turn.id}): "
                "обработай только его действие. Ходы существ сервер проведёт сам после твоего ответа по их "
                "профилю поведения — не атакуй за существ и не меняй очередь."
            )

        # Маршрутизатор механик (раздел 7): однозначную атаку оружием сервер проводит сам, модель её только опишет
        trace_calls: list[dict] = []
        routed: list[str] = []
        for m in new:
            name, args = "resolve_attack", intents.routable_attack(m.intent) if m.kind == "action" else None
            if args is None and m.kind == "action":
                name, args = "cast_spell", _routable_cast(ctx, m.intent)
            actor = (args or {}).get("attacker_id") or (args or {}).get("caster_id")
            if not args or actor not in required:
                continue
            if hero_turn is not None and actor != hero_turn.id:
                continue
            await self._status(cid, "rolling")
            r = await execute(ctx, name, args, key=f"{turn_id}:route:{m.id}")
            trace_calls.append({"tool": name, "args": args, "result": r, "routed": True})
            if r.get("ok"):
                routed.append(f"{actor}: {name} уже выполнен сервером по намерению")
            elif name == "cast_spell":
                routed.append(
                    f"{actor}: cast_spell отклонён сервером: {r.get('error')} — объясни игроку в повествовании"
                )
        route_note = ""
        if routed:
            route_note = "\n\nУже сделано сервером (не повторяй эти вызовы):\n- " + "\n- ".join(routed)

        await self._status(cid, "remembering")
        memory_note = await self._memory_block(s, c, ctx, new)
        # мир не ждёт: созревшие ответы на поступки героев и случайности, выпавшие, пока шло игровое время
        world_note = await standing_tools.run_standing(ctx) + await fortune_tools.run_watch(ctx)
        # отряд буксует на одном препятствии: мир подбрасывает новую возможность (в бою не нужно)
        stall = (
            "" if hero_turn is not None else rhythm.stall_note(await rhythm.stalled_turns(s, cid, ctx.game_session_id))
        )
        msgs: list[dict] = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"{memory_note}Таблица сцены:\n{ctx.world.scene_table()}\n\n{world_note}{stall}"
                    f"Недавние сообщения чата:\n{convo or 'пока нет'}\n\n"
                    f"Новые реплики игроков:\n{news}{combat_note}{route_note}\n\nФаза решения: вызови нужные "
                    "инструменты. "
                    "Когда все действия закрыты, ответь одним словом «готово» без вызовов."
                ),
            },
        ]
        done_calls = retries = 0
        for _ in range(MAX_STEPS):
            reply = await self._ask(
                calls, cfg, cid, seat.id, turn_id, "decide", msgs, tool_specs(ctx.world, decision_tools(ctx))
            )
            msgs.append(reply.message or {"role": "assistant", "content": reply.text})
            if not reply.tool_calls:
                open_ = required - ctx.closed
                if open_ and retries < 1:
                    retries += 1
                    names_open = ", ".join(f"{i} ({ctx.world.characters[i].name})" for i in sorted(open_))
                    msgs.append(
                        {
                            "role": "user",
                            "content": (
                                f"Не закрыты действия персонажей: {names_open}. На каждое действие вызови инструмент "
                                "или cancel_action с причиной."
                            ),
                        }
                    )
                    continue
                break
            for call in reply.tool_calls:
                if done_calls >= MAX_CALLS:
                    result = {
                        "ok": False,
                        "error": f"лимит {MAX_CALLS} вызовов за ход исчерпан: переходи к повествованию",
                    }
                elif "__invalid_json__" in call.arguments:
                    result = {"ok": False, "error": "аргументы — не JSON-объект"}
                else:
                    if call.name in ROLL_TOOLS:
                        await self._status(cid, "rolling")
                    result = await execute(ctx, call.name, call.arguments, key=f"{turn_id}:{call.id}")
                    if call.name not in AUDIO_TOOLS:  # звук не отнимает вызовы у механики
                        done_calls += 1
                trace_calls.append({"tool": call.name, "args": call.arguments, "result": result})
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )
            if done_calls >= MAX_CALLS and all(not t["result"].get("ok") for t in trace_calls[-1:]):
                break

        # Контракт намерения: молчание запрещено — код сам фиксирует отказ (раздел 7.1)
        for cid_ in sorted(required - ctx.closed):
            r = await execute(
                ctx,
                "cancel_action",
                {"character_id": cid_, "reason": "мастер не обработал действие"},
                key=f"{turn_id}:auto_cancel:{cid_}",
            )
            trace_calls.append({"tool": "cancel_action", "auto": True, "result": r})

        combat_notes: list[str] = []
        if combat.in_combat(ctx):
            acted = hero_turn is not None and any(m.kind == "action" and m.seat_id == hero_turn.seat_id for m in new)
            if acted and combat.current_id(ctx) == hero_turn.id:
                await combat.finish_turn(ctx, combat_notes)
            await self._status(cid, "rolling")
            combat_notes += await combat.run_until_hero(ctx, f"{turn_id}:combat", self._ask_reaction)

        plot_notes = await plot_tools.run_clock(ctx)  # злодеи не ждут: шаги угрозы по игровым дням

        await self._status(cid, "describing")
        voiced = bool(getattr(self, "tts", None) and self.tts.enabled and getattr(self, "media_dir", None))
        narration, audit = await self._narrate(
            calls,
            cfg,
            c,
            seat.id,
            turn_id,
            system,
            convo,
            news,
            ctx,
            combat_notes,
            plot_notes,
            stalled=bool(stall),
            voiced=voiced,
        )

        tts_task = None
        if voiced:
            # озвучивается краткая суть хода, подробности остаются текстом
            spoken = audit.get("voice_text") or narration
            tts_task = asyncio.create_task(self.tts.voice_for_narration(self.media_dir, cid, spoken))

        whispers = await flush_outbox(s, ctx)
        linked = await link_text(s, cid, narration)

        voice_data = None
        if tts_task is not None:
            try:
                voice_data = await tts_task
            except Exception:
                log.exception("ошибка генерации озвучки мастера")

        msg_data: dict[str, Any] = {}
        if voice_data:
            msg_data["voice"] = voice_data

        msg = Message(
            campaign_id=cid,
            session_id=ctx.game_session_id,
            seq=await next_seq(s, cid),
            seat_id=seat.id,
            kind="narration",
            content=linked,
            data=msg_data or None,
        )
        s.add(msg)
        await s.flush()
        turn.status, turn.finished_at, turn.narration_message_id = "done", now(), msg.id
        turn.trace = {
            "calls": trace_calls,
            "audit": audit,
            "required": sorted(required),
            "closed": sorted(ctx.closed),
            "combat": combat_notes,
            "plot_clock": plot_notes,
            "world": world_note,
            "stalled": bool(stall),
        }
        await s.commit()
        return {"ctx": ctx, "messages": [*whispers, msg], "names": names, "ids": [m.id for m in new], "skipped": False}

    async def _narrate(
        self,
        calls,
        cfg,
        c,
        seat_id,
        turn_id,
        system,
        convo,
        news,
        ctx: ToolContext,
        notes=(),
        plot_notes=(),
        *,
        stalled: bool = False,
        voiced: bool = False,
    ):
        results = _render_results(ctx)
        turn = combat.public_turn(ctx.world)
        prompt = render(
            "narrate.j2",
            results=results,
            scene=ctx.world.scene_table(),
            length=_narration_length(ctx, notes),
            check_only=_check_only(ctx, notes),
            combat_notes=list(notes),
            plot_notes=list(plot_notes),
            next_turn=turn["name"] if turn else None,
            stalled=stalled,
            voiced=voiced,
        )
        base = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Недавние сообщения чата:\n{convo or 'пока нет'}\n\n"
                f"Реплики игроков этого хода:\n{news}\n\n{prompt}",
            },
        ]
        known = set(ctx.world.characters) | set(ctx.world.entities)
        audit: dict[str, Any] = {"regenerated": False, "stripped": []}
        reply = await self._ask(calls, cfg, c.id, seat_id, turn_id, "narrate", base, None)
        text = reply.text.strip()
        unknown = sorted({m.group(1) for m in MARKUP.finditer(text) if m.group(1) not in known})
        if unknown:
            audit["regenerated"] = True
            audit["unknown_first"] = unknown
            retry = [
                *base,
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": (
                        f"В тексте размечены сущности, которых нет в реестре: {', '.join(unknown)}. Перепиши ответ: "
                        "размечай только id из таблицы сцены, новых существ и предметов не вводи."
                    ),
                },
            ]
            reply = await self._ask(calls, cfg, c.id, seat_id, turn_id, "narrate", retry, None)
            text = reply.text.strip()

        def strip(m: re.Match) -> str:
            if m.group(1) in known:
                return m.group(0)
            audit["stripped"].append(m.group(1))
            return m.group(2)

        voice_text, text = _split_voice(text)
        if voice_text:
            audit["voice_text"] = MARKUP.sub(r"\2", voice_text)
        text = MARKUP.sub(strip, text)
        # Очистка от случайных вызовов инструментов в тексте мастера (например, set_soundscape {...})
        text = re.sub(r"^\s*[a-z_]+\s*\{.*?\}\s*", "", text, flags=re.DOTALL).strip()
        # Очистка от оборванного незакрытого тега разметки в конце текста
        text = re.sub(r"\[\[[^\]]*$", "", text).rstrip()
        return text or "…", audit

    async def _system_prompt(self, s, c: Campaign, cfg: AgentConfig, ctx: ToolContext) -> str:
        secret = await s.get(CampaignSecret, c.id)
        secrets = ""
        has_plot = bool(secret and plot.has_plan(secret.plot))
        if has_plot:
            # «Сюжет сейчас» — текущий акт и что рядом; весь каркас мастер читает через get_plot
            extra = json.dumps(secret.setting, ensure_ascii=False)[:4000] if secret.setting else ""
            now_ = plot.now_block(secret.plot, location_entity_id=ctx.world.scene.location_id)
            secrets = (now_ + ("\n" + extra if extra else ""))[:16000]
        elif secret and (secret.setting or secret.plot):
            secrets = json.dumps({"setting": secret.setting, "plot": secret.plot}, ensure_ascii=False)[:12000]
        ties = [
            f"{ch.name} ({ch.id}):\n{text}"
            for ch in ctx.world.characters.values()
            if ch.status in ("approved", "active") and (text := bonds.render(ch, private=True))
        ]
        if ties:
            secrets = (secrets + "\n" if secrets else "") + "Связи героев (ответы игроков):\n" + "\n".join(ties)
        # характеры героев (анкета и летопись) мастер видит, как видит лист: чтобы NPC и сцены цепляли героев
        chars = []
        for ch in ctx.world.characters.values():
            if ch.status not in ("approved", "active"):
                continue
            if text := persona.render(ch.persona, await persona.notes_of(s, c.id, ch.id)):
                chars.append(f"{ch.name} ({ch.id}):\n{text}")
        if chars:
            secrets = (secrets + "\n" if secrets else "") + "Характеры героев:\n" + "\n".join(chars)
        style = cfg.persona or ""
        own = persona.render((cfg.settings or {}).get("character"), await persona.notes_of(s, c.id, None), master=True)
        if own:
            style = (style + "\n\n" if style else "") + "Твой характер как мастера:\n" + own
        dc = ", ".join(f"{e.id} = {e.data['value']} ({e.name})" for e in ctx.world.catalog.dc_scale())
        return render(
            "master_system.j2",
            campaign_name=c.name,
            style=style or None,
            brief=brief_text(c.brief),
            excluded_themes=", ".join((c.settings or {}).get("excluded_themes") or []),
            public_intro=c.public_intro,
            secrets=secrets,
            has_plot=has_plot,
            pacing=rhythm.pacing_note((c.brief or {}).get("length"), await rhythm.turns_played(s, c.id)),
            dc_scale=dc,
            max_calls=MAX_CALLS,
            leveling=progress_tools.leveling(c),
            random_events=fortune_tools.random_events(c),
            audio=audio.prompt_block(c, ctx.world.scene),
        )

    # --- память (раздел 9) ---

    async def _memory_block(self, s, c: Campaign, ctx: ToolContext, new: list[Message]) -> str:
        """Сводка кампании и фрагменты правил и лора, найденные по новым репликам и месту действия."""
        parts = []
        last = await memory.latest(s, c.id)
        text = memory.render_content(last.content) if last else ""
        if text:
            parts.append("Сводка кампании (без чисел: числа только в таблице сцены):\n" + text)
        loc = ctx.world.entities.get(ctx.world.scene.location_id or "")
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
                model = parser_model_for(cfg.provider, cfg.model)
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
        from app.core.chat import visible

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
            model = parser_model_for(cfg.provider, cfg.model) if cfg is not None else None
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
            ch_id, provider, cfg_model, master_seat_id = ch.id, cfg.provider, cfg.model, seat.id
            api_base = (cfg.settings or {}).get("api_base")
            await s.rollback()
        model = parser_model_for(provider, cfg_model)
        call = LlmCall(campaign_id=cid, seat_id=master_seat_id, turn_id=None, purpose="parse", model=model)
        try:
            reply = await asyncio.wait_for(self._parse_call(model, info, text, values, api_base), timeout=PARSE_TIMEOUT)
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
        self, model: str, info: str, text: str, values: dict, api_base: str | None = None
    ) -> LLMReply:
        return await self.llm.complete(
            [
                {"role": "system", "content": intents.PARSER_SYSTEM},
                {"role": "user", "content": f"{info}\n\nРеплика игрока:\n{text}"},
            ],
            model=model,
            tools=[intents.tool_spec(values)],
            max_tokens=1500,
            temperature=0.0,
            api_base=api_base,
        )

    # --- пошаговый режим: ход, таймаут, реакции (раздел 5, 7.2) ---

    async def after_turn(self, ctx: ToolContext) -> None:
        """После фиксации хода: всем — чей ход, и таймер хода героя."""
        cid = ctx.campaign.id
        turn = combat.public_turn(ctx.world)
        await self.bus.publish(cid, envelope("turn.changed", cid, {"turn": turn}), None)
        old = self._timers.pop(cid, None)
        if old is not None and old is not asyncio.current_task():
            old.cancel()
        if turn and turn.get("deadline"):
            marker = combat.turn_marker(ctx.world.scene)
            self._timers[cid] = asyncio.create_task(self._timeout_after(cid, marker, float(turn["deadline"])))
        if self.presence is not None:
            await self.presence.turn_changed(cid, turn)
        self._watch_strong(ctx)
        if turn and not turn.get("submitted") and self.players is not None:
            seat = next((x for x in ctx.campaign.seats if x.id == turn.get("seat_id")), None)
            if seat is not None and seat.role == "player" and seat.occupant_type == "agent":
                self.players.combat_turn(cid, seat.id)

    def _watch_strong(self, ctx: ToolContext) -> None:
        """Сильное событие — гибель героя, конец боя или момент, отмеченный мастером (``mark_moment``):
        летопись характера пишется сразу, не ждёт конца сессии."""
        cid = ctx.campaign.id
        heroes = ctx.world.characters.values()
        dead = frozenset(ch.id for ch in heroes if ch.status == "dead" or (ch.resources or {}).get("dead"))
        mode = ctx.world.scene.mode
        before = self._seen.get(cid)
        self._seen[cid] = (dead, mode)
        reasons = []
        if before is not None:
            reasons += [f"пал герой {ctx.world.characters[i].name}" for i in dead - before[0]]
            if before[1] == "combat" and mode != "combat":
                reasons.append("бой закончился")
        for ev in ctx.events:
            if ev.tool == "mark_moment":
                p = ev.payload or {}
                reasons.append(f"{p.get('label') or 'сильный момент'}: {p.get('text') or ''}".rstrip(": "))
        if reasons:
            self._spawn(self._safe(character.chronicle(self, cid, "; ".join(reasons)), "летопись"))

    async def _timeout_after(self, cid: str, marker: str | None, deadline: float) -> None:
        try:
            await asyncio.sleep(max(0.0, deadline - time.time()))
            await self.run_timeout(cid, marker)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("таймаут хода в кампании %s", cid)

    async def resume_timers(self) -> None:
        """После перезапуска сервера: снова завести таймеры ходов в идущих боях."""
        async with self.maker() as s:
            rows = (await s.scalars(select(Scene).where(Scene.mode == "combat"))).all()
        for sc in rows:
            deadline = (sc.state or {}).get("deadline")
            if deadline:
                marker = combat.turn_marker(sc)
                self._timers[sc.campaign_id] = asyncio.create_task(
                    self._timeout_after(sc.campaign_id, marker, float(deadline))
                )

    async def run_timeout(self, cid: str, marker: str | None) -> str | None:
        """Время хода героя вышло: действие по умолчанию — «выжидает», затем ходят существа."""
        return await self.advance(cid, "timeout", marker=marker)

    async def advance(self, cid: str, reason: str, *, marker: str | None = None, seat_id: str | None = None):
        """Сдвигает очередь боя без заявки героя и проводит ходы существ до следующего героя.

        ``timeout`` — вышло время (герой выжидает); ``pass`` — игрок сам пропустил ход (только место героя, чей ход);
        ``master`` — живой мастер закрыл ход героя; ``sync`` — очередь только что собрана: первыми могут быть существа;
        ``away`` — игрок героя, чей ход, ушёл из сети (раздел 11).
        Возвращает id хода мастера или None, если сдвигать нечего."""
        lock = self._locks.setdefault(cid, asyncio.Lock())
        async with lock:
            calls: list[LlmCall] = []
            try:
                async with self.maker() as s:
                    c = await s.get(Campaign, cid)
                    sc = await s.get(Scene, cid)
                    if c is None or sc is None or combat.turn_marker(sc) is None:
                        return None
                    if marker is not None and combat.turn_marker(sc) != marker:
                        return None
                    if reason in ("timeout", "away") and (sc.state or {}).get("submitted"):
                        return None  # герой успел заявить действие: ход ведёт мастер
                    game = await active_session(s, cid)
                    seat = master_seat(c)
                    last = await s.scalar(select(func.max(MasterTurn.upto_seq)).where(MasterTurn.campaign_id == cid))
                    turn = MasterTurn(
                        campaign_id=cid,
                        session_id=game.id if game else None,
                        upto_seq=last or 0,
                        trace={"advance": reason, "marker": combat.turn_marker(sc)},
                    )
                    s.add(turn)
                    await s.flush()
                    ctx = await open_context(s, c, self.dice_factory(), turn_id=turn.id, seat_id=seat.id)
                    hero = combat.current_character(ctx)
                    if reason == "pass" and (hero is None or hero.seat_id is None or hero.seat_id != seat_id):
                        await s.rollback()
                        return None
                    away = self.presence.away(cid) if self.presence is not None else set()
                    if reason == "away" and (hero is None or hero.seat_id not in away):
                        await s.rollback()
                        return None  # игрок успел вернуться, или героя уже ведёт другой
                    notes: list[str] = []
                    if hero is not None and reason != "sync":
                        what = {
                            "timeout": "выжидает",
                            "pass": "пропускает ход",
                            "master": "завершает ход",
                            "away": "пропускает ход: игрок вне сети",
                        }[reason]
                        await ctx.record("turn_end", actor_id=hero.id, payload={"reason": reason, "action": what})
                        if reason == "timeout":
                            notes.append(f"время хода {hero.name} вышло: {hero.name} выжидает")
                        elif reason == "pass":
                            notes.append(f"{hero.name} пропускает ход")
                        elif reason == "away":
                            notes.append(f"{hero.name} пропускает ход: игрок вне сети")
                        await combat.finish_turn(ctx, notes)
                    await self._status(cid, "rolling")
                    notes += await combat.run_until_hero(ctx, f"{turn.id}:combat", self._ask_reaction)
                    names = await _names(s, c)
                    messages = await flush_outbox(s, ctx)
                    acted = [e for e in ctx.events if e.tool != "turn_end"]
                    msg = None
                    if seat.occupant_type == "agent" and acted:
                        cfg = await s.get(AgentConfig, seat.agent_config_id)
                        await self._status(cid, "describing")
                        system = await self._system_prompt(s, c, cfg, ctx)
                        news = "- " + "\n- ".join(notes) if notes else "нет"
                        text, audit = await self._narrate(calls, cfg, c, seat.id, turn.id, system, "", news, ctx, notes)
                        kind, trace_extra = "narration", {"audit": audit}
                    elif notes:
                        joined = "; ".join(notes)
                        text, kind, trace_extra = joined[:1].upper() + joined[1:] + ".", "system", {}
                    else:
                        text, kind, trace_extra = None, None, {}
                    if text is not None:
                        msg = Message(
                            campaign_id=cid,
                            session_id=ctx.game_session_id,
                            seq=await next_seq(s, cid),
                            seat_id=seat.id if kind == "narration" else None,
                            kind=kind,
                            content=text,
                        )
                        s.add(msg)
                        await s.flush()
                    turn.status, turn.finished_at = "done", now()
                    turn.narration_message_id = msg.id if msg else None
                    turn.trace = {**turn.trace, "combat": notes, **trace_extra}
                    await s.commit()
                await publish_changes(self.bus, ctx, [*messages, *([msg] if msg else [])], names)
                await self.after_turn(ctx)
                return turn.id
            finally:
                await self._status(cid, "idle")
                if calls:
                    async with self.maker() as s:
                        s.add_all(calls)
                        await s.commit()

    async def _ask_reaction(self, ctx: ToolContext, ch: Character, creature) -> bool:
        """Кнопка реакции игроку с таймером (по умолчанию 15 с). Нет ответа — реакция не используется."""
        if not ch.seat_id:
            return False
        seat = next((x for x in ctx.campaign.seats if x.id == ch.seat_id), None)
        if seat is not None and seat.role == "player" and seat.occupant_type == "agent":
            return not seat.delegated_from  # ИИ-игрок бьёт вслед; за ушедшего игрока — осторожно, не бьёт
        cid = ctx.campaign.id
        wait = float((ctx.campaign.settings or {}).get("reaction_sec") or combat.REACTION_SEC)
        prompt_id = "rx_" + uuid.uuid4().hex[:12]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._reactions[prompt_id] = (cid, ch.seat_id, fut, None)
        hero = ctx.world.actor(ch.id)
        payload = {
            "prompt_id": prompt_id,
            "character_id": ch.id,
            "trigger": f"«{creature.name}» выходит из ближнего боя",
            "options": combat.reaction_options(hero, creature),
            "expires_at": time.time() + wait,
        }
        self._reactions[prompt_id] = (cid, ch.seat_id, fut, payload)
        await self.bus.publish(cid, envelope("reaction.prompt", cid, payload), [ch.seat_id])
        try:
            choice = await asyncio.wait_for(fut, timeout=wait)
        except TimeoutError:
            choice = "skip"
        finally:
            self._reactions.pop(prompt_id, None)
        await self.bus.publish(
            cid, envelope("reaction.closed", cid, {"prompt_id": prompt_id, "choice": choice}), [ch.seat_id]
        )
        return choice == "opportunity_attack"

    def resolve_reaction(self, prompt_id: str, seat_id: str | None, option: str) -> bool:
        entry = self._reactions.get(prompt_id)
        if entry is None or entry[1] != seat_id or entry[2].done():
            return False
        entry[2].set_result(option)
        return True

    def pending_reaction(self, cid: str, seat_id: str | None) -> dict | None:
        """Открытая кнопка реакции этого места, если есть."""
        for c, seat, fut, payload in self._reactions.values():
            if c == cid and seat == seat_id and payload is not None and not fut.done():
                return payload
        return None

    # --- проверка персонажа ИИ-мастером (раздел 5.1) ---

    async def review_character(self, cid: str, character_id: str) -> str | None:
        """Проверка героя ИИ-мастером. Если модель недоступна или так и не вынесла решения, герой остаётся
        на проверке, а причина пишется в журнал и видна игроку и владельцу: владелец может проверить сам."""
        lock = self._locks.setdefault(cid, asyncio.Lock())
        async with lock:
            calls: list[LlmCall] = []
            error = None
            try:
                attempted, status = await self._review(cid, character_id, calls)
                if attempted and not status:
                    error = "модель не вынесла решения за три попытки"
            except asyncio.CancelledError:
                raise
            except LLMError as e:
                attempted, status, error = True, None, explain(str(e))
            except Exception as e:  # noqa: BLE001 — сбой проверки не должен теряться молча
                log.exception("проверка героя %s сорвалась", character_id)
                attempted, status, error = True, None, f"{type(e).__name__}: {e}"[:500]
            finally:
                if calls:
                    async with self.maker() as s:
                        s.add_all(calls)
                        await s.commit()
            if error:
                async with self.maker() as s:
                    failed = {"error": error}
                    s.add(Event(campaign_id=cid, tool="review_failed", target_id=character_id, payload=failed))
                    await s.commit()
                await self.bus.publish(
                    cid, envelope("character.review_failed", cid, {"character_id": character_id, "error": error}), None
                )
            return status

    async def _review(self, cid: str, character_id: str, calls: list) -> tuple[bool, str | None]:
        """ИИ-проверка героя. Сессия БД не держится во время обращения к модели: в SQLite открытая транзакция
        не даёт другим писать, и игроки получали «database is locked», пока модель думала."""
        from app.core.characters import full_view

        async with self.maker() as s:
            c = await s.get(Campaign, cid)
            seat = master_seat(c)
            if seat.occupant_type != "agent":
                return False, None
            seat_id = seat.id
            cfg = await s.get(AgentConfig, seat.agent_config_id)
            ctx = await open_context(s, c, self.dice_factory(), turn_id=None, seat_id=seat_id)
            ch = ctx.world.characters.get(character_id)
            if ch is None or ch.status != "submitted":
                return False, None
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
        for _ in range(3):
            reply = await self._ask(calls, cfg, cid, seat_id, None, "review", msgs, tools)
            msgs.append(reply.message or {"role": "assistant", "content": reply.text})
            if not reply.tool_calls:
                msgs.append({"role": "user", "content": "Вызови review_character."})
                continue
            async with self.maker() as s:
                c = await s.get(Campaign, cid)
                ctx = await open_context(s, c, self.dice_factory(), turn_id=None, seat_id=seat_id)
                ch = ctx.world.characters.get(character_id)
                if ch is None or ch.status != "submitted":
                    return False, None  # пока модель думала, героя проверил человек или игрок его отозвал
                status = None
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
                    if r.get("ok"):
                        status = r["result"]["status"]
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
                            {"character": full, "status": status, "comment": ch.review_comment},
                        ),
                        [ch.seat_id],
                    )
                return True, status
        return True, None


async def _new_player_messages(s, c: Campaign) -> list[Message]:
    """Реплики игроков после последнего хода мастера (удачного, идущего или сорвавшегося: сорвавшийся ход
    просит игроков повторить действие, поэтому его реплики второй раз не берутся)."""
    last = await s.scalar(select(func.max(MasterTurn.upto_seq)).where(MasterTurn.campaign_id == c.id)) or 0
    return await _player_messages(s, c, last + 1, None)


async def _player_messages(s, c: Campaign, from_seq: int, upto_seq: int | None) -> list[Message]:
    players = {x.id for x in c.seats if x.role == "player"}
    q = select(Message).where(Message.campaign_id == c.id, Message.seq >= from_seq, Message.kind.in_(PLAYER_KINDS))
    if upto_seq is not None:
        q = q.where(Message.seq <= upto_seq)
    rows = await s.scalars(q.order_by(Message.seq))
    return [m for m in rows if m.seat_id in players]


async def _history(s, c: Campaign, before_seq: int) -> list[Message]:
    rows = await s.scalars(
        select(Message)
        .where(Message.campaign_id == c.id, Message.seq < before_seq, Message.kind.notin_(("ooc", "roll")))
        .order_by(Message.seq.desc())
        .limit(HISTORY)
    )
    return list(reversed(rows.all()))


async def _names(s, c: Campaign) -> dict[str, str]:
    ids = [x.user_id for x in c.seats if x.user_id] + [c.owner_id]
    rows = await s.scalars(select(User).where(User.id.in_(ids)))
    return {u.id: u.name for u in rows}


KIND_RU = {
    "action": "действие",
    "speech": "речь",
    "whisper": "шёпот мастеру",
    "narration": "мастер",
    "system": "система",
}


def _who(m: Message, char_by_seat: dict, names: dict) -> str:
    ch = char_by_seat.get(m.seat_id)
    player = names.get(m.author_user_id or "", "")
    if ch is not None:
        return f"{ch.name} ({ch.id}{', игрок ' + player if player else ''})"
    return player or "мастер"


def _render_history(rows: list[Message], char_by_seat: dict, names: dict) -> str:
    out = []
    for m in rows:
        if m.kind == "narration" and m.visible_to is not None:
            out.append(f"[мастер шёпотом, видит только адресат] {m.content}")
        elif m.kind == "narration":
            out.append(f"[мастер] {m.content}")
        elif m.kind == "system":
            out.append(f"[система] {m.content}")
        else:
            out.append(f"[{KIND_RU.get(m.kind, m.kind)}] {_who(m, char_by_seat, names)}: {m.content}")
    return "\n".join(out)


def _render_new(rows: list[Message], char_by_seat: dict, names: dict) -> str:
    out = []
    for m in rows:
        note = "" if m.seat_id in char_by_seat else " (у игрока ещё нет персонажа)"
        out.append(f"- [{KIND_RU.get(m.kind, m.kind)}] {_who(m, char_by_seat, names)}{note}: {m.content}")
        if m.kind == "action" and m.intent:
            out.append(f"  намерение (разбор парсера): {intents.describe(m.intent)}")
    return "\n".join(out)


VOICE_LINE = re.compile(r"^\s*(?:\*\*)?Голос:(?:\*\*)?\s*(.+?)\s*(?:\n\s*\n|\n|$)", re.IGNORECASE)


def _split_voice(text: str) -> tuple[str | None, str]:
    """Первая строка «Голос: …» — краткая суть хода для озвучки; остальное — ответ в чат."""
    m = VOICE_LINE.match(text)
    if m is None:
        return None, text
    return m.group(1).strip() or None, text[m.end() :].strip()


def _check_only(ctx: ToolContext, notes=()) -> bool:
    """Ход вне боя, в котором были только проверки: ответ — короткое литературное описание исхода."""
    tools = [ev.tool for ev in ctx.events if ev.tool not in AUDIO_TOOLS]
    return not notes and not combat.in_combat(ctx) and bool(tools) and set(tools) == {"roll_check"}


def _narration_length(ctx: ToolContext, notes=()) -> str:
    if _check_only(ctx, notes):
        return "одно-два предложения"
    if notes or combat.in_combat(ctx):
        return "от одного до четырёх абзацев"
    return (
        "один короткий абзац, два-четыре предложения; второй абзац — только если герои попали в новое место или "
        "случилось что-то важное для сюжета"
    )


def _render_results(ctx: ToolContext) -> str:
    out = []
    for ev in ctx.events:
        if ev.tool in AUDIO_TOOLS:
            continue
        res = ev.payload.get("result", ev.payload)
        if ev.tool in plot_tools.PLOT_TOOLS or ev.tool == "threat_clock":
            mark = " [СЮЖЕТ: только для мастера, прямо не называй]"
        else:
            mark = " [СКРЫТЫЙ БРОСОК: игрокам только последствия]" if ev.hidden else ""
        out.append(f"- {ev.tool}{mark}: {json.dumps(res, ensure_ascii=False, default=str)}")
    return "\n".join(out)
