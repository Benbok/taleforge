"""Повествование, настроение мастера и озвучка хода."""

from __future__ import annotations

import logging
import re
from typing import Any

from app.agents.llm import LLMError, model_for, parser_model_for
from app.agents.master.common import MARKUP, render
from app.agents.master.helpers import _check_only, _narration_length, _render_results
from app.core import combat
from app.db.models import AgentConfig, Campaign, Scene
from app.emotion import game as mood
from app.emotion.analyzers import LLMAnalyzer
from app.emotion.schemas import PlayerActionContext
from app.tools.registry import ToolContext

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
        stream=None,
        *,
        stalled: bool = False,
        meet: str = "",
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
        )
        base = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"Недавние сообщения чата:\n{convo or 'пока нет'}\n\n"
                f"Реплики игроков этого хода:\n{news}\n\n{prompt}" + (f"\n\n{meet}" if meet else ""),
            },
        ]
        known = set(ctx.world.characters) | set(ctx.world.entities)
        audit: dict[str, Any] = {"regenerated": False, "stripped": []}
        push = stream.push if stream is not None else None
        reply = await self._ask(calls, cfg, c.id, seat_id, turn_id, "narrate", base, None, stream_callback=push)
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
            # без потока: стирать черновик и печатать его заново — то самое «текст исчез и появился снова».
            # Игроки видят первый вариант, пока пишется исправленный; финальный текст заменит его на месте
            reply = await self._ask(calls, cfg, c.id, seat_id, turn_id, "narrate", retry, None)
            text = reply.text.strip()

        def strip(m: re.Match) -> str:
            if m.group(1) in known:
                return m.group(0)
            audit["stripped"].append(m.group(1))
            return m.group(2)

        text = MARKUP.sub(strip, text)
        # Очистка от случайных вызовов инструментов в тексте мастера (например, set_music {...})
        text = re.sub(r"^\s*[a-z_]+\s*\{.*?\}\s*", "", text, flags=re.DOTALL).strip()
        # Очистка от оборванного незакрытого тега разметки в конце текста
        text = re.sub(r"\[\[[^\]]*$", "", text).rstrip()
        return text or "…", audit

    def _tts_ready(self, c: Campaign) -> bool:
        st = c.settings or {}
        tts = getattr(self, "tts", None)
        if tts is None or not getattr(self, "media_dir", None) or not st.get("tts_enabled", True):
            return False
        engine = tts.get_engine(st.get("tts_provider")) if hasattr(tts, "get_engine") else tts
        return bool(engine.enabled)

    async def _voice(
        self, calls, cfg, c, seat_id, turn_id, system, ctx, combat_notes
    ) -> tuple[str | None, dict | None]:
        """Короткая реплика мастера и её озвучка. Сбой не мешает ходу: остаётся текст без голоса."""
        st = c.settings or {}
        try:
            line = await self._voice_line(calls, cfg, c, seat_id, turn_id, system, ctx, combat_notes)
            if not line:
                return None, None
            data = await self.tts.voice_for_narration(
                self.media_dir, c.id, line, provider=st.get("tts_provider"), voice_name=st.get("tts_voice")
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
            analyzer = LLMAnalyzer(persona_id=persona_id)
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
    ) -> str:
        results = _render_results(ctx)
        prompt = render(
            "voice_line.j2",
            results=results,
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
        text = MARKUP.sub(r"\2", text)
        return text or "Вперёд!"
