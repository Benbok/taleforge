"""Ход мастера: сбор пакета, маршрутизация механик, фаза решения, фиксация."""

from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy import func, select

from app.agents import intent as intents
from app.agents import rhythm, textcalls
from app.agents.llm import LLMError, LLMReply, decide_model_for, model_for
from app.agents.master.common import MAX_CALLS, MAX_STEPS, ROLL_TOOLS, _routable_cast, decision_tools, render
from app.agents.master.helpers import (
    _batches,
    _heard_by,
    _history,
    _names,
    _party_change,
    _render_history,
    _render_new,
    _turn_messages,
    _unsettled_fails,
)
from app.core import adventure, audio, bonds, chat, combat, persona, plot
from app.core.brief import brief_text
from app.core.campaigns import master_seat
from app.core.chat import active_session, next_seq, system_message
from app.core.linker import link_text
from app.db.models import AgentConfig, Campaign, CampaignSecret, LlmCall, MasterTurn, Message, Scene, now
from app.gateway.events import Stream, envelope, publish_message
from app.tools import fortune as fortune_tools
from app.tools import plot as plot_tools
from app.tools import progress as progress_tools
from app.tools import standing as standing_tools
from app.tools.audio import AUDIO_TOOLS
from app.tools.registry import ToolContext, execute, tool_specs
from app.tools.runtime import flush_outbox, open_context, publish_changes

log = logging.getLogger(__name__)


def _hostile_opening_spell(ctx: ToolContext, intent: dict | None) -> dict | None:
    """An unambiguous offensive spell against a living hostile at the caster's place.

    A self-buff (including Shillelagh), healing, ritual or non-hostile spell
    never starts combat automatically. Leave unclear spells to the GM.
    """
    from app.core.spells import spell_catalog

    actions = (intent or {}).get("actions") or []
    if len(actions) != 1 or actions[0].get("verb") != "cast":
        return None
    args = _routable_cast(ctx, intent)
    if not args or args.get("ritual"):
        return None
    spell = spell_catalog(ctx.world.catalog).spells.get(args["spell_id"])
    if not spell or not any(spell.get(k) for k in ("attack", "save", "damage", "auto_hit")):
        return None
    caster_id = args["caster_id"]
    if caster_id not in ctx.world.characters:
        return None
    for target_id in args.get("target_ids") or []:
        target = ctx.world.entities.get(target_id)
        if (
            target is not None
            and target.kind == "creature"
            and not (target.state or {}).get("dead")
            and not (target.state or {}).get("fled")
            and (target.state or {}).get("attitude", "hostile") == "hostile"
            and ctx.world.actor_place(caster_id) == ctx.world.actor_place(target_id)
        ):
            return args
    return None


class TurnMixin:
    """Часть MasterService (app/agents/master/service.py)."""

    # --- ход ---

    async def _status(self, cid: str, stage: str) -> None:
        # ход группы разделившегося отряда: «мастер думает» видят только её игроки
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

    async def _run_turn(self, cid: str, place: str | None = None) -> str | None:
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
            batches, groups = await _batches(s, c)
            if not batches:
                return None
            if place not in batches:
                place = min(batches, key=lambda p: batches[p][0].seq)  # группа самой ранней реплики
            new = batches[place]
            if place is not None:
                self._audience[cid] = chat.audience(c, groups.get(place, []))
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
                    await s.flush()
                    for m in new:
                        m.turn_id = turn.id
                    await s.commit()
                    await publish_message(self.bus, msg)
                    await self._states(cid, [m.id for m in new], "failed")
                    return None
            turn = MasterTurn(
                campaign_id=cid,
                session_id=game.id,
                upto_seq=new[-1].seq,
                trace={"from_seq": new[0].seq, **({"place": place} if place is not None else {})},
            )
            s.add(turn)
            await s.flush()
            for m in new:
                m.turn_id = turn.id  # реплика взята: её больше не отменить и не взять другим ходом
            await s.commit()
            turn_id = turn.id
            ids = [m.id for m in new]

        await self._states(cid, ids, "processing")
        await self.introduce(cid)  # новичок за столом: мастер сначала представляет его
        calls: list[LlmCall] = []
        drafts: list[str] = []  # черновики повествования, которые игроки видели по кускам
        replan = False
        await self._status(cid, "listening")
        try:
            async with self.maker() as s:
                published = await self._play(s, cid, turn_id, calls, drafts)
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
            for draft in drafts:  # ход откатился: недописанный текст мастера убираем из чата
                await self.bus.publish(cid, envelope("message.withdrawn", cid, {"id": draft}), None)
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
        override_model: str | None = None,
        stream_callback=None,
    ) -> LLMReply:
        model = override_model or (decide_model_for() if purpose == "decide" else model_for())
        try:
            reply = await self.llm.complete(
                messages,
                model=model,
                tools=tools,
                stream_callback=stream_callback,
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

    async def _play(self, s, cid: str, turn_id: str, calls: list, drafts: list[str] | None = None) -> dict:
        c = await s.get(Campaign, cid)
        turn = await s.get(MasterTurn, turn_id)
        seat = master_seat(c)
        cfg = await s.get(AgentConfig, seat.agent_config_id)
        place = (turn.trace or {}).get("place")
        ctx = await open_context(s, c, self.dice_factory(), turn_id=turn_id, seat_id=seat.id, focus=place)
        new = await _turn_messages(s, c, turn_id)
        names = await _names(s, c)
        if not new:  # все реплики пакета отменены, пока ход начинался: модель не зовём
            turn.status, turn.finished_at = "skipped", now()
            await s.commit()
            return {"ctx": ctx, "messages": [], "names": names, "ids": [], "skipped": True}
        t0 = ctx.world.enter_clock()  # отряд разделён: ход идёт по часам этой группы
        before = {p: [h.id for h in hs] for p, hs in ctx.world.groups().items()}  # как стоял отряд до хода
        crew = ctx.world.crew or {h for hs in before.values() for h in hs}
        seats = {ch.seat_id for ch in ctx.world.characters.values() if ch.id in crew and ch.seat_id}
        history = await _history(s, c, new[0].seq, seats if place is not None else None)
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
        # A declared hostile weapon strike or offensive spell begins initiative
        # before damage, saving the original action for its caster's legal turn.
        # Compound actions remain with the master until the Action Plan phase.
        trace_calls: list[dict] = []
        routed: list[str] = []
        opening_actors: set[str] = set()
        opening_notes: list[str] = []
        if not combat.in_combat(ctx):
            for m in new:
                attack = intents.routable_attack(m.intent) if m.kind == "action" else None
                spell = _hostile_opening_spell(ctx, m.intent) if m.kind == "action" else None
                actions = (m.intent or {}).get("actions") or []
                actor_id = attack["attacker_id"] if attack else spell["caster_id"] if spell else None
                if (
                    actor_id is None
                    or len(actions) != 1
                    or actor_id not in required
                    or m.seat_id not in char_by_seat
                    or char_by_seat[m.seat_id].id != actor_id
                ):
                    continue
                if attack is not None:
                    enemy = ctx.world.entities.get(attack["target_id"])
                    if (
                        enemy is None
                        or enemy.kind != "creature"
                        or (enemy.state or {}).get("dead")
                        or (enemy.state or {}).get("attitude", "hostile") != "hostile"
                        or ctx.world.actor_place(actor_id) != ctx.world.actor_place(enemy.id)
                    ):
                        continue
                opened = await execute(ctx, "set_scene_mode", {"mode": "combat"}, key=f"{turn_id}:opening:initiative")
                trace_calls.append({"tool": "set_scene_mode", "result": opened, "automatic": True, "routed": True})
                if opened.get("ok"):
                    if attack is not None:
                        combat.queue_opening_attack(ctx, attack)
                    else:
                        combat.queue_opening_spell(ctx, spell)
                    opening_actors.add(actor_id)
                    ctx.closed.add(actor_id)
                    action_name = "атака" if attack is not None else "заклинание"
                    routed.append(
                        f"{actor_id}: запуск инициативы уже выполнен сервером; {action_name} заявлено "
                        "и будет проведено в собственный ход героя (или уже проведено)"
                    )
                    await self._status(cid, "rolling")
                    opening_notes += await combat.run_until_hero(ctx, f"{turn_id}:opening", self._ask_reaction)
                else:
                    routed.append(f"{actor_id}: начать бой не удалось: {opened.get('error')}")
                break
        fighting = combat.in_combat(ctx) and ctx.world.fighting_here()  # бой другой группы этот ход не ведёт
        hero_turn = combat.current_character(ctx) if fighting else None  # в бою: чей ход закрывает ответ мастера
        combat_note = ""
        if hero_turn is not None:
            combat_note = (
                f"\n\nИдёт бой, раунд {ctx.world.scene.round}. Сейчас ход {hero_turn.name} ({hero_turn.id}): "
                "обработай только его действие. Ходы существ сервер проведёт сам после твоего ответа по их "
                "профилю поведения — не атакуй за существ и не меняй очередь."
            )

        # Маршрутизатор механик (раздел 7): однозначную атаку оружием сервер проводит сам, модель её только опишет
        for m in new:
            if m.seat_id in char_by_seat and char_by_seat[m.seat_id].id in opening_actors:
                continue
            name, args = "resolve_attack", intents.routable_attack(m.intent) if m.kind == "action" else None
            if args and any(a.get("verb") in intents.MOVE_VERBS for a in (m.intent or {}).get("actions") or []):
                # Preserve the sequence for the decision model: route must never
                # try the weapon attack before the declared movement.
                args = None
            if args is None and m.kind == "action":
                name, args = "cast_spell", _routable_cast(ctx, m.intent)
            if args is None and m.kind == "action":
                routed_call = intents.routable_tool_call(m.intent)
                if routed_call:
                    name, args = routed_call
            actor = (
                (args or {}).get("attacker_id")
                or (args or {}).get("caster_id")
                or (args or {}).get("character_id")
                or ((args or {}).get("character_ids") or [None])[0]
            )
            if not args or actor not in required:
                continue
            if combat.in_combat(ctx) and (hero_turn is None or actor != hero_turn.id):
                continue
            await self._status(cid, "rolling")
            r = await execute(ctx, name, args, key=f"{turn_id}:route:{m.id}")
            trace_calls.append({"tool": name, "args": args, "result": r, "routed": True})
            if r.get("ok"):
                routed.append(f"{actor}: {name} уже выполнен сервером по намерению")
            else:
                routed.append(f"{actor}: {name} отклонён сервером: {r.get('error')} — объясни игроку в повествовании")
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
        done_calls = retries = written_rounds = 0
        nudged = False
        spawn_retry = False
        allowed = decision_tools(ctx)

        async def run_call(name: str, args: dict, key: str) -> dict:
            nonlocal done_calls
            if done_calls >= MAX_CALLS:
                return {"ok": False, "error": f"лимит {MAX_CALLS} вызовов за ход исчерпан: переходи к повествованию"}
            if name not in allowed:
                return {"ok": False, "error": f"инструмент {name} недоступен в этом ходе"}
            if not isinstance(args, dict) or "__invalid_json__" in args:
                return {"ok": False, "error": "аргументы — не JSON-объект"}
            if name == "resolve_attack":
                attacker = (args or {}).get("attacker_id")
                target = ctx.world.entities.get((args or {}).get("target_id"))
                if attacker in ctx.world.characters and combat.in_combat(ctx):
                    from app.core import economy

                    if not economy.active(ctx.world, attacker):
                        return {"ok": False, "error": "атака невозможна: сейчас ход другого участника"}
                    if combat.state(ctx).get("actor") != attacker:
                        # Initiative has been rolled, but the first turn has not
                        # been initialized. Do not spend an untracked free attack.
                        if attacker in opening_actors:
                            return {"ok": False, "error": "начальная атака уже заявлена"}
                        combat.queue_opening_attack(ctx, args)
                        opening_actors.add(attacker)
                        ctx.closed.add(attacker)
                        done_calls += 1
                        return {"ok": True, "result": {"opening_attack": "queued by initiative"}}
                # The model may initiate an attack that was not recognized by the
                # intent router. Initiate initiative instead of permitting a free hit.
                if (
                    not combat.in_combat(ctx)
                    and attacker in required
                    and target is not None
                    and target.kind == "creature"
                    and not (target.state or {}).get("dead")
                    and (target.state or {}).get("attitude", "hostile") == "hostile"
                    and ctx.world.actor_place(attacker) == ctx.world.actor_place(target.id)
                ):
                    opened = await execute(ctx, "set_scene_mode", {"mode": "combat"}, key=f"{key}:initiative")
                    trace_calls.append({"tool": "set_scene_mode", "result": opened, "automatic": True})
                    if not opened.get("ok"):
                        return opened
                    combat.queue_opening_attack(ctx, args)
                    opening_actors.add(attacker)
                    ctx.closed.add(attacker)
                    await self._status(cid, "rolling")
                    opening_notes.extend(await combat.run_until_hero(ctx, f"{key}:opening", self._ask_reaction))
                    done_calls += 1
                    return {"ok": True, "result": {"mode": "combat", "opening_attack": "queued by initiative"}}
            if name in ROLL_TOOLS:
                await self._status(cid, "rolling")
            result = await execute(ctx, name, args, key=key)
            if name not in AUDIO_TOOLS:  # звук не отнимает вызовы у механики
                done_calls += 1
            return result

        for _ in range(MAX_STEPS):
            reply = await self._ask(calls, cfg, cid, seat.id, turn_id, "decide", msgs, tool_specs(ctx.world, allowed))
            msgs.append(reply.message or {"role": "assistant", "content": reply.text})
            # Текстовые имитации вызовов нельзя исполнять: только native tool_calls проходят
            # через серверный диспетчер. Даём модели шанс исправить формат ответа.
            if not reply.tool_calls and textcalls.contains(reply.text, allowed):
                written_rounds += 1
                if written_rounds <= 2:
                    msgs.append(
                        {
                            "role": "user",
                            "content": (
                                "Ты написал вызовы инструментов обычным текстом. Сервер НЕ выполнил эти команды. "
                                "Повтори необходимые действия настоящими tool_calls (function calling), "
                                "передавая параметры через аргументы инструмента. Текстовые команды запрещены. "
                                "После выполнения всех действий ответь «готово»."
                            ),
                        }
                    )
                    continue
                # Никаких изменений от текстовых вызовов. Незакрытые действия будут отменены ниже.
                break
            if not reply.tool_calls:
                # Отказ spawn_entity не должен незаметно перейти в повествование
                # о несуществующих врагах (например, из-за бюджета встречи).
                failed_spawns = [t for t in trace_calls if t["tool"] == "spawn_entity" and not t["result"].get("ok")]
                if failed_spawns and not spawn_retry:
                    spawn_retry = True
                    issues = "; ".join(str(t["result"].get("error") or "вызов отклонён") for t in failed_spawns)
                    msgs.append(
                        {
                            "role": "user",
                            "content": (
                                f"Существа НЕ появились: spawn_entity отклонён ({issues[:800]}). "
                                "Если их появление необходимо, повтори вызов с допустимым количеством или "
                                "подходящим более слабым шаблоном. Если нельзя — не утверждай, что они "
                                "присутствуют, видят героев или атакуют. Выполняй только реальные tool_calls."
                            ),
                        }
                    )
                    continue
                open_ = required - ctx.closed
                fails = _unsettled_fails(ctx, trace_calls)
                if fails and not nudged:
                    nudged = True  # критический провал словами не закрыть: последствие пишется в лист героя
                    msgs.append(
                        {
                            "role": "user",
                            "content": (
                                "Критический провал без последствия в листе героя: "
                                + ", ".join(f"{i} ({ctx.world.characters[i].name})" for i in fails)
                                + ". Закрепи его инструментом на этом герое (apply_effect с состоянием из шаблонов и "
                                "длительностью, drop_item, apply_hazard или reposition), потом ответь «готово»."
                            ),
                        }
                    )
                    continue
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
                result = await run_call(call.name, call.arguments, f"{turn_id}:{call.id}")
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

        combat_notes: list[str] = list(opening_notes)
        # An AI-initiated set_scene_mode can occur AFTER the initial fighting snapshot.
        # Always bootstrap the live queue; only finish a previously active hero turn.
        if combat.in_combat(ctx) and ctx.world.fighting_here():
            acted = (
                fighting
                and hero_turn is not None
                and hero_turn.id not in opening_actors
                and any(m.kind == "action" and m.seat_id == hero_turn.seat_id for m in new)
            )
            if acted and combat.current_id(ctx) == hero_turn.id:
                await combat.finish_turn(ctx, combat_notes)
            await self._status(cid, "rolling")
            combat_notes += await combat.run_until_hero(ctx, f"{turn_id}:combat", self._ask_reaction)

        ctx.world.settle_clock(t0)  # часы кампании — наибольшие из часов групп
        plot_notes = await plot_tools.run_clock(ctx)  # злодеи не ждут: шаги угрозы по игровым дням

        party_notes, meet = await _party_change(s, ctx, before, crew, names)
        audio.regroup(ctx)  # сошлись — общий звук места встречи
        audio.autopilot(ctx)  # мастер забыл про звук: мелодия под место или бой
        await self._status(cid, "describing")
        system += await self._mood(s, calls, cfg, c, seat.id, turn_id, ctx, new, char_by_seat)

        # реплика для озвучки и синтез идут параллельно с повествованием, а не перед ним
        voice_task = None
        if self._tts_ready(c):
            voice_task = asyncio.create_task(
                self._voice(calls, cfg, c, seat.id, turn_id, system, ctx, combat_notes, news=news)
            )

        whispers = await flush_outbox(s, ctx)  # карточки бросков и шёпоты встают в чат раньше повествования
        heard = _heard_by(ctx, crew)  # отряд разделён: ответ и броски видят герои этой группы
        for m in whispers:
            if m.kind == "roll" and heard is not None:
                m.visible_to = heard
        msg = Message(
            campaign_id=cid,
            session_id=ctx.game_session_id,
            seq=await next_seq(s, cid),
            seat_id=seat.id,
            kind="narration",
            visible_to=heard,
            content="",
            data={"place": place} if heard is not None and place is not None else None,
        )
        s.add(msg)
        await s.flush()
        # черновик: игроки видят текст по кускам, а само сообщение уходит в чат только после коммита хода
        stream = Stream(self.bus, cid, msg, to=heard)
        if drafts is not None:
            drafts.append(msg.id)

        try:
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
                stream=stream,
                stalled=bool(stall),
                meet=meet,
            )
        except BaseException:
            if voice_task is not None:
                voice_task.cancel()
            raise
        voice_line_text, voice_data = await voice_task if voice_task is not None else (None, None)
        if voice_data:
            msg.data = {**(msg.data or {}), "voice": {**voice_data, "text": voice_line_text}}

        msg.content = await link_text(s, cid, narration)
        party_msgs = [await system_message(s, c, text, None) for text in party_notes]
        turn.status, turn.finished_at, turn.narration_message_id = "done", now(), msg.id
        turn.trace = {
            "calls": trace_calls,
            "text_call_rejections": written_rounds,
            "audit": audit,
            "voice_line": voice_line_text,
            "required": sorted(required),
            "closed": sorted(ctx.closed),
            "combat": combat_notes,
            "plot_clock": plot_notes,
            "world": world_note,
            "stalled": bool(stall),
        }
        await s.commit()
        return {
            "ctx": ctx,
            "messages": [*whispers, msg, *party_msgs],
            "names": names,
            "ids": [m.id for m in new],
            "skipped": False,
        }

    async def _system_prompt(self, s, c: Campaign, cfg: AgentConfig, ctx: ToolContext) -> str:
        secret = await s.get(CampaignSecret, c.id)
        secrets = ""
        has_plot = bool(secret and plot.has_plan(secret.plot))
        if has_plot:
            # «Сюжет сейчас» — текущий акт и что рядом; весь каркас мастер читает через get_plot
            extra = json.dumps(secret.setting, ensure_ascii=False)[:4000] if secret.setting else ""
            home = ctx.world.entities.get(ctx.world.home() or "")
            if adventure.room_of(home) is not None:  # комната готового приключения: место каркаса — место модуля
                home = ctx.world.entities.get(home.location_id or "")
            now_ = plot.now_block(secret.plot, location_entity_id=home.id if home else None)
            secrets = (now_ + ("\n" + extra if extra else ""))[:16000]
            book = adventure.master_block(ctx.world)
            if book:
                secrets += "\n\nПо книге:\n" + book[:12000]
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
            difficulty=c.difficulty,
            leveling=progress_tools.leveling(c),
            random_events=fortune_tools.random_events(c),
            critical_checks=(c.settings or {}).get("critical_checks", True) is not False,
            audio=audio.prompt_block(c, ctx.world.scene, audio.where(ctx)),
        )
