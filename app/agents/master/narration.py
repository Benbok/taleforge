"""Повествование, настроение мастера и озвучка хода."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.agents import textcalls, voicing
from app.agents.llm import LLMError, model_for, parser_model_for
from app.agents.master.action_progress import public_action_notice
from app.agents.master.common import MARKUP, render
from app.agents.master.continuity import invented_player_dialogue, unregistered_named_actors
from app.agents.master.helpers import _check_only, _narration_length, _render_results
from app.agents.master.outcomes import (
    acted,
    cancelled_actions,
    failed_attack,
    failed_item_action,
    public_attempts,
    public_factual_fallback,
    transition_outcome,
)
from app.core import combat
from app.core.linker import BARE, effect_names
from app.db.models import AgentConfig, Campaign, Scene
from app.emotion import game as mood
from app.emotion.analyzers import LLMAnalyzer
from app.emotion.schemas import PlayerActionContext
from app.tools.registry import ToolContext
from app.tools.resolution.requests import action_key

log = logging.getLogger(__name__)


class NarrationMixin:
    """Часть MasterService (app/agents/master/service.py)."""

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
        adaptation_notes=(),
        stream=None,
        *,
        stalled: bool = False,
        meet: str = "",
        tool_attempts: list[dict] | None = None,
        mood_note: str = "",
    ):
        from app.agents.master.optimization import optimization_flags
        from app.agents.master.prompt_context import build_prompt_bundle, narration_scene

        compact = optimization_flags(getattr(c, "settings", None) or {})["role_context"]
        outcome = transition_outcome(tool_attempts)
        attack_rejected = failed_attack(tool_attempts)
        item_rejected = failed_item_action(ctx, tool_attempts)
        attempts = public_attempts(tool_attempts)
        cancellations = cancelled_actions(ctx)
        results = _render_results(ctx, public_only=compact)
        turn = combat.public_turn(ctx.world)
        prompt = render(
            "narrate.j2",
            results=results,
            tool_attempts=attempts,
            cancelled_actions=cancellations,
            failed_transition=outcome == "failed",
            scene=narration_scene(ctx) if compact else ctx.world.scene_table(),
            length=_narration_length(ctx, notes),
            check_only=_check_only(ctx, notes),
            combat_notes=list(notes),
            plot_notes=[] if compact else list(plot_notes),
            adaptation_notes=list(adaptation_notes),
            next_turn=turn["name"] if turn else None,
            stalled=stalled,
        )
        base = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Недавние сообщения чата:\n{convo or 'пока нет'}\n\n"
                f"Реплики игроков этого хода:\n{news}\n\n{prompt}" + (f"\n\n{meet}" if meet else ""),
            },
        ]
        prompt_metadata = None
        if compact:
            bundle = await build_prompt_bundle(
                ctx,
                cfg,
                role="narrate",
                inputs={
                    "request": base[1]["content"],
                    "mood": mood_note,
                    "legacy_messages": base,
                },
            )
            base = bundle.messages
            prompt_metadata = bundle.metadata("narrate")
        ask_options = {"prompt_metadata": prompt_metadata} if prompt_metadata else {}
        known = set(ctx.world.characters) | set(ctx.world.entities)
        inventory_names = {
            item.id: ctx.world.item_name(item)
            for items in getattr(ctx.world, "inventory", {}).values()
            for item in items
        }
        known.update(inventory_names)
        rules = effect_names(ctx.world.catalog)
        known.update(rules)
        human_seats = {seat.id for seat in c.seats if seat.occupant_type != "agent"}
        players = {cid: ch.name for cid, ch in ctx.world.characters.items() if ch.seat_id in human_seats}
        participants = {cid: ch.name for cid, ch in ctx.world.characters.items()}
        participants.update({e.id: e.name for e in ctx.world.in_scene_entities()})
        audit: dict[str, Any] = {"regenerated": False, "stripped": []}
        if outcome is not None:
            audit["transition_outcome"] = outcome
        has_resolution = any(ev.tool == "resolve_action" for ev in ctx.events)
        can_stream = (
            stream is not None
            and outcome != "failed"
            and not attack_rejected
            and not has_resolution
            and not cancellations
            and not item_rejected
        )
        # Scene and player ownership checks require the whole response. Publish
        # the checked draft only; a rejected first attempt must never reach chat.
        reply = await self._ask(
            calls, cfg, c.id, seat_id, turn_id, "narrate", base, None, **ask_options
        )
        text = reply.text.strip()
        if not text:
            audit["regenerated"] = True
            audit["empty_retry"] = True
            retry = [
                *base,
                {
                    "role": "user",
                    "content": "Ответ пуст. Опиши подтверждённые результаты этого хода словами. Не выводи многоточие.",
                },
            ]
            reply = await self._ask(
                calls, cfg, c.id, seat_id, turn_id, "narrate", retry, None, **ask_options
            )
            text = reply.text.strip()
        rejected_names: set[str] = set()
        excluded_fallback_names: set[str] = set()
        known_names = {ch.name.casefold() for ch in ctx.world.characters.values()}
        known_names.update(e.name.casefold() for e in ctx.world.entities.values())
        known_names.update(name.casefold() for name in rules.values())
        known_names.update(name.casefold() for name in inventory_names.values())

        def unknown_refs(draft: str) -> list[str]:
            refs = set()
            for m in MARKUP.finditer(textcalls.clean(draft)):
                if m.group(1) not in known:
                    refs.add(m.group(1))
                    if m.group(2).casefold() not in known_names:
                        rejected_names.add(m.group(2))
            return sorted(refs)

        unknown = unknown_refs(text)
        # Bare entity markup also needs a name already present in the registry.
        unnamed = sorted(
            {
                m.group(1).strip()
                for m in BARE.finditer(textcalls.clean(text))
                if m.group(1).strip().casefold() not in known_names
            }
        )
        # Псевдовызовы инструментов сначала очищает существующий textcalls-аудитор.
        # Имена внутри их JSON-аргументов не являются художественным повествованием.
        has_tool_text = textcalls.contains(text, textcalls.tool_names())
        unregistered = [] if has_tool_text else unregistered_named_actors(text, ctx.world)
        player_dialogue = invented_player_dialogue(textcalls.clean(text), players, participants, news)
        if unknown or unregistered or player_dialogue or unnamed:
            audit["regenerated"] = True
            if unknown:
                audit["unknown_first"] = unknown
            if unnamed:
                audit["unregistered_names"] = unnamed
            if unregistered:
                audit["unregistered_actors"] = unregistered
            if player_dialogue:
                audit["player_dialogue"] = player_dialogue
            problems = []
            if unknown:
                problems.append(f"неизвестные id: {', '.join(unknown)}")
            if unnamed:
                problems.append(f"разметка без id, таких мест и сущностей нет в реестре: {', '.join(unnamed)}")
            if unregistered:
                problems.append(f"не зарегистрированы в текущей сцене: {', '.join(unregistered)}")
            if player_dialogue:
                problems.append(
                    "придуманы реплики персонажей игроков: " + ", ".join(players[cid] for cid in player_dialogue)
                )
            retry = [
                *base,
                {"role": "assistant", "content": text},
                {
                    "role": "user",
                    "content": (
                        f"Нарушена достоверность сцены ({'; '.join(problems)}). Перепиши ответ: "
                        "возможны только участники и события, подтверждённые текущей таблицей сцены "
                        "и успешными вызовами инструментов. Не описывай незарегистрированных врагов как "
                        "видимых или приближающихся. Не отвечай за персонажей игроков: их реплики берутся "
                        "только из сообщений соответствующего игрока этого хода. Если вопрос обращён к "
                        "другому герою, оставь ответ его игроку. Если действие игрока не выполнено, объясни причину."
                        " Окружение без записи в реестре описывай без разметки [[...]], не добавляя новых участников."
                    ),
                },
            ]
            # Rejected drafts stay private while the narrator rewrites them.
            reply = await self._ask(
                calls, cfg, c.id, seat_id, turn_id, "narrate", retry, None, **ask_options
            )
            text = reply.text.strip()

        blocked_refs = unknown_refs(text)

        def strip(m: re.Match) -> str:
            if m.group(1) in inventory_names:
                # Inventory rows have no entity.inspect card. Preserve the
                # item name without publishing a link the client cannot open.
                return m.group(2)
            if m.group(1) in known:
                return m.group(0)
            audit["stripped"].append(m.group(1))
            return m.group(2)

        text = MARKUP.sub(strip, text)
        # Ни markdown-псевдовызовы, ни обычные текстовые команды нельзя публиковать
        # или превращать в действия мира. Повторно запрашиваем прозу, если ответа не осталось.
        tools = textcalls.tool_names()
        if textcalls.contains(text, tools):
            audit["tool_text"] = [name for name, _ in textcalls.parse(text, tools)] or ["incomplete"]
            text = textcalls.clean(text)
            if not text:
                audit["regenerated"] = True
                retry = [
                    *base,
                    {
                        "role": "user",
                        "content": (
                            "Вместо повествования ты вывел текстовые команды инструментов. Они НЕ были выполнены. "
                            "Напиши только художественное описание уже произошедших событий по фактическим "
                            "результатам инструментов и таблице сцены; не выдумывай исполнение команд."
                        ),
                    },
                ]
                reply = await self._ask(
                    calls, cfg, c.id, seat_id, turn_id, "narrate", retry, None, **ask_options
                )
                blocked_refs = unknown_refs(reply.text)
                text = MARKUP.sub(strip, reply.text.strip())
                if textcalls.contains(text, tools):
                    audit["tool_text_retry"] = True
                    text = textcalls.clean(text)
        # Очистка от случайных вызовов инструментов в тексте мастера (например, set_music {...})
        text = re.sub(r"^\s*[a-z_]+\s*\{.*?\}\s*", "", text, flags=re.DOTALL).strip()
        # Очистка от оборванного незакрытого тега разметки в конце текста
        text = re.sub(r"\[\[[^\]]*$", "", text).rstrip()
        # Последний барьер: повторная галлюцинация не превращается в факт игрового мира.
        blocked_names = sorted(
            name for name in rejected_names if re.search(r"(?<!\w)" + re.escape(name) + r"(?!\w)", text, re.IGNORECASE)
        )
        excluded_fallback_names.update(blocked_names)
        unregistered = unregistered_named_actors(text, ctx.world)
        if unregistered:
            audit["blocked_actors"] = unregistered
            excluded_fallback_names.update(unregistered)
            text = public_factual_fallback(
                ctx,
                tool_attempts,
                notice="Появление новых участников не подтверждено текущей сценой.",
                excluded_names=unregistered,
            )
        if blocked_refs or blocked_names:
            if blocked_refs:
                audit["blocked_refs"] = blocked_refs
            if blocked_names:
                audit["blocked_names"] = blocked_names
            text = public_factual_fallback(
                ctx,
                tool_attempts,
                notice="Описание встречи не подтверждено текущей сценой.",
                excluded_names=blocked_names,
            )
        bare_names = sorted(
            {m.group(1).strip() for m in BARE.finditer(text) if m.group(1).strip().casefold() not in known_names}
        )
        if bare_names:
            audit["blocked_bare_names"] = bare_names
            excluded_fallback_names.update(bare_names)
            text = public_factual_fallback(ctx, tool_attempts, excluded_names=bare_names)
        blocked_dialogue = invented_player_dialogue(text, players, participants, news)
        if blocked_dialogue:
            audit["blocked_player_dialogue"] = blocked_dialogue
            text = public_factual_fallback(
                ctx,
                tool_attempts,
                notice="Ответ персонажа игрока ещё не получен. Его реплику должен написать сам игрок.",
            )
        if outcome == "failed":
            # После окончательного отказа нельзя публиковать свободную прозу модели:
            # она может утверждать об успешном входе, несмотря на явный запрет.
            # Используем факты из движка, не историю диалога и не секретные ToolError.
            audit["transition_fallback"] = True
            text = public_factual_fallback(ctx, tool_attempts, excluded_names=excluded_fallback_names)
        elif attack_rejected:
            audit["attack_fallback"] = True
            text = public_factual_fallback(ctx, tool_attempts, excluded_names=excluded_fallback_names)
        if item_rejected:
            audit["item_fallback"] = True
            text = public_factual_fallback(
                ctx,
                tool_attempts,
                notice=(
                    "Часть действий с предметами не выполнена; передача и употребление "
                    "не подтверждены, если они не указаны ниже."
                ),
                excluded_names=excluded_fallback_names,
            )
        if cancellations and text and all(acted(ctx, x.get("actor_id")) for x in cancellations):
            # Часть заявки обработана (многочастная заявка, мастер закрыл одну часть): проза о применённом
            # остаётся, необработанная часть называется явно — без замены всего ответа сухой сводкой.
            audit["partial_cancel"] = True
            ref_notices = []
            for x in cancellations:
                ref = x.get("action_ref")
                if ref is not None:
                    prog = ctx.action_progress.get(action_key(ref)) if hasattr(ctx, "action_progress") else None
                    if prog is not None:
                        notice = public_action_notice(ctx, ref, prog)
                        if notice:
                            ref_notices.append(f"{x['character']}: {notice}")
                    elif x.get("reason"):
                        ref_notices.append(f"{x['character']}: {x['reason']}")
            if ref_notices:
                text = f"{text}\n\n" + "\n".join(dict.fromkeys(ref_notices))
            else:
                names = ", ".join(dict.fromkeys(x["character"] for x in cancellations))
                text = f"{text}\n\n{names}: часть заявки мастер не обработал — уточните её следующим действием."
        elif cancellations:
            # Unconstrained prose cannot establish the success of a cancelled
            # action. Other committed effects still appear in the same answer.
            audit["cancel_fallback"] = True
            text = public_factual_fallback(ctx, tool_attempts, excluded_names=excluded_fallback_names)
        if not text:
            audit["empty_fallback"] = True
            text = public_factual_fallback(ctx, tool_attempts, excluded_names=excluded_fallback_names)
        if can_stream:
            await stream.push(text)
        return text, audit

    def _tts_for(self, c: Campaign, kind: str) -> voicing.Channel | None:
        """Канал озвучки кампании (voicing.LINE, TEXT или INTRO), если он включён и его источник подключён."""
        tts = getattr(self, "tts", None)
        if tts is None or not getattr(self, "media_dir", None):
            return None
        ch = voicing.intro(c.settings) if kind == voicing.INTRO else voicing.channel(c.settings, kind)
        if ch is None:
            return None
        engine = tts.get_engine(ch.provider) if hasattr(tts, "get_engine") else tts
        return ch if engine.enabled else None

    async def _voice(
        self, calls, cfg, c, seat_id, turn_id, system, ctx, combat_notes, *, ch: voicing.Channel, news: str = ""
    ) -> tuple[str | None, dict | None]:
        """Короткая реплика мастера и её озвучка каналом реплик. Сбой не мешает ходу: остаётся текст без голоса."""
        try:
            line = await self._voice_line(calls, cfg, c, seat_id, turn_id, system, ctx, combat_notes, news=news)
            if not line:
                return None, None
            data = await self.tts.voice_for_narration(
                self.media_dir, c.id, line, provider=ch.provider, voice_name=ch.voice
            )
            return line, data
        except Exception:  # noqa: BLE001
            log.warning("реплика или озвучка мастера не удалась", exc_info=True)
            return None, None

    async def _mood(self, s, calls, cfg, c, seat_id, turn_id, ctx: ToolContext, new, char_by_seat) -> str:
        """Эмоции мастера за ход (app/emotion): броски героев и оценка реплик технической моделью.
        Состояние живёт в scene.state, итог — строка для системного промпта повествования и озвучки."""
        persona_id = (cfg.settings or {}).get("emotion_persona") or mood.DEFAULT_PERSONA
        persona = mood.persona_of(persona_id)
        heroes = {ch.id for ch in char_by_seat.values()}
        hi, lo = mood.hero_naturals(ctx.events, heroes)
        deltas = [mood.crit_delta(persona, hi, lo)]
        text = "\n".join(m.content for m in new if m.kind in ("action", "speech") and m.content)
        if text:
            analyzer = LLMAnalyzer(persona_id=persona_id, persona_description=cfg.persona or "")
            ask = PlayerActionContext(player_id="party", character_name="", action_text=text[:2000])
            try:
                reply = await self._ask(
                    calls,
                    cfg,
                    c.id,
                    seat_id,
                    turn_id,
                    "emotion",
                    analyzer.messages(ask),
                    None,
                    override_model=parser_model_for(),
                )
                deltas.append(LLMAnalyzer.parse(reply.text))
            except LLMError:
                pass  # без оценки реплик настроение всё равно меняется от бросков и затухает
        scene = await s.get(Scene, c.id)
        state = mood.step(mood.load(scene.state if scene else None), persona, *deltas)
        if scene is not None:
            scene.state = {**(scene.state or {}), mood.MOOD_KEY: mood.dump(state)}
        return mood.instruction(state)

    async def _voice_line(
        self,
        calls: list,
        cfg: AgentConfig,
        c: Campaign,
        seat_id: str,
        turn_id: str | None,
        system: str,
        ctx: ToolContext,
        combat_notes: list,
        *,
        news: str = "",
    ) -> str:
        results = _render_results(ctx, public_only=True)
        prompt = render(
            "voice_line.j2",
            temper=mood.persona_of((cfg.settings or {}).get("emotion_persona")),
            results=results,
            news=news,
            combat_notes=list(combat_notes),
        )
        custom = (cfg.settings or {}).get("voice_line_model")
        lite_model = model_for(None, custom) if custom else parser_model_for()  # короткая реплика — техническая модель

        msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        reply = await self._ask(calls, cfg, c.id, seat_id, turn_id, "voice_line", msgs, None, override_model=lite_model)
        text = reply.text.strip().strip("\"'«»—–- ").strip()
        text = textcalls.clean(MARKUP.sub(r"\2", text))
        return text or "Вперёд!"
