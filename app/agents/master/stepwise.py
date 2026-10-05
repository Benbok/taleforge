"""Пошаговый режим (разделы 5, 7.2): чей ход, таймер хода, ходы существ, реакции."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid

from sqlalchemy import func, select

from app.agents import character
from app.agents.master.helpers import _heard_by, _names
from app.core import combat
from app.core.campaigns import master_seat
from app.core.chat import active_session, next_seq
from app.db.models import AgentConfig, Campaign, Character, LlmCall, MasterTurn, Message, Scene, now
from app.gateway.events import envelope
from app.tools.registry import ToolContext
from app.tools.runtime import flush_outbox, open_context, publish_changes

log = logging.getLogger(__name__)


class StepwiseMixin:
    """Часть MasterService (app/agents/master/service.py)."""

    # --- пошаговый режим: ход, таймаут, реакции (раздел 5, 7.2) ---

    async def after_turn(self, ctx: ToolContext) -> None:
        """После фиксации хода: всем — чей ход, и таймер хода героя; эскизы мест по новым описаниям."""
        cid = ctx.campaign.id
        self.schedule_sketches(ctx)
        turn = combat.public_turn(ctx.world)
        for seats, view in combat.turn_views(ctx.world):  # отряд разделён: ход видят только те, у кого бой
            await self.bus.publish(cid, envelope("turn.changed", cid, {"turn": view}), seats)
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
        lock = self.turn_lock(cid)
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
                    # отряд разделён: ходы боя видят только те, кто в нём (и мастер)
                    places = combat.fronts(ctx.world)
                    crew = {h.id for p, hs in ctx.world.groups().items() if p in places for h in hs}
                    everyone = {h.id for hs in ctx.world.groups().values() for h in hs}
                    if ctx.world.split and crew != everyone:  # раунды боя идут по часам тех, кто сражается
                        ctx.world.crew = crew
                    t0 = ctx.world.enter_clock()
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
                    ctx.world.settle_clock(t0)
                    names = await _names(s, c)
                    messages = await flush_outbox(s, ctx)
                    heard = _heard_by(ctx, crew) if ctx.world.split and crew else None
                    for m in messages:
                        if m.kind == "roll" and heard is not None:
                            m.visible_to = heard
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
                            visible_to=heard,
                            data={"place": next(iter(places))} if heard is not None and len(places) == 1 else None,
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
