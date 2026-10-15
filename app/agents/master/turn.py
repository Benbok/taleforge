"""Ход мастера: сбор пакета, маршрутизация механик, фаза решения, фиксация."""

from __future__ import annotations

import json
import logging

from sqlalchemy import func, select

from app.agents import intent as intents
from app.agents import rhythm, textcalls
from app.agents.llm import LLMError, LLMQuotaError, LLMReply, decide_model_for, model_for, reply_audit_error
from app.agents.master import checkpoint
from app.agents.master.action_order import ready_action_refs
from app.agents.master.action_progress import finalize_action_parts
from app.agents.master.adaptation import adaptation_prompt, public_adaptation_effects
from app.agents.master.common import (
    MAX_CALLS,
    MAX_STEPS,
    ROLL_TOOLS,
    _routable_cast,
    decision_tools,
    declared_cast,
    render,
)
from app.agents.master.creative import creative_context, creative_note
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
from app.agents.master.optimization import optimization_flags
from app.agents.master.resolution import action_context_prompt, capture_attempt, permit_repair, resolution_prompt
from app.agents.master.searches import unresolved_searches
from app.agents.master.tool_profiles import (
    EXPAND_TOOL,
    ExpandDecisionToolsArgs,
    profile_id_context,
    profile_tool_names,
    select_tool_profile,
)
from app.core import adventure, audio, bonds, chat, combat, persona, plot
from app.core.brief import brief_text
from app.core.campaigns import master_seat
from app.core.chat import active_session, next_seq, system_message
from app.core.llm_diagnostics import message_sizes, reply_metrics
from app.core.narrative.view import master_canon_block
from app.core.resolution.contracts import ActionProgress, ActionRef, ResolutionResult, ToolActionBinding
from app.core.scene_context import message_scene_context
from app.core.world_tx import WorldConflict
from app.db.models import AgentConfig, Campaign, CampaignSecret, LlmCall, MasterTurn, Message, Scene, now
from app.gateway.events import envelope, publish_message
from app.tools import fortune as fortune_tools
from app.tools import plot as plot_tools
from app.tools import progress as progress_tools
from app.tools import standing as standing_tools
from app.tools.action_plan import (
    approach_attack,
    approach_cast,
    execute_action_plan,
    hostile_cast_plan,
    hostile_target,
    maneuver_plan,
)
from app.tools.audio import AUDIO_TOOLS
from app.tools.narrative.commitments import reserve_turn_claims
from app.tools.registry import REGISTRY, ToolContext, ToolError, execute, tool_specs
from app.tools.resolution.requests import action_key, bound_tool_key, mark_resolved
from app.tools.runtime import flush_outbox, open_context, publish_changes

log = logging.getLogger(__name__)


def _targets_hostile_with_spell(ctx: ToolContext, args: dict) -> bool:
    """Combat trigger for a damaging/hostile spell with an explicit enemy target."""
    from app.core.spells import spell_catalog

    caster_id = args.get("caster_id")
    spell_id = args.get("spell_id")
    target_ids = args.get("target_ids")
    if not isinstance(caster_id, str) or not isinstance(spell_id, str) or not isinstance(target_ids, list):
        return False
    spell = spell_catalog(ctx.world.catalog).spells.get(spell_id)
    if (
        spell
        and spell.get("on_fail") == ["charmed"]
        and not any(spell.get(key) for key in ("attack", "damage", "auto_hit"))
    ):
        return False  # A charm save alone does not prove the target noticed an attack.
    if (
        caster_id not in ctx.world.characters
        or not spell
        or args.get("ritual")
        or not any(spell.get(k) for k in ("attack", "save", "damage", "auto_hit"))
    ):
        return False
    for target_id in target_ids:
        if not isinstance(target_id, str):
            continue
        target = ctx.world.entities.get(target_id)
        if (
            target is not None
            and target.kind == "creature"
            and not (target.state or {}).get("dead")
            and not (target.state or {}).get("fled")
            and (target.state or {}).get("attitude", "hostile") == "hostile"
            and ctx.world.actor_place(caster_id) == ctx.world.actor_place(target_id)
        ):
            return True
    return False


def _hostile_opening_spell(ctx: ToolContext, intent: dict | None) -> dict | None:
    """Route only a single unequivocal hostile cast; buffs and parley stay free."""
    actions = (intent or {}).get("actions") or []
    if len(actions) != 1 or actions[0].get("verb") != "cast":
        return None
    args = _routable_cast(ctx, intent)
    return args if args and _targets_hostile_with_spell(ctx, args) else None


def _mark_actor_opening(ctx: ToolContext, actor_id: str) -> None:
    for r in ctx.required_actions:
        if r.actor_id == actor_id:
            mark_resolved(ctx, r)
            ctx.action_progress[action_key(r)] = ActionProgress(
                status="completed",
                result=ResolutionResult(execution="applied", game_outcome="success"),
            )
    ctx.closed.add(actor_id)


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
        diagnostics: dict = {}
        replan = False
        committed = False  # действия хода зафиксированы: дальше откатывать нечего (docs/world-objects-delivery2.md)
        await self._status(cid, "listening")
        try:
            for attempt in range(2):
                try:
                    async with self.maker() as s:
                        published = await self._play(s, cid, turn_id, calls, diagnostics)
                    break
                except WorldConflict:
                    if attempt:
                        raise
                    # мир изменился между чтением и первой записью хода: ход целиком переигрывается по свежему миру
                    log.info("ход мастера %s: мир изменился, ход переигрывается", turn_id)
                    diagnostics["world_conflict_retry"] = True
            committed = True
            if published["skipped"]:
                return turn_id
            await self._save_calls(calls)
            told = await self._narrate_turn(cid, turn_id)
            await publish_changes(self.bus, published["ctx"], [*published["messages"], *told], published["names"])
            queued = (published["ctx"].world.scene.state or {}).get("transits") or []
            if queued:  # переходы хода завершились до описания: прежний контекст показал бы героев на старом месте
                from app.core.layout import transit

                heroes = sorted({h for q in queued for h in q["hero_ids"]})
                try:
                    await transit.republish(self.maker, self.dice_factory, self.bus, cid, heroes)
                except Exception:  # noqa: BLE001 — сбой рассылки не прерывает завершение сохранённого хода
                    log.exception("публикация перехода хода %s не удалась", turn_id)
            await self._states(cid, published["ids"], "answered")
            await self.after_turn(published["ctx"])
            replan = "replan" in published["ctx"].signals
            if self.players is not None:
                self.players.reset_round(cid)
            self.schedule_summary(cid)  # сводка обновится, если набралось summary_every сообщений
            self.signal_recovery()
        except Exception as e:  # noqa: BLE001 — сбой хода не должен ронять сервер; ход откатывается целиком
            log.exception("ход мастера %s не удался", turn_id)
            if committed:
                self.signal_recovery()  # действия сохранены: описание допишет восстановитель
            else:
                conflict = isinstance(e, WorldConflict)
                async with self.maker() as s:
                    t = await s.get(MasterTurn, turn_id)
                    t.status, t.finished_at = "failed", now()
                    t.trace = {
                        **(t.trace or {}),
                        **diagnostics,
                        "rolled_back": True,
                        "error": f"{type(e).__name__}: {e}",
                    }
                    c = await s.get(Campaign, cid)
                    text = (
                        "Мастер не смог завершить ход: мир изменился, пока он думал. Ничего не изменилось: "
                        "повторите действие."
                        if conflict
                        else "Мастер не смог завершить ход. Ничего не изменилось: повторите действие."
                    )
                    if isinstance(e, LLMQuotaError):
                        text = (
                            "У мастера исчерпан бюджет модели. Ничего не изменилось. "
                            "Владелец кампании должен проверить лимит расходов проекта у провайдера модели "
                            "и после восстановления бюджета перезапустить сервер."
                            if e.budget_exhausted
                            else "У мастера исчерпана квота запросов модели. Ничего не изменилось. "
                            "Повторите действие через минуту; при повторном отказе владельцу нужно проверить "
                            "квоты проекта у провайдера модели."
                        )
                    msg = await system_message(s, c, text, None)
                    sc = await s.get(Scene, cid)
                    if sc is not None and (sc.state or {}).get("submitted"):
                        sc.state = {**sc.state, "submitted": False}  # заявку можно повторить
                    await s.commit()
                await publish_message(self.bus, msg)
                await self._states(cid, ids, "failed")
        finally:
            await self._status(cid, "idle")
            await self._save_calls(calls)
        if replan:
            self.schedule_replan(cid)  # после учёта вызовов: пересмотр пишет в ту же кампанию
        return turn_id

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
    ) -> LLMReply:
        model = override_model or (decide_model_for() if purpose == "decide" else model_for())
        sizes = message_sizes(messages, tools or [])
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

    async def _play(self, s, cid: str, turn_id: str, calls: list, diagnostics: dict | None = None) -> dict:
        """Фаза действий хода: всё, что меняет мир, одной транзакцией. Повествование — после её коммита
        (``_narrate_turn``), по checkpoint, без повторного вызова инструментов."""
        c = await s.get(Campaign, cid)
        turn = await s.get(MasterTurn, turn_id)
        seat = master_seat(c)
        cfg = await s.get(AgentConfig, seat.agent_config_id)
        place = (turn.trace or {}).get("place")
        ctx = await open_context(s, c, self.dice_factory(), turn_id=turn_id, seat_id=seat.id, focus=place)
        flags = optimization_flags(c.settings or {})
        if diagnostics is not None:
            ctx.turn_diagnostics = diagnostics
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

        from app.tools.resolution.requests import bind_message_actions

        for message in new:
            if message.kind == "action" and message.seat_id in char_by_seat:
                ctx.required_actions.extend(bind_message_actions(message, char_by_seat[message.seat_id].id))

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
        # Ordered, unequivocal move+attack and move+cast actions use Action Plans.
        trace_calls: list[dict] = []
        ctx.turn_diagnostics["calls"] = trace_calls
        routed: list[str] = []
        # заклинания, уже сотворённые сервером по заявке: (герой, заклинание) -> ключ идемпотентности
        routed_casts: dict[tuple[str, str], str] = {}
        opening_actors: set[str] = set()
        opening_notes: list[str] = []
        blocked_actors: set[str] = set()
        if not combat.in_combat(ctx):
            # Start initiative before either the movement or hostile action.
            for m in new:
                if m.kind != "action":
                    continue
                plan = approach_attack(m.intent) or approach_cast(ctx, m.intent) or maneuver_plan(m.intent)
                if plan is None:
                    continue
                spell_plan = plan.get("kind") == "cast"
                actor = plan["caster_id"] if spell_plan else plan["attacker_id"]
                hostile = hostile_cast_plan(ctx, plan) if spell_plan else hostile_target(ctx, plan)
                if (
                    not hostile
                    or actor not in required
                    or m.seat_id not in char_by_seat
                    or char_by_seat[m.seat_id].id != actor
                ):
                    continue
                opened = await execute(ctx, "set_scene_mode", {"mode": "combat"}, key=f"{turn_id}:plan:initiative")
                trace_calls.append({"tool": "set_scene_mode", "result": opened, "automatic": True, "routed": True})
                if opened.get("ok"):
                    combat.queue_opening_plan(ctx, plan)
                    opening_actors.add(actor)
                    _mark_actor_opening(ctx, actor)
                    description = (
                        "Манёвр" if plan.get("kind") in ("shove", "grapple") else "Движение и последующее действие"
                    )
                    routed.append(
                        f"{actor}: {description} сохранён до законного хода по инициативе; не исполняй повторно"
                    )
                    await self._status(cid, "rolling")
                    opening_notes += await combat.run_until_hero(ctx, f"{turn_id}:plan", self._ask_reaction)
                else:
                    routed.append(f"{actor}: начало боя отклонено: {opened.get('error')}")
                break
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
                    _mark_actor_opening(ctx, actor_id)
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
            plan = (approach_attack(m.intent) or approach_cast(ctx, m.intent)) if m.kind == "action" else None
            actor = (plan.get("caster_id") or plan.get("attacker_id")) if plan is not None else None
            valid = plan is not None and (plan.get("kind") == "cast" or hostile_target(ctx, plan))
            if valid and actor in required:
                if combat.in_combat(ctx) and hero_turn is not None and hero_turn.id == actor:
                    await self._status(cid, "rolling")
                    result = await execute_action_plan(ctx, plan, f"{turn_id}:plan:{m.id}")
                    trace_calls.append({"tool": "action_plan", "args": plan, "result": result, "routed": True})
                    routed.append(
                        f"{actor}: составная заявка проверена сервером: {'; '.join(result['notes'])}. "
                        "Не дублируй перемещение или атаку"
                    )
                    _mark_actor_opening(ctx, actor)
                    if not result["completed"]:
                        blocked_actors.add(actor)
                        combat._set(ctx, submitted=False)
                    continue
            name, args = "resolve_attack", intents.routable_attack(m.intent) if m.kind == "action" else None
            if args and any(a.get("verb") in intents.MOVE_VERBS for a in (m.intent or {}).get("actions") or []):
                # Preserve the sequence for the decision model: route must never
                # try the weapon attack before the declared movement.
                args = None
            if args is None and m.kind == "action":
                name, args = "cast_spell", _routable_cast(ctx, m.intent)
                if args and any(a.get("verb") in intents.MOVE_VERBS for a in (m.intent or {}).get("actions") or []):
                    # Never cast first and narrate an imaginary approach afterwards.
                    args = None
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
            m_actions = (m.data or {}).get("resolution_actions") or []
            call_args = dict(args)
            if m_actions:
                target_ref = ActionRef.model_validate(m_actions[0]["ref"])
                if target_ref not in ready_action_refs(ctx):
                    continue
                call_args["action_ref"] = m_actions[0]["ref"]
            await self._status(cid, "rolling")
            call_key = await bound_tool_key(ctx, name, call_args, f"{turn_id}:route:{m.id}")
            r = await execute(ctx, name, call_args, key=call_key)
            if m_actions:
                binding = ctx.current_binding or ToolActionBinding(
                    ref=ActionRef.model_validate(m_actions[0]["ref"]), role="finish"
                )
            else:
                binding = ctx.current_binding or actor
            request_key = await capture_attempt(ctx, binding, r)
            trace_calls.append({"tool": name, "args": args, "result": r, "routed": True, "request_key": request_key})
            if r.get("ok"):
                routed.append(f"{actor}: {name} уже выполнен сервером по намерению")
                if name == "cast_spell":
                    if isinstance(binding, ToolActionBinding):
                        routed_casts[action_key(binding.ref)] = call_key
                    routed_casts[(actor, args["spell_id"])] = call_key
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
                    f"{await resolution_prompt(ctx)}"
                    f"{await action_context_prompt(ctx) if flags['action_refs'] else ''}"
                    f"\n{creative_note(creative_context(ctx))}\n"
                    f"{await adaptation_prompt(ctx)}\n"
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
        search_retry = False
        failed_transition = False
        invalid_source_stop = False
        profile = select_tool_profile(ctx, new) if flags["tool_profiles"] else None
        allowed = profile_tool_names(ctx, profile) if profile else decision_tools(ctx)

        def id_context_note() -> dict:
            return {
                "role": "user",
                "content": "Допустимые id для инструментов (не придумывай):\n"
                + json.dumps(profile_id_context(ctx, allowed), ensure_ascii=False),
            }

        if profile:
            msgs.append(id_context_note())

        async def run_call(name: str, args: dict, key: str) -> dict:
            nonlocal done_calls, allowed, profile
            # A stable profile never grants tools removed by live campaign permissions.
            if profile and name not in set(decision_tools(ctx)) | {EXPAND_TOOL}:
                return {"ok": False, "error": f"инструмент {name} недоступен в этом ходе"}
            if profile and name == EXPAND_TOOL and name in allowed:
                from pydantic import ValidationError

                try:
                    ExpandDecisionToolsArgs.model_validate(args)
                except ValidationError as error:
                    return {"ok": False, "error": str(error)}
                profile = "general"
                allowed = profile_tool_names(ctx, profile)
                return {
                    "ok": True,
                    "result": {"profile": profile, "tools": allowed, "valid_ids": profile_id_context(ctx, allowed)},
                }
            if done_calls >= MAX_CALLS and name != "adapt_story":
                return {"ok": False, "error": f"лимит {MAX_CALLS} вызовов за ход исчерпан: переходи к повествованию"}
            if name not in allowed:
                return {"ok": False, "error": f"инструмент {name} недоступен в этом ходе"}
            if not isinstance(args, dict) or "__invalid_json__" in args:
                return {"ok": False, "error": "аргументы — не JSON-объект"}
            # Validate before special combat routes can queue or mutate anything.
            if REGISTRY[name].mutating and (flags["action_refs"] or args.get("action_ref") is not None):
                from pydantic import ValidationError

                from app.agents.master.action_binding import bind_tool_action

                try:
                    raw_ref = args.get("action_ref")
                    explicit = ActionRef.model_validate(raw_ref) if raw_ref is not None else None
                    await bind_tool_action(ctx, name, args, explicit=explicit)
                except (ToolError, ValidationError) as error:
                    done_calls += 1
                    return {
                        "ok": False,
                        "error": str(error),
                        "failure": {
                            "code": getattr(error, "code", "invalid_source"),
                            "category": getattr(error, "category", "invalid_arguments"),
                        },
                    }
            if name == "cast_spell" and not combat.in_combat(ctx) and args.get("caster_id") in ctx.world.characters:
                spell = ctx.world.catalog.find(str(args.get("spell_id") or ""), "spell_template")
                if not declared_cast(new, char_by_seat, args["caster_id"], spell.name if spell else ""):
                    done_calls += 1
                    return {
                        "ok": False,
                        "error": "игрок этого заклинания в этом ходу не заявлял: не твори его за героя",
                    }
            if name in ("resolve_attack", "resolve_shove", "resolve_grapple"):
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
                        if name in ("resolve_shove", "resolve_grapple"):
                            kind = "shove" if name == "resolve_shove" else "grapple"
                            combat.queue_opening_plan(ctx, {"kind": kind, **args})
                        else:
                            combat.queue_opening_attack(ctx, args)
                        opening_actors.add(attacker)
                        _mark_actor_opening(ctx, attacker)
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
                    if name in ("resolve_shove", "resolve_grapple"):
                        kind = "shove" if name == "resolve_shove" else "grapple"
                        combat.queue_opening_plan(ctx, {"kind": kind, **args})
                    else:
                        combat.queue_opening_attack(ctx, args)
                    opening_actors.add(attacker)
                    _mark_actor_opening(ctx, attacker)
                    await self._status(cid, "rolling")
                    opening_notes.extend(await combat.run_until_hero(ctx, f"{key}:opening", self._ask_reaction))
                    done_calls += 1
                    return {"ok": True, "result": {"mode": "combat", "opening_attack": "queued by initiative"}}
            if name == "cast_spell" and _targets_hostile_with_spell(ctx, args):
                caster = args["caster_id"]
                if combat.in_combat(ctx):
                    from app.core import economy

                    if not economy.active(ctx.world, caster):
                        return {"ok": False, "error": "атакующее заклинание: сейчас ход другого участника"}
                    if combat.state(ctx).get("actor") != caster:
                        if caster in opening_actors:
                            return {"ok": False, "error": "начальное действие уже заявлено"}
                        combat.queue_opening_spell(ctx, args)
                        opening_actors.add(caster)
                        _mark_actor_opening(ctx, caster)
                        done_calls += 1
                        return {"ok": True, "result": {"opening_spell": "queued by initiative"}}
                elif caster in required:
                    opened = await execute(ctx, "set_scene_mode", {"mode": "combat"}, key=f"{key}:initiative")
                    trace_calls.append({"tool": "set_scene_mode", "result": opened, "automatic": True})
                    if not opened.get("ok"):
                        return opened
                    combat.queue_opening_spell(ctx, args)
                    opening_actors.add(caster)
                    _mark_actor_opening(ctx, caster)
                    await self._status(cid, "rolling")
                    opening_notes.extend(await combat.run_until_hero(ctx, f"{key}:opening", self._ask_reaction))
                    done_calls += 1
                    return {"ok": True, "result": {"mode": "combat", "opening_spell": "queued by initiative"}}
            if name in ROLL_TOOLS:
                await self._status(cid, "rolling")
            ctx.remaining_resolution_calls = MAX_CALLS - done_calls
            ctx.resolution_calls_used = 0
            repair_target = (
                ActionRef.model_validate(args["action_ref"])
                if REGISTRY[name].mutating and isinstance(args.get("action_ref"), dict)
                else (args.get("character_id") or args.get("attacker_id") or args.get("caster_id"))
            )
            if (
                name != "adjudicate_action"
                and REGISTRY[name].mutating
                and REGISTRY[name].closes_actions
                and not await permit_repair(ctx, repair_target)
            ):
                done_calls += 1
                return {
                    "ok": False,
                    "error": "Лимит исправления аргументов этой заявки исчерпан; действие не выполнено.",
                }
            key = await bound_tool_key(ctx, name, args, key)
            if name == "cast_spell":
                # повтор заклинания, уже сотворённого по заявке, — прежний результат без второй ячейки
                raw_ref = args.get("action_ref")
                action_ref = (
                    ActionRef.model_validate(raw_ref)
                    if isinstance(raw_ref, dict)
                    else (raw_ref if isinstance(raw_ref, ActionRef) else None)
                )
                if action_ref:
                    key = routed_casts.get(action_key(action_ref), key)
                else:
                    key = routed_casts.get((args.get("caster_id"), args.get("spell_id")), key)
            result = await execute(ctx, name, args, key=key)
            if name == "adjudicate_action" and result.get("ok"):
                result = {**result, "request_key": action_key(ActionRef.model_validate(args["proposal"]["ref"]))}
            if (
                name != "adjudicate_action"
                and REGISTRY[name].mutating
                and REGISTRY[name].closes_actions
                and (result.get("failure") or {}).get("code") != "invalid_source"
            ):
                actor = args.get("character_id") or args.get("attacker_id") or args.get("caster_id")
                binding = ctx.current_binding or actor
                request_key = await capture_attempt(ctx, binding, result)
                if request_key:
                    result = {**result, "request_key": request_key}
            if name not in AUDIO_TOOLS and name != "adapt_story":  # адаптация имеет собственный бюджет
                done_calls += max(1, ctx.resolution_calls_used) if name == "adjudicate_action" else 1
            return result

        for _ in range(MAX_STEPS):
            specs = tool_specs(ctx.world, allowed, dynamic_ids=not flags["tool_profiles"])
            reply = await self._ask(calls, cfg, cid, seat.id, turn_id, "decide", msgs, specs)
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
                failed_spawns = [
                    t
                    for t in trace_calls
                    if t["tool"] == "spawn_entity" and not t["result"].get("ok") and not t["result"].get("skipped")
                ]
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
                open_ = (required - ctx.closed) - opening_actors
                searches = unresolved_searches(ctx)
                if searches and not search_retry and done_calls < MAX_CALLS:
                    search_retry = True
                    search_names = [s.actor_id if isinstance(s, ActionRef) else str(s) for s in searches]
                    msgs.append(
                        {
                            "role": "user",
                            "content": (
                                "Результат исследования не закреплён после успешной проверки: "
                                + ", ".join(search_names)
                                + ". До повествования запиши конкретный результат через learn_fact, "
                                "reveal_knowledge или place_item в месте героя с discovery_check_event_id "
                                "(event_id успешной проверки из её ответа). Если ничего ценного нет, "
                                "запиши конкретный факт о проверенной области. Не описывай несуществующие находки."
                            ),
                        }
                    )
                    continue
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
            failed_in_batch = False
            invalid_source_in_batch = False
            for call in reply.tool_calls:
                args = call.arguments
                if invalid_source_in_batch:
                    result = {"ok": False, "skipped": True, "error": "не выполнено после неверной ссылки на заявку"}
                elif failed_in_batch:
                    result = {
                        "ok": False,
                        "skipped": True,
                        "error": "не выполнено после ошибки перехода; исправь переход",
                    }
                elif (
                    failed_transition
                    and call.name == "spawn_entity"
                    and isinstance(args, dict)
                    and not args.get("location_id")
                ):
                    result = {
                        "ok": False,
                        "error": "предыдущий переход отклонён; укажи фактический location_id или исправь переход",
                    }
                else:
                    result = await run_call(call.name, args, f"{turn_id}:{call.id}")
                trace_calls.append(
                    {
                        "tool": call.name,
                        "args": args,
                        "result": result,
                        "request_key": result.get("request_key"),
                        "call_key": f"{turn_id}:{call.id}",
                    }
                )
                msgs.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.id,
                        "content": json.dumps(result, ensure_ascii=False, default=str),
                    }
                )
                if flags["action_refs"] and (result.get("failure") or {}).get("code") == "invalid_source":
                    invalid_source_in_batch = True
                    if ctx.turn_diagnostics.get("invalid_source_repairs", 0) >= 1:
                        invalid_source_stop = True
                    else:
                        ctx.turn_diagnostics["invalid_source_repairs"] = 1
                if call.name in ("move", "enter_room"):
                    if result.get("ok"):
                        failed_transition = False
                    else:
                        failed_transition = True
                        failed_in_batch = True
            if invalid_source_stop:
                ctx.turn_diagnostics["decision_stop_reason"] = "invalid_source"
                break
            if invalid_source_in_batch:
                msgs.append(
                    {
                        "role": "user",
                        "content": (
                            "Ссылка на заявку неверна. Ничего по ней не выполнено. Исправь её один раз, "
                            "используя точный action_ref ниже; не придумывай source_id."
                            + await action_context_prompt(ctx)
                        ),
                    }
                )
            admission_note = (await resolution_prompt(ctx)) + (await adaptation_prompt(ctx))
            if flags["action_refs"]:
                admission_note += await action_context_prompt(ctx)
            if admission_note:
                msgs.append({"role": "user", "content": admission_note})
            if failed_in_batch:
                msgs.append(
                    {
                        "role": "user",
                        "content": (
                            "Переход НЕ выполнен. Остальные вызовы в этом ответе пропущены, "
                            "а герои остались на фактическом месте из таблицы сцены. "
                            "Проверь доступные комнаты, затем повтори корректный переход. "
                            "Только после успешного перехода создавай находящихся там противников."
                        ),
                    }
                )
            if (
                done_calls >= MAX_CALLS
                and trace_calls[-1]["tool"] != "adapt_story"
                and all(not t["result"].get("ok") for t in trace_calls[-1:])
            ):
                break

        if getattr(ctx, "required_actions", None):
            await finalize_action_parts(ctx)

        searches = unresolved_searches(ctx)
        if searches:
            diagnostics["unresolved_searches"] = [
                sr.model_dump() if isinstance(sr, ActionRef) else sr for sr in searches
            ]
            for search_ref in searches:
                actor = search_ref.actor_id if isinstance(search_ref, ActionRef) else search_ref
                cancel_args = {"character_id": actor, "reason": "Результат исследования ещё не подтверждён миром."}
                if isinstance(search_ref, ActionRef):
                    cancel_args["action_ref"] = search_ref.model_dump()
                result = await execute(
                    ctx,
                    "cancel_action",
                    cancel_args,
                    key=f"{turn_id}:unresolved_search:{actor}:{getattr(search_ref, 'part', 0)}",
                )
                trace_calls.append({"tool": "cancel_action", "auto": True, "result": result})

        # Контракт намерения: молчание запрещено — код сам фиксирует отказ (раздел 7.1)
        if getattr(ctx, "required_actions", None):
            for ref in ctx.required_actions:
                prog = ctx.action_progress.get(action_key(ref))
                if not prog or prog.status not in {"completed", "denied", "blocked"}:
                    r = await execute(
                        ctx,
                        "cancel_action",
                        {
                            "character_id": ref.actor_id,
                            "reason": (
                                "Действие не выполнено: не удалось сопоставить ответ мастера с заявкой."
                                if invalid_source_stop
                                else "мастер не обработал действие"
                            ),
                            "action_ref": ref.model_dump(),
                        },
                        key=f"{turn_id}:auto_cancel:{ref.actor_id}:{ref.source_id}:{ref.part}",
                    )
                    trace_calls.append({"tool": "cancel_action", "auto": True, "result": r})
        else:
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
                and hero_turn.id not in blocked_actors
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
        mood_note = await self._mood(s, calls, cfg, c, seat.id, turn_id, ctx, new, char_by_seat)

        whispers = await flush_outbox(s, ctx)  # карточки бросков и шёпоты встают в чат раньше повествования
        heard = _heard_by(ctx, crew)  # отряд разделён: ответ и броски видят герои этой группы
        for m in whispers:
            if m.kind == "roll" and heard is not None:
                m.visible_to = heard
        # строка повествования резервируется один раз на ход; пока текста нет, её не видит никто
        scene_context = await message_scene_context(s, c, place)
        msg = Message(
            campaign_id=cid,
            session_id=ctx.game_session_id,
            seq=await next_seq(s, cid),
            seat_id=seat.id,
            kind="narration",
            visible_to=[],
            content="",
            data={
                "pending": True,
                "scene_context": scene_context,
                "scope": "party" if heard is not None else "public",
                **({"place": place} if place is not None else {}),
            },
        )
        s.add(msg)
        await s.flush()
        turn.trace = {
            **(turn.trace or {}),
            **{
                key: ctx.turn_diagnostics[key]
                for key in ("invalid_source_repairs", "decision_stop_reason")
                if key in ctx.turn_diagnostics
            },
            "calls": trace_calls,
            "text_call_rejections": written_rounds,
            "required": sorted(required),
            "closed": sorted(ctx.closed),
            "combat": combat_notes,
            "plot_clock": plot_notes,
            "world": world_note,
            "stalled": bool(stall),
            **(
                {"unresolved_searches": [s.model_dump() if isinstance(s, ActionRef) else s for s in searches]}
                if searches
                else {}
            ),
        }
        adapt_effects = public_adaptation_effects(ctx, tuple(heard or ()))
        listeners = None if heard is None else tuple(h.id for h in ctx.world.characters.values() if h.seat_id in heard)
        claims = await reserve_turn_claims(ctx, listeners)  # закрепление коммитится ниже, до LLM повествования
        try:
            from app.core.narrative.contracts import EvidenceRecord, EvidenceRef, NarrativePolicy, TurnBoundaryState
            from app.core.narrative.triggers import derive_boundaries, enqueue_boundaries
            from app.db.narrative import ensure_state

            ev_recs = [
                EvidenceRecord(
                    ref=EvidenceRef(campaign_id=cid, kind="event", source_id=ev.id),
                    status="applied",
                    subject_refs=(ev.actor_id,) if ev.actor_id else (),
                    audience=tuple(heard or ()),
                    game_time=getattr(ev, "game_time", 0) or 0,
                    applied_result=ev.tool,
                )
                for ev in ctx.events
            ]
            game_session = locals().get("game")
            t_bound = TurnBoundaryState(
                id=turn_id,
                phase="turn",
                session_id=getattr(game_session, "id", None) if game_session else None,
                focus=place,
                audience=tuple(heard or ()),
                external_boundary=False,
            )
            n_st = await ensure_state(s, cid)
            pol = NarrativePolicy(mode=n_st.mode, version=n_st.policy_version)
            bounds = derive_boundaries(tuple(ev_recs), t_bound, pol)
            if bounds:
                await enqueue_boundaries(ctx, bounds)
        except Exception:
            log.exception("ошибка вычисления границ адаптации хода %s", turn_id)

        turn.generation_checkpoint = checkpoint.effects_committed(
            events=[ev.id for ev in ctx.events],
            operation_refs=sorted(ctx.operation_refs),
            crew=sorted(crew),
            narration_message_id=msg.id,
            audience=heard,
            place=place,
            inputs={
                "convo": convo,
                "news": news,
                "mood": mood_note,
                "combat_notes": combat_notes,
                "plot_notes": plot_notes,
                "party_notes": party_notes,
                "stalled": bool(stall),
                "meet": meet,
                "adaptation_notes": [e.description for e in adapt_effects] + claims,
            },
            adaptation_effects=[e.model_dump() for e in adapt_effects],
        )
        await s.commit()
        return {"ctx": ctx, "messages": whispers, "names": names, "ids": [m.id for m in new], "skipped": False}

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
        if canon := master_canon_block(ctx.world):
            secrets = (secrets + "\n\n" if secrets else "") + canon
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
            audio=audio.prompt_block(c, ctx.world.scene, audio.where(ctx), ctx.saved_sfx),
        )
