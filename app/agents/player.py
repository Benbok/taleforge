"""ИИ-игроки (ТЗ, раздел 5.2; этап 9).

Агент на месте игрока играет своего героя, как человек. Он знает только лист героя, его характер, публичную сводку,
сцену и сообщения, видимые этому месту. Шёпотов других игроков и тайн мастера он не видит. Инструментов у него нет:
он пишет обычную реплику, и она проходит тот же парсер, те же проверки хода и ту же запись в чат.

Когда агент говорит:
- вне боя — один раз после повествования мастера, если в этом ходе мастеру писал живой игрок (иначе агенты и
  мастер разговаривали бы друг с другом без конца);
- в бою — в ход своего героя; если модель не ответила или реплику не приняли, ход пропускается;
- кнопку реакции решает сам: атака по возможности, кроме героя, которого ИИ ведёт за ушедшего игрока (осторожно).

Героя ушедшего игрока ИИ ведёт с пометкой «играть осторожно, не принимать необратимых решений» (раздел 11).
"""

from __future__ import annotations

import asyncio
import logging
import re

from sqlalchemy import select

from app.agents import memory
from app.agents.llm import LLMError, model_for
from app.core import chat, combat, persona
from app.core.campaigns import Viewer
from app.core.world import get_scene
from app.db.models import AgentConfig, Campaign, Character, Entity, InventoryItem, LlmCall, Message, Seat, User
from app.gateway.events import publish_message

log = logging.getLogger(__name__)

HISTORY = 15  # последних видимых сообщений в контексте агента
MARKUP = re.compile(r"\[\[([^|\]]+)\|([^\]]+)\]\]")
SILENT = "—"

SYSTEM = (
    "Ты — игрок за столом текстовой ролевой игры по правилам D&D 5e и отыгрываешь одного героя. "
    "Пиши по-русски, от лица героя, 1–3 предложения: что герой делает и, если нужно, что говорит (прямая речь "
    "в кавычках). Результат действия не описывай: успех, урон и последствия решает мастер. Не управляй другими "
    "героями и NPC, не придумывай предметы и способности, которых нет в листе. Держись характера героя. "
    "Если герою сейчас нечего сказать или сделать, ответь одним символом «—»."
)
CAUTIOUS = (
    "Ты ведёшь этого героя временно, пока его игрок вне сети. Играй осторожно: не принимай необратимых решений, "
    "не трать редкие ресурсы, не меняй отношения героя с другими, держись отряда."
)


def is_agent_player(seat: Seat | None) -> bool:
    return seat is not None and seat.role == "player" and seat.occupant_type == "agent"


def cautious(seat: Seat) -> bool:
    """Герой ушедшего игрока, которого ИИ ведёт по итогам голосования."""
    return bool(seat.delegated_from)


class PlayerAgents:
    def __init__(self, master) -> None:
        self.master = master
        self._busy: set[tuple[str, str]] = set()
        self._tasks: set[asyncio.Task] = set()

    # --- когда говорить ---

    def after_narration(self, cid: str) -> None:
        """Мастер ответил живому игроку: каждый ИИ-игрок может откликнуться одной репликой."""
        self._spawn(self._answer_all(cid))

    async def _answer_all(self, cid: str) -> None:
        async with self.master.maker() as s:
            c = await s.get(Campaign, cid)
            sc = await get_scene(s, cid) if c is not None else None
            if c is None or sc.mode == "combat":
                return  # в бою агент ходит только в свой ход
            seats = [x.id for x in c.seats if is_agent_player(x)]
        for seat_id in seats:  # по очереди: следующий видит реплику предыдущего
            await self.speak(cid, seat_id, combat_turn=False)

    def combat_turn(self, cid: str, seat_id: str) -> None:
        self._spawn(self.speak(cid, seat_id, combat_turn=True))

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._tasks.add(t)
        t.add_done_callback(self._tasks.discard)

    async def wait_idle(self) -> None:
        while self._tasks:
            await asyncio.wait(set(self._tasks))

    async def stop(self) -> None:
        for t in list(self._tasks):
            t.cancel()
        for t in list(self._tasks):
            try:
                await t
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

    # --- реплика ---

    async def speak(self, cid: str, seat_id: str, *, combat_turn: bool) -> str | None:
        """Одна реплика агента. Возвращает id сообщения или None, если агент промолчал или реплику не приняли."""
        key = (cid, seat_id)
        if key in self._busy:
            return None
        self._busy.add(key)
        try:
            prompt = await self._prompt(cid, seat_id, combat_turn)
            if prompt is None:
                return None
            system, user, cfg_model, api_base, careful = prompt
            text = await self._ask(cid, seat_id, system, user, cfg_model, api_base)
            msg_id = await self._post(cid, seat_id, text) if text else None
            if msg_id is None and combat_turn and await self._still_agent(cid, seat_id):
                await self.master.advance(cid, "pass", seat_id=seat_id)  # вернувшийся игрок ходит сам
            return msg_id
        except Exception:  # noqa: BLE001 — ИИ-игрок не должен ронять игру
            log.exception("ИИ-игрок %s в кампании %s", seat_id, cid)
            return None
        finally:
            self._busy.discard(key)

    async def _still_agent(self, cid: str, seat_id: str) -> bool:
        async with self.master.maker() as s:
            c = await s.get(Campaign, cid)
            return c is not None and is_agent_player(next((x for x in c.seats if x.id == seat_id), None))

    async def _prompt(self, cid: str, seat_id: str, combat_turn: bool):
        from app.content.catalog import campaign_catalog
        from app.tools.runtime import public_entity

        async with self.master.maker() as s:
            c = await s.get(Campaign, cid)
            if c is None or await chat.active_session(s, cid) is None:
                return None
            seat = next((x for x in c.seats if x.id == seat_id), None)
            if not is_agent_player(seat) or seat.agent_config_id is None:
                return None
            sc = await get_scene(s, cid)
            if (sc.mode == "combat") != combat_turn:
                return None  # бой начался или кончился, пока агент ждал очереди
            q = select(Character).where(Character.seat_id == seat_id, Character.status.in_(("approved", "active")))
            ch = (await s.scalars(q)).first()
            if ch is None or (ch.resources or {}).get("hp", 1) <= 0:
                return None  # героя нет или он без сознания: говорить некому
            cfg = await s.get(AgentConfig, seat.agent_config_id)
            cat = await campaign_catalog(s, c)
            inv = (await s.scalars(select(InventoryItem).where(InventoryItem.character_id == ch.id))).all()
            from app.core.characters import full_view

            sheet = full_view(ch, cat, list(inv), [])
            last = await memory.latest(s, cid)
            q = select(Message).where(Message.campaign_id == cid).order_by(Message.seq.desc()).limit(HISTORY * 3)
            rows = [m for m in (await s.scalars(q)).all() if chat.visible(m, seat_id) and m.kind != "ooc"]
            rows = list(reversed(rows[:HISTORY]))
            chars = {
                x.seat_id: x.name for x in (await s.scalars(select(Character).where(Character.campaign_id == cid)))
            }
            ents = (await s.scalars(select(Entity).where(Entity.campaign_id == cid))).all()
            here = [
                public_entity(e)["name"]
                for e in ents
                if e.kind != "location" and (sc.location_id is None or e.location_id == sc.location_id)
            ]
            place = next((e.name for e in ents if e.id == sc.location_id), None)
            careful = cautious(seat)
            user_text = _render(ch, sheet, last, rows, chars, place, here, combat_turn)
            character = persona.render(ch.persona, await persona.notes_of(s, cid, ch.id))
            system = SYSTEM + ("\n\nХарактер твоего героя:\n" + character if character else "")
            system += "\n\n" + CAUTIOUS if careful else ""
            model = model_for(cfg.provider, cfg.model)
            api_base = (cfg.settings or {}).get("api_base")
        return system, user_text, model, api_base, careful

    async def _ask(self, cid: str, seat_id: str, system: str, user: str, model: str, api_base) -> str | None:
        call = LlmCall(campaign_id=cid, seat_id=seat_id, turn_id=None, purpose="player", model=model)
        text = None
        try:
            reply = await self.master.llm.complete(
                [{"role": "system", "content": system}, {"role": "user", "content": user}],
                model=model,
                max_tokens=400,
                temperature=0.9,
                api_base=api_base,
            )
            call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
            call.cost, call.latency_ms = reply.cost, reply.latency_ms
            text = MARKUP.sub(r"\2", reply.text or "").strip().strip("«»").strip()
            if text in ("", SILENT, "-", "–"):
                text = None
        except LLMError as e:
            call.error = str(e)[:2000]
        async with self.master.maker() as s:
            s.add(call)
            await s.commit()
        return text[:1000] if text else None

    async def _post(self, cid: str, seat_id: str, text: str) -> str | None:
        """Реплика идёт тем же путём, что у человека: парсер намерений, проверка хода, запись в чат."""
        parsed = await self.master.parse_intent(cid, seat_id, text)
        if parsed.reject:
            log.info("реплику ИИ-игрока %s не приняли: %s", seat_id, parsed.reject)
            return None
        async with self.master.maker() as s:
            c = await s.get(Campaign, cid)
            seat = next((x for x in c.seats if x.id == seat_id), None)
            if not is_agent_player(seat):
                return None
            owner = await s.get(User, c.owner_id)
            viewer = Viewer(owner, c, seat)
            kind = parsed.kind or "action"
            reason = await combat.gate_message(s, viewer, kind)
            if reason:
                await s.rollback()
                log.info("реплика ИИ-игрока %s не прошла: %s", seat_id, reason)
                return None
            m = await chat.post_message(s, viewer, kind, text, 1000)
            m.author_user_id = None  # автор — ИИ, не владелец
            m.data = {"ai": True}
            if parsed.intent and m.kind == "action":
                m.intent = parsed.intent
            await s.commit()
            names = {x.user_id: x.user.name for x in c.seats if x.user is not None}
            state = (await chat.message_states(s, c, [m])).get(m.id)
        await publish_message(self.master.bus, m, names, state)
        if m.kind in ("action", "speech", "whisper"):
            self.master.notify(cid)
        return m.id


def _render(ch, sheet, last, rows, chars, place, here, combat_turn: bool) -> str:
    p = ch.personality or {}
    traits = "\n".join(f"- {k}: {v}" for k, v in p.items() if v and isinstance(v, str | int | float))
    inv = ", ".join(i.get("name", "") for i in sheet.get("inventory") or [] if isinstance(i, dict)) or "—"
    derived = sheet.get("derived") or {}
    res = ch.resources or {}
    lines = [
        f"Твой герой: {ch.name}. Класс: {sheet.get('class_name') or (ch.sheet or {}).get('class_id')}, "
        f"уровень {(ch.sheet or {}).get('level', 1)}. Хиты {res.get('hp', '?')} из {derived.get('hp_max', '?')}.",
        f"Снаряжение: {inv}.",
    ]
    if ch.public_bio:
        lines.append(f"Внешность и история: {ch.public_bio}")
    if ch.private_backstory:
        lines.append(f"Что знает только герой: {ch.private_backstory}")
    if traits:
        lines.append("Характер:\n" + traits)
    if last is not None and last.content.get("recap"):
        lines.append("Ранее в кампании: " + last.content["recap"])
    lines.append(f"Где вы: {place or 'не названо'}. Рядом: {', '.join(here) or 'никого'}.")
    lines.append("Последнее за столом:")
    for m in rows:
        who = "Мастер" if m.kind == "narration" else chars.get(m.seat_id) or ("Система" if m.kind == "system" else "?")
        lines.append(who + ": " + MARKUP.sub(r"\2", m.content))
    lines.append(
        "Сейчас бой, и это ход твоего героя: заяви одно действие на ход."
        if combat_turn
        else "Мастер только что ответил. Что делает или говорит твой герой?"
    )
    return "\n".join(lines)
