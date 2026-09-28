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
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jinja2
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents.llm import LLM, LLMError, LLMReply, model_for
from app.core.campaigns import master_seat
from app.core.chat import active_session, next_seq, system_message
from app.db.models import (
    AgentConfig,
    Campaign,
    CampaignSecret,
    Character,
    LlmCall,
    MasterTurn,
    Message,
    User,
    as_utc,
    now,
)
from app.gateway.events import envelope, publish_message
from app.rules.dice import Dice
from app.tools.registry import REGISTRY, ToolContext, execute, tool_specs
from app.tools.runtime import flush_outbox, open_context, publish_changes

log = logging.getLogger(__name__)

MAX_CALLS = 8  # вызовов инструментов за ход (раздел 7)
MAX_STEPS = 12  # обращений к модели в фазе решения
HISTORY = 20  # последних сообщений в контексте (раздел 9)
PLAYER_KINDS = ("action", "speech", "whisper")
ROLL_TOOLS = ("roll_check", "resolve_attack", "death_save", "apply_hazard", "set_scene_mode", "rest", "use_item")
MARKUP = re.compile(r"\[\[([^|\]]+)\|([^\]]+)\]\]")
DECISION_TOOLS = [n for n in REGISTRY if n != "review_character"]

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(Path(__file__).parent / "prompts"),
    autoescape=False,
    keep_trailing_newline=False,
)


def render(name: str, **kw: Any) -> str:
    return _env.get_template(name).render(**kw).strip()


class MasterService:
    """Очередь ходов ИИ-мастера по кампаниям. Один ход кампании за раз; реплики, пришедшие во время хода,
    уходят в следующий пакет."""

    def __init__(self, sessionmaker: async_sessionmaker, bus, llm: LLM, dice_factory=Dice):
        self.maker = sessionmaker
        self.bus = bus
        self.llm = llm
        self.dice_factory = dice_factory
        self._tasks: dict[str, asyncio.Task] = {}
        self._pending: set[str] = set()
        self._locks: dict[str, asyncio.Lock] = {}
        self._background: set[asyncio.Task] = set()

    # --- очередь ---

    def notify(self, campaign_id: str) -> None:
        """Пришла реплика игрока: запустить сбор пакета или отметить, что после текущего хода нужен ещё один."""
        task = self._tasks.get(campaign_id)
        if task is not None and not task.done():
            self._pending.add(campaign_id)
            return
        self._tasks[campaign_id] = asyncio.create_task(self._loop(campaign_id))

    def schedule_review(self, campaign_id: str, character_id: str) -> None:
        t = asyncio.create_task(self.review_character(campaign_id, character_id))
        self._background.add(t)
        t.add_done_callback(self._background.discard)

    async def wait_idle(self, campaign_id: str | None = None) -> None:
        while self._background:
            await asyncio.wait(set(self._background))
        while (t := self._tasks.get(campaign_id)) is not None and not t.done():
            await asyncio.wait({t})

    async def stop(self) -> None:
        tasks = [*self._tasks.values(), *self._background]
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
            players = {
                ch.seat_id
                for ch in await s.scalars(
                    select(Character).where(Character.campaign_id == cid, Character.status.in_(("approved", "active")))
                )
                if ch.seat_id
            }
            wrote = {m.seat_id for m in new}
            if players and players <= wrote:
                return 0
            window = float((c.settings or {}).get("collect_window_sec", 60))
            waited = (datetime.now(UTC) - as_utc(new[0].created_at)).total_seconds()
            return max(0.0, window - waited)

    # --- ход ---

    async def _status(self, cid: str, stage: str) -> None:
        await self.bus.publish(cid, envelope("master.status", cid, {"stage": stage}), None)

    async def run_turn(self, cid: str) -> str | None:
        lock = self._locks.setdefault(cid, asyncio.Lock())
        async with lock:
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
                    return None
            turn = MasterTurn(campaign_id=cid, session_id=game.id, upto_seq=new[-1].seq, trace={"from_seq": new[0].seq})
            s.add(turn)
            await s.commit()
            turn_id = turn.id

        calls: list[LlmCall] = []
        await self._status(cid, "listening")
        try:
            async with self.maker() as s:
                published = await self._play(s, cid, turn_id, calls)
            await publish_changes(self.bus, published["ctx"], published["messages"], published["names"])
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
                await s.commit()
            await publish_message(self.bus, msg)
        finally:
            await self._status(cid, "idle")
            if calls:
                async with self.maker() as s:
                    s.add_all(calls)
                    await s.commit()
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
                max_tokens=4096 if tools else 2048,
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
        history = await _history(s, c, new[0].seq if new else turn.upto_seq + 1)
        names = await _names(s, c)
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

        await self._status(cid, "remembering")
        msgs: list[dict] = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"Недавние сообщения чата:\n{convo or 'пока нет'}\n\nТаблица сцены:\n{ctx.world.scene_table()}\n\n"
                    f"Новые реплики игроков:\n{news}\n\nФаза решения: вызови нужные инструменты. "
                    "Когда все действия закрыты, ответь одним словом «готово» без вызовов."
                ),
            },
        ]
        trace_calls: list[dict] = []
        done_calls = retries = 0
        for _ in range(MAX_STEPS):
            reply = await self._ask(
                calls, cfg, cid, seat.id, turn_id, "decide", msgs, tool_specs(ctx.world, DECISION_TOOLS)
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

        await self._status(cid, "describing")
        narration, audit = await self._narrate(calls, cfg, c, seat.id, turn_id, system, convo, news, ctx)

        whispers = await flush_outbox(s, ctx)
        msg = Message(
            campaign_id=cid,
            session_id=ctx.game_session_id,
            seq=await next_seq(s, cid),
            seat_id=seat.id,
            kind="narration",
            content=narration,
        )
        s.add(msg)
        await s.flush()
        turn.status, turn.finished_at, turn.narration_message_id = "done", now(), msg.id
        turn.trace = {"calls": trace_calls, "audit": audit, "required": sorted(required), "closed": sorted(ctx.closed)}
        await s.commit()
        return {"ctx": ctx, "messages": [*whispers, msg], "names": names}

    async def _narrate(self, calls, cfg, c, seat_id, turn_id, system, convo, news, ctx: ToolContext):
        results = _render_results(ctx)
        prompt = render(
            "narrate.j2", results=results, scene=ctx.world.scene_table(), length="от одного до четырёх абзацев"
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

        text = MARKUP.sub(strip, text)
        return text or "…", audit

    async def _system_prompt(self, s, c: Campaign, cfg: AgentConfig, ctx: ToolContext) -> str:
        secret = await s.get(CampaignSecret, c.id)
        secrets = ""
        if secret and (secret.setting or secret.plot):
            secrets = json.dumps({"setting": secret.setting, "plot": secret.plot}, ensure_ascii=False)[:12000]
        dc = ", ".join(f"{e.id} = {e.data['value']} ({e.name})" for e in ctx.world.catalog.dc_scale())
        return render(
            "master_system.j2",
            campaign_name=c.name,
            style=cfg.persona,
            excluded_themes=", ".join((c.settings or {}).get("excluded_themes") or []),
            public_intro=c.public_intro,
            secrets=secrets,
            dc_scale=dc,
            max_calls=MAX_CALLS,
        )

    # --- проверка персонажа ИИ-мастером (раздел 5.1) ---

    async def review_character(self, cid: str, character_id: str) -> str | None:
        lock = self._locks.setdefault(cid, asyncio.Lock())
        async with lock:
            calls: list[LlmCall] = []
            try:
                async with self.maker() as s:
                    c = await s.get(Campaign, cid)
                    seat = master_seat(c)
                    if seat.occupant_type != "agent":
                        return None
                    cfg = await s.get(AgentConfig, seat.agent_config_id)
                    ctx = await open_context(s, c, self.dice_factory(), turn_id=None, seat_id=seat.id)
                    ch = ctx.world.characters.get(character_id)
                    if ch is None or ch.status != "submitted":
                        return None
                    from app.core.characters import full_view

                    sheet = full_view(ch, ctx.world.catalog, ctx.world.inventory.get(ch.id, []), [])
                    system = await self._system_prompt(s, c, cfg, ctx)
                    msgs = [
                        {"role": "system", "content": system},
                        {
                            "role": "user",
                            "content": (
                                "Игрок прислал персонажа на проверку. Правила сервер уже проверил. Оцени историю и "
                                "соответствие сеттингу и вызови review_character: одобри или верни с комментарием. "
                                "Можешь тайно связать историю героя с сюжетом через secret_link.\n\n"
                                + json.dumps(sheet, ensure_ascii=False, default=str)
                            ),
                        },
                    ]
                    status = None
                    for _ in range(3):
                        reply = await self._ask(
                            calls, cfg, cid, seat.id, None, "review", msgs, tool_specs(ctx.world, ["review_character"])
                        )
                        msgs.append(reply.message or {"role": "assistant", "content": reply.text})
                        if not reply.tool_calls:
                            msgs.append({"role": "user", "content": "Вызови review_character."})
                            continue
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
                        if status:
                            break
                    await s.commit()
                    if status and ch.seat_id:
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
                    return status
            finally:
                if calls:
                    async with self.maker() as s:
                        s.add_all(calls)
                        await s.commit()


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
        .where(Message.campaign_id == c.id, Message.seq < before_seq, Message.kind != "ooc")
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
        if m.kind in ("narration",):
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
    return "\n".join(out)


def _render_results(ctx: ToolContext) -> str:
    out = []
    for ev in ctx.events:
        res = ev.payload.get("result", ev.payload)
        mark = " [СКРЫТЫЙ БРОСОК: игрокам только последствия]" if ev.hidden else ""
        out.append(f"- {ev.tool}{mark}: {json.dumps(res, ensure_ascii=False, default=str)}")
    return "\n".join(out)
