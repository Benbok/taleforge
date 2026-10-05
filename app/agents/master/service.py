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
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents import character, rhythm
from app.agents.llm import LLM
from app.agents.master.helpers import _batches, _in_fight
from app.agents.master.narration import NarrationMixin
from app.agents.master.parsing import ParsingMixin
from app.agents.master.recall import RecallMixin
from app.agents.master.review import ReviewMixin
from app.agents.master.stepwise import StepwiseMixin
from app.agents.master.turn import TurnMixin
from app.agents.master.whispers import WhisperMixin
from app.core.campaigns import master_seat
from app.core.chat import active_session
from app.db.models import Campaign, Character, Scene, as_utc
from app.gateway.coordination import Coordination, InMemoryCoordination
from app.rules.dice import Dice
from app.tools.registry import ToolContext

log = logging.getLogger(__name__)


class MasterService(WhisperMixin, TurnMixin, NarrationMixin, RecallMixin, ParsingMixin, StepwiseMixin, ReviewMixin):
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
        coordination: Coordination | None = None,
    ):
        self.maker = sessionmaker
        self.bus = bus
        self.llm = llm
        self.dice_factory = dice_factory
        self.media_dir = media_dir
        self.tts = tts
        # замки кампаний и открытые кнопки реакций: единственное место, которое меняется, когда серверов станет
        # больше одного (app/gateway/coordination.py)
        self.coordination = coordination or InMemoryCoordination()
        self._tasks: dict[str, asyncio.Task] = {}
        self._pending: set[str] = set()
        self._background: set[asyncio.Task] = set()
        self._timers: dict[str, asyncio.Task] = {}  # таймер хода героя в бою, по кампаниям
        self._summarizing: set[str] = set()
        self.presence = None  # app/gateway/presence.py: кто из игроков ушёл во время сессии (раздел 11)
        self.players = None  # app/agents/player.py: ИИ-игроки (раздел 5.2)
        self._seen: dict[str, tuple[frozenset, str]] = {}  # павшие герои и режим сцены: для сильных событий
        self._audience: dict[str, list[str]] = {}  # кто видит идущий ход, если отряд разделён

    def turn_lock(self, cid: str) -> asyncio.Lock:
        """Замок хода кампании: под ним идут ход мастера, ходы существ и запись итогов озвучки."""
        return self.coordination.turn_lock(cid)

    def intro_lock(self, cid: str) -> asyncio.Lock:
        """Замок вступления: мастер представляет новичка и кампанию под ним."""
        return self.coordination.intro_lock(cid)

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
        """Старт сессии: вступление ко всей кампании, представление новых героев, затем цель на вечер."""

        async def run() -> None:
            await self._status(campaign_id, "describing")
            try:
                # 1. Интро всей кампании (только один раз в самом начале)
                await self.introduce_campaign(campaign_id)
                # 2. Вступление для непредставленных героев
                await self.introduce(campaign_id)
                # 3. Цель на вечер
                if session_id:
                    await self._safe(rhythm.session_goal(self, campaign_id, session_id), "цель на вечер")
            finally:
                async with self.maker() as s:
                    c = await s.get(Campaign, campaign_id)
                    if c and (c.settings or {}).get("intro_generating"):
                        c.settings = {**(c.settings or {}), "intro_generating": False}
                        await s.commit()
                await self._status(campaign_id, "idle")

        self._spawn(run())

    def schedule_session_close(self, campaign_id: str, session_id: str | None, ended: bool) -> None:
        """Конец сессии: сводка, затем зацепка на следующий раз или, при завершении кампании, эпилог."""

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

    async def introduce_campaign(self, campaign_id: str) -> str | None:
        """Вступление ко всей кампании (2–4 абзаца о мире, ситуации и месте); одно на кампанию."""
        from app.agents import prelude

        async with self.intro_lock(campaign_id):
            try:
                return await prelude.introduce_campaign(self, campaign_id)
            except Exception:  # noqa: BLE001 — без вступления игра всё равно идёт
                log.exception("вступление ко всей кампании %s не удалось", campaign_id)
                return None

    async def introduce(self, campaign_id: str) -> str | None:
        """Вступление для ещё не представленных героев; одно на кампанию за раз."""
        from app.agents import prelude

        async with self.intro_lock(campaign_id):
            try:
                return await prelude.introduce(self, campaign_id)
            except Exception:  # noqa: BLE001 — без вступления игра всё равно идёт
                log.exception("вступление в кампании %s не удалось", campaign_id)
                return None

    def schedule_replan(self, campaign_id: str) -> None:
        """Пересмотр оставшихся актов после закрытия акта (раздел 3): в фоне, ход его не ждёт."""
        from app.agents import architect

        self._spawn(architect.revise(self, campaign_id))

    def schedule_sketches(self, ctx: ToolContext) -> None:
        """Мастер описал место (``describe_place``): техническая модель строит эскиз в фоне, ход его не ждёт."""
        from app.agents import surveyor

        for sig in sorted(x for x in ctx.signals if x.startswith("sketch:")):
            ctx.signals.discard(sig)
            self._spawn(self._safe(surveyor.draw(self, ctx.campaign.id, sig.split(":", 1)[1]), "эскиз места"))

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
                    delay, place = await self._collect_delay(cid)
                    if delay is None or delay <= 0:
                        break
                    await asyncio.sleep(min(delay, 1.0))
                if delay is None:
                    if cid not in self._pending:
                        break
                    continue
                # разделившийся отряд: после хода одной группы, возможно, уже готова другая
                if await self.run_turn(cid, place) is None and cid not in self._pending:
                    break
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("очередь мастера кампании %s", cid)
        finally:
            self._tasks.pop(cid, None)

    async def _collect_delay(self, cid: str) -> tuple[float | None, str | None]:
        """Сколько ещё ждать реплик и для какой группы отряда. None — ход не нужен: мастер не ИИ, сессии нет или
        новых реплик нет. Разделившийся отряд собирает реплики по группам: каждая ждёт только своих игроков."""
        async with self.maker() as s:
            c = await s.get(Campaign, cid)
            if c is None or master_seat(c).occupant_type != "agent" or await active_session(s, cid) is None:
                return None, None
            batches, groups = await _batches(s, c)
            if not batches:
                return None, None
            sc = await s.get(Scene, cid)
            agents = {x.id for x in c.seats if x.occupant_type == "agent"}
            away = self.presence.away(cid) if self.presence is not None else set()
            window = float((c.settings or {}).get("collect_window_sec", 60))
            best: tuple[float | None, str | None] = (None, None)
            for place, new in batches.items():
                heroes = groups.get(place, []) if place is not None else [h for hs in groups.values() for h in hs]
                if sc is not None and sc.mode == "combat" and sc.turn_order and _in_fight(sc, heroes):
                    # в бою мастер отвечает сразу на действие героя, чей ход; остальное ждёт этого ответа
                    st = sc.state or {}
                    cur = await s.get(Character, sc.turn_order[int(st.get("turn", 0)) % len(sc.turn_order)]["id"])
                    if cur is not None and any(m.kind == "action" and m.seat_id == cur.seat_id for m in new):
                        return 0, place
                    continue
                players = {h.seat_id for h in heroes if h.seat_id}
                players -= away  # ушедшего игрока не ждём
                players -= agents  # живые игроки закрывают окно сбора; ИИ ходит синхронно перед мастером
                wrote = {m.seat_id for m in new}
                if players and players <= wrote:
                    return 0, place
                waited = (datetime.now(UTC) - as_utc(new[0].created_at)).total_seconds()
                delay = max(0.0, window - waited)
                if best[0] is None or delay < best[0]:
                    best = (delay, place)
            return best
