"""Офлайн и голосование (ТЗ, раздел 11).

Пока сессия идёт, обрыв связи не сразу считается уходом: место 60 секунд «переподключается», и только потом
становится «офлайн». В бою ход такого героя пропускается (через 5 секунд: перезагрузка страницы — не уход),
вне боя мастер его реплику не ждёт.
Когда игрок ушёл, оставшиеся живые игроки голосуют: отдать героя другому игроку или поставить паузу
(передать героя ИИ — с ИИ-игроками, этап 9). Ушёл живой мастер — голосуют за ИИ-мастера или паузу.
Решает простое большинство (больше половины голосующих); ничья или 2 минуты без решения — пауза.
Вернулся во время голосования — оно отменяется. Вернулся, когда героя уже ведёт другой, — получает его обратно
в начале следующего хода и короткую сводку пропущенного. Ушли все игроки — пауза без голосования.

Состояние живёт в памяти процесса: после перезапуска сервера все и так подключаются заново.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.core import chat
from app.core.campaigns import agent_for_master, master_seat
from app.core.world import get_scene
from app.db.models import Campaign, Character, Seat
from app.gateway.events import envelope, publish_message
from app.gateway.hub import Connection, Hub

log = logging.getLogger(__name__)

GRACE_SEC = 60.0  # сколько ждать переподключения до статуса «офлайн»
VOTE_SEC = 120.0  # сколько длится голосование; без решения — пауза
SKIP_SEC = 5.0  # через сколько пропускать ход героя в бою, если его игрок не вернулся
HERO = ("approved", "active")


@dataclass
class Vote:
    id: str
    campaign_id: str
    seat_id: str  # чьё место решаем
    subject: str  # player | master
    who: str  # имя ушедшего
    hero: str | None  # имя его героя; у мастера — None
    options: list[dict[str, str]]
    voters: list[str]  # места голосующих
    deadline: float
    ballots: dict[str, str] = field(default_factory=dict)
    task: asyncio.Task | None = None

    def payload(self) -> dict[str, Any]:
        tally = {o["id"]: 0 for o in self.options}
        for option in self.ballots.values():
            tally[option] += 1
        return {
            "vote_id": self.id,
            "seat_id": self.seat_id,
            "subject": self.subject,
            "who": self.who,
            "hero": self.hero,
            "options": self.options,
            "voters": self.voters,
            "voted": sorted(self.ballots),
            "tally": tally,
            "deadline": self.deadline,
        }


def _setting(c: Campaign, key: str, default: float) -> float:
    v = (c.settings or {}).get(key)
    return float(default if v is None else v)


class Presence:
    """Статусы мест, таймеры переподключения и голосования по кампаниям."""

    def __init__(self, maker, bus, hub: Hub, master) -> None:
        self.maker = maker
        self.bus = bus
        self.hub = hub
        self.master = master
        self._away: dict[tuple[str, str], str] = {}  # (кампания, место) → reconnecting | offline
        self._left_seq: dict[tuple[str, str], int] = {}  # последний seq, который видел ушедший
        self._grace: dict[tuple[str, str], asyncio.Task] = {}
        self._votes: dict[tuple[str, str], Vote] = {}
        self._returning: set[tuple[str, str]] = set()  # вернулись, героя отдадим в начале следующего хода
        self._left_at: dict[tuple[str, str], float] = {}
        self._covered: set[tuple[str, str]] = set()  # ушли, но героя ведёт другой игрок или место занял ИИ-мастер
        self._skip_after: dict[str, float] = {}
        self._tasks: set[asyncio.Task] = set()
        self._inflight: set[asyncio.Task] = set()  # входы и уходы, которые надо довести до конца
        self._locks: dict[str, asyncio.Lock] = {}
        self._stopping = False

    # --- чтение ---

    def status(self, campaign_id: str, seat: Seat) -> str | None:
        if seat.user_id is None or seat.occupant_type == "empty":
            return None
        user = seat.delegated_from if seat.occupant_type == "agent" else seat.user_id
        if user in self.hub.online_users(campaign_id):
            return "online"
        return self._away.get((campaign_id, seat.id), "offline")

    def away(self, campaign_id: str) -> set[str]:
        """Места, которые сейчас никто не ведёт: игрок ушёл во время сессии, и замены ему нет."""
        return {seat for (cid, seat) in self._away if cid == campaign_id and (cid, seat) not in self._covered}

    def votes(self, campaign_id: str) -> list[dict[str, Any]]:
        return [v.payload() for (cid, _), v in self._votes.items() if cid == campaign_id]

    # --- события сокетов ---

    async def before_join(self, user_id: str, campaign_id: str) -> None:
        """Живой мастер вернулся, а игру пока ведёт ИИ-мастер: место возвращается ему до входа, чтобы снимок уже
        показывал его мастером."""
        async with self.maker() as s:
            c = await s.get(Campaign, campaign_id)
            if c is None:
                return
            seat = master_seat(c)
            if not (seat.occupant_type == "agent" and seat.delegated_from and seat.delegated_from == user_id):
                return
            seat.occupant_type, seat.delegated_from = "human", None
            game = await chat.active_session(s, c.id)
            msg = await chat.system_message(s, c, "Мастер вернулся и снова ведёт игру.", game)
            await s.commit()
            seat_id = seat.id
        await publish_message(self.bus, msg)
        await self._publish_stand_in(campaign_id, seat_id, None)

    async def joined(self, conn: Connection) -> None:
        """Сокет вошёл в кампанию. Вход и уход одной кампании идут по очереди и доводятся до конца, даже если
        обработчик сокета отменят (закрыли вкладку сразу после входа)."""
        await asyncio.shield(self._track(self._serial(conn.campaign_id, self._joined(conn))))

    def leave(self, conn: Connection) -> None:
        """Сокет закрылся: уход — отдельной задачей, остановка сервера дождётся её, прежде чем закрыть базу."""
        self._track(self._serial(conn.campaign_id, self._left(conn)))

    def _track(self, coro) -> asyncio.Task:
        t = asyncio.create_task(coro)
        self._inflight.add(t)
        t.add_done_callback(self._inflight.discard)
        return t

    async def _serial(self, campaign_id: str, coro) -> None:
        async with self._locks.setdefault(campaign_id, asyncio.Lock()):
            if self._stopping:
                coro.close()
                return
            await coro

    async def _joined(self, conn: Connection) -> None:
        key = (conn.campaign_id, conn.seat_id)
        async with self.maker() as s:
            c = await s.get(Campaign, conn.campaign_id)
            conn.stand_in = {x.id for x in c.seats if x.stand_in_user_id == conn.user_id} if c else set()
            seat = next((x for x in c.seats if x.id == conn.seat_id), None) if c else None
            delegated = seat is not None and seat.stand_in_user_id is not None
            in_turn = delegated and await self._current_seat(s, conn.campaign_id) == conn.seat_id
        if conn.seat_id is None:
            return
        grace = self._grace.pop(key, None)
        if grace is not None:
            grace.cancel()
        was = self._away.pop(key, None)
        self._left_at.pop(key, None)
        self._covered.discard(key)
        left_seq = self._left_seq.pop(key, None)
        await self._publish_presence(conn.campaign_id, conn.seat_id, "online")
        vote = self._votes.get(key)
        if vote is not None:
            await self._finish(vote, "canceled")
        if delegated:
            if in_turn:
                self._returning.add(key)  # герой сейчас ходит в руках замены: вернём в начале следующего хода
            else:
                await self._give_back(conn.campaign_id, conn.seat_id)
        if was == "offline" and left_seq is not None:
            self._spawn(self._catch_up(conn.campaign_id, conn.seat_id, left_seq))

    async def _left(self, conn: Connection) -> None:
        if conn.seat_id is None or conn.user_id in self.hub.online_users(conn.campaign_id):
            return  # у игрока открыт ещё один сокет
        key = (conn.campaign_id, conn.seat_id)
        async with self.maker() as s:
            c = await s.get(Campaign, conn.campaign_id)
            game = await chat.active_session(s, conn.campaign_id) if c is not None else None
            if game is None:
                await self._publish_presence(conn.campaign_id, conn.seat_id, "offline")
                return
            grace = _setting(c, "reconnect_grace_sec", GRACE_SEC)
            self._skip_after[conn.campaign_id] = _setting(c, "away_skip_sec", SKIP_SEC)
            self._left_seq[key] = c.last_seq
            current = await self._current_seat(s, conn.campaign_id)
        self._away[key] = "reconnecting"
        self._left_at[key] = time.monotonic()
        await self._publish_presence(conn.campaign_id, conn.seat_id, "reconnecting")
        old = self._grace.pop(key, None)
        if old is not None:
            old.cancel()
        self._grace[key] = asyncio.create_task(self._grace_over(key, grace))
        if current == conn.seat_id:
            self._skip(conn.campaign_id, conn.seat_id)  # ход героя без игрока пропускается

    async def turn_changed(self, campaign_id: str, turn: dict | None) -> None:
        """Из очереди боя: вернуть героя вернувшемуся игроку и пропустить ход героя, которого никто не ведёт."""
        seat_now = (turn or {}).get("seat_id")
        for key in [k for k in self._returning if k[0] == campaign_id]:
            if key[1] != seat_now:
                self._returning.discard(key)
                await self._give_back(campaign_id, key[1])
        if seat_now and seat_now in self.away(campaign_id) and not (turn or {}).get("submitted"):
            self._skip(campaign_id, seat_now)

    def _skip(self, campaign_id: str, seat_id: str) -> None:
        """Пропустить ход героя, чей игрок ушёл. Не сразу: обновить страницу — не повод терять ход."""
        left = self._left_at.get((campaign_id, seat_id))
        wait = self._skip_after.get(campaign_id, SKIP_SEC)
        delay = max(0.0, wait - (time.monotonic() - left)) if left is not None else 0.0

        async def run() -> None:
            await asyncio.sleep(delay)
            if seat_id in self.away(campaign_id):  # advance ещё раз проверит, что ход всё тот же и героя никто не ведёт
                await self.master.advance(campaign_id, "away")

        self._spawn(run())

    async def session_stopped(self, campaign_id: str) -> None:
        """Сессия на паузе или закончена: ждать и голосовать больше не о чем."""
        for key in [k for k in self._grace if k[0] == campaign_id]:
            self._grace.pop(key).cancel()
        for key in [k for k in self._votes if k[0] == campaign_id]:
            await self._finish(self._votes[key], "stopped")
        for key in [k for k in self._away if k[0] == campaign_id]:
            self._away.pop(key)
            self._left_seq.pop(key, None)
            self._left_at.pop(key, None)
            self._covered.discard(key)
            await self._publish_presence(campaign_id, key[1], "offline")
        self._returning = {k for k in self._returning if k[0] != campaign_id}
        for conn in self.hub.connections(campaign_id):
            conn.stand_in = set()

    # --- голосование ---

    async def cast(self, conn: Connection, vote_id: str, option: str) -> str | None:
        """Голос. Возвращает причину отказа или None."""
        vote = next((v for (cid, _), v in self._votes.items() if cid == conn.campaign_id and v.id == vote_id), None)
        if vote is None:
            return "голосование уже закончилось"
        if conn.seat_id not in vote.voters:
            return "в этом голосовании решают игроки, которые были в сети, когда оно началось"
        if option not in {o["id"] for o in vote.options}:
            return "такого варианта нет"
        vote.ballots[conn.seat_id] = option
        await self.bus.publish(vote.campaign_id, envelope("vote.updated", vote.campaign_id, vote.payload()), None)
        counts: dict[str, int] = {}
        for o in vote.ballots.values():
            counts[o] = counts.get(o, 0) + 1
        best, n = max(counts.items(), key=lambda kv: kv[1])
        if n * 2 > len(vote.voters):
            await self._finish(vote, best)
        elif len(vote.ballots) == len(vote.voters):
            await self._finish(vote, "pause")  # все проголосовали, большинства нет: ничья
        return None

    async def _grace_over(self, key: tuple[str, str], wait: float) -> None:
        try:
            await asyncio.sleep(wait)
            self._grace.pop(key, None)
            if key not in self._away:
                return
            self._away[key] = "offline"
            await self._publish_presence(key[0], key[1], "offline")
            await self._start_vote(*key)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("ожидание переподключения в кампании %s", key[0])

    async def _start_vote(self, campaign_id: str, seat_id: str) -> None:
        async with self.maker() as s:
            c = await s.get(Campaign, campaign_id)
            if c is None or await chat.active_session(s, campaign_id) is None:
                return
            seat = next((x for x in c.seats if x.id == seat_id), None)
            if seat is None or seat.occupant_type != "human" or seat.user is None:
                return
            online = self.hub.online_users(campaign_id)
            present = [
                x
                for x in c.seats
                if x.role == "player" and x.occupant_type == "human" and x.id != seat_id and x.user_id in online
            ]
            names = {x.id: x.user.name for x in present}
            if seat.role == "master":
                hero = None
                options = [
                    {"id": "ai_master", "label": "ИИ-мастер подхватывает игру"},
                    {"id": "pause", "label": "Поставить на паузу"},
                ]
            else:
                q = select(Character).where(Character.seat_id == seat_id, Character.status.in_(HERO))
                ch = (await s.scalars(q)).first()
                if ch is None:
                    return  # героя в игре нет: решать нечего
                hero = ch.name
                options = [{"id": f"seat:{x.id}", "label": f"Передать {names[x.id]}"} for x in present]
                options.append({"id": "pause", "label": "Поставить на паузу"})
            who = seat.user.name
            wait = _setting(c, "vote_timeout_sec", VOTE_SEC)
        if not present:
            await self._pause(campaign_id, "Игроков в сети не осталось: сессия на паузе.")
            return
        vote = Vote(
            id="v_" + uuid.uuid4().hex[:12],
            campaign_id=campaign_id,
            seat_id=seat_id,
            subject=seat.role,
            who=who,
            hero=hero,
            options=options,
            voters=[x.id for x in present],
            deadline=time.time() + wait,
        )
        self._votes[(campaign_id, seat_id)] = vote
        vote.task = asyncio.create_task(self._vote_timeout(vote, wait))
        await self.bus.publish(campaign_id, envelope("vote.started", campaign_id, vote.payload()), None)

    async def _vote_timeout(self, vote: Vote, wait: float) -> None:
        try:
            await asyncio.sleep(wait)
            await self._finish(vote, "pause")
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("голосование в кампании %s", vote.campaign_id)

    async def _finish(self, vote: Vote, outcome: str) -> None:
        key = (vote.campaign_id, vote.seat_id)
        if self._votes.get(key) is not vote:
            return
        del self._votes[key]
        if vote.task is not None and vote.task is not asyncio.current_task():
            vote.task.cancel()
        label = next((o["label"] for o in vote.options if o["id"] == outcome), None)
        await self.bus.publish(
            vote.campaign_id,
            envelope("vote.ended", vote.campaign_id, {**vote.payload(), "outcome": outcome, "label": label}),
            None,
        )
        if outcome == "pause":
            await self._pause(vote.campaign_id, f"Голосование: пауза, пока {vote.who} вне сети.")
        elif outcome == "ai_master":
            await self._ai_master(vote.campaign_id, vote.seat_id)
        elif outcome.startswith("seat:"):
            await self._hand_over(vote, outcome.removeprefix("seat:"))

    # --- исходы ---

    async def _pause(self, campaign_id: str, text: str) -> None:
        async with self.maker() as s:
            c = await s.get(Campaign, campaign_id)
            game = await chat.active_session(s, campaign_id) if c is not None else None
            if game is None:
                return
            msg = await chat.close_session(s, c, game, "paused", text)
            await s.commit()
            game_id = game.id
        await publish_message(self.bus, msg)
        await self.bus.publish(campaign_id, envelope("session.paused", campaign_id, {"status": "paused"}), None)
        await self.session_stopped(campaign_id)
        self.master.schedule_session_close(campaign_id, game_id, ended=False)

    async def _hand_over(self, vote: Vote, to_seat: str) -> None:
        async with self.maker() as s:
            c = await s.get(Campaign, vote.campaign_id)
            seat = next((x for x in c.seats if x.id == vote.seat_id), None) if c else None
            to = next((x for x in c.seats if x.id == to_seat), None) if c else None
            if seat is None or to is None or to.user_id is None or await chat.active_session(s, c.id) is None:
                return
            seat.stand_in_user_id = to.user_id
            text = f"Пока {vote.who} вне сети, {vote.hero} ведёт {to.user.name}."
            msg = await chat.system_message(s, c, text, await chat.active_session(s, c.id))
            await s.commit()
            user_id, name = to.user_id, to.user.name
        for conn in self.hub.connections(vote.campaign_id, user_id):
            conn.stand_in.add(vote.seat_id)
        self._covered.add((vote.campaign_id, vote.seat_id))  # героя ведут: мастер его снова ждёт
        await publish_message(self.bus, msg)
        await self._publish_stand_in(vote.campaign_id, vote.seat_id, {"user_id": user_id, "name": name})

    async def _ai_master(self, campaign_id: str, seat_id: str) -> None:
        async with self.maker() as s:
            c = await s.get(Campaign, campaign_id)
            if c is None or await chat.active_session(s, campaign_id) is None:
                return
            seat = master_seat(c)
            if seat.id != seat_id or seat.occupant_type != "human":
                return
            if seat.agent_config_id is None:
                agent = await agent_for_master(s, {})  # профиль модели по умолчанию из админки
                s.add(agent)
                await s.flush()
                seat.agent_config_id = agent.id
            seat.occupant_type, seat.delegated_from = "agent", seat.user_id
            msg = await chat.system_message(
                s, c, "Мастер вне сети: игру подхватывает ИИ-мастер.", await chat.active_session(s, campaign_id)
            )
            await s.commit()
        self._covered.add((campaign_id, seat_id))
        await publish_message(self.bus, msg)
        await self._publish_stand_in(campaign_id, seat_id, {"ai": True, "name": "ИИ-мастер"})
        self.master.notify(campaign_id)  # ответить на реплики, которые ждали живого мастера

    async def _give_back(self, campaign_id: str, seat_id: str) -> None:
        async with self.maker() as s:
            c = await s.get(Campaign, campaign_id)
            seat = next((x for x in c.seats if x.id == seat_id), None) if c else None
            if seat is None or seat.stand_in_user_id is None:
                return
            was = seat.stand_in_user_id
            seat.stand_in_user_id = None
            q = select(Character).where(Character.seat_id == seat_id, Character.status.in_(HERO))
            ch = (await s.scalars(q)).first()
            who = seat.user.name if seat.user else "игрок"
            text = f"{who} вернулся и снова ведёт {ch.name}." if ch else f"{who} вернулся."
            msg = await chat.system_message(s, c, text, await chat.active_session(s, campaign_id))
            await s.commit()
        for conn in self.hub.connections(campaign_id, was):
            conn.stand_in.discard(seat_id)
        await publish_message(self.bus, msg)
        await self._publish_stand_in(campaign_id, seat_id, None)

    async def _catch_up(self, campaign_id: str, seat_id: str, from_seq: int) -> None:
        try:
            await self.master.catch_up(campaign_id, seat_id, from_seq)
        except Exception:  # noqa: BLE001 — без сводки вернувшийся всё равно видит досланные сообщения
            log.exception("сводка пропущенного в кампании %s", campaign_id)

    # --- служебное ---

    async def _current_seat(self, s, campaign_id: str) -> str | None:
        """Место героя, чей сейчас ход в бою, если он ещё не заявил действие."""
        sc = await get_scene(s, campaign_id)
        if sc.mode != "combat" or not sc.turn_order or (sc.state or {}).get("submitted"):
            return None
        entry = sc.turn_order[int((sc.state or {}).get("turn", 0)) % len(sc.turn_order)]
        ch = await s.get(Character, entry["id"])
        return ch.seat_id if ch else None

    async def _publish_presence(self, campaign_id: str, seat_id: str, status: str) -> None:
        try:
            payload = {"seat_id": seat_id, "status": status}
            await self.bus.publish(campaign_id, envelope("presence.changed", campaign_id, payload), None)
        except Exception:  # noqa: BLE001
            log.debug("presence не отправлен", exc_info=True)

    async def _publish_stand_in(self, campaign_id: str, seat_id: str, stand_in: dict | None) -> None:
        payload = {"seat_id": seat_id, "stand_in": stand_in}
        await self.bus.publish(campaign_id, envelope("stand_in.changed", campaign_id, payload), None)

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def stop(self) -> None:
        self._stopping = True
        if self._inflight:
            await asyncio.wait(set(self._inflight), timeout=5)
        votes = [v.task for v in self._votes.values() if v.task]
        tasks = [*self._grace.values(), *votes, *self._tasks, *self._inflight]
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
