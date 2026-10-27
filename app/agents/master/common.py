"""Общее для ИИ-мастера: пределы хода, набор инструментов фазы решения, шаблоны промптов."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import jinja2

from app.config import Settings
from app.core import adventure, audio, plot
from app.core.chat import TURN_KINDS
from app.tools import plot as plot_tools
from app.tools.audio import AUDIO_TOOLS
from app.tools.master.generation import HOST_TOOLS
from app.tools.registry import REGISTRY, ToolContext

log = logging.getLogger(__name__)

MAX_CALLS = 8  # вызовов инструментов за ход (раздел 7)
PARSE_TIMEOUT = 30  # секунд: дольше — реплика уходит мастеру без разбора
MAX_STEPS = 12  # обращений к модели в фазе решения
HISTORY = 20  # последних сообщений в контексте (раздел 9)
COMBAT_LENGTH = "один короткий абзац, два-четыре предложения"  # в бою — только исход бросков, без пересказа сцены
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
DECISION_TOOLS = [n for n in REGISTRY if n != "review_character" and not REGISTRY[n].internal]


def decision_tools(ctx: ToolContext) -> list[str]:
    """Инструменты фазы решения. Инструменты сюжета — только когда у кампании есть каркас, звука — когда владелец
    включил его и библиотека не пуста."""
    off = set() if plot.has_plan(ctx.world.plot) else set(plot_tools.PLOT_TOOLS)
    if not adventure.is_module(ctx.campaign):
        off.add("enter_room")
    if not audio.enabled(ctx.campaign):
        off |= set(AUDIO_TOOLS)
    cfg = ctx.session.info.get("settings", Settings())
    if not (cfg.sfx_enabled and (ctx.campaign.settings or {}).get("sfx_enabled") or ctx.saved_sfx):
        off.add("request_sfx")
    if not audio.music_tracks(ctx.campaign):
        off.add("set_music")
    off.add("expand_decision_tools")  # exposed only by opt-in decision profiles
    off |= HOST_TOOLS  # подготовку места назначает ведущий, не модель
    return [n for n in REGISTRY if n != "review_character" and not REGISTRY[n].internal and n not in off]


_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(Path(__file__).resolve().parents[1] / "prompts"),
    autoescape=False,
    keep_trailing_newline=False,
)


def render(name: str, **kw: Any) -> str:
    return _env.get_template(name).render(**kw).strip()


def _routable_cast(ctx, intent):
    return None


def _world_choices(cat):
    return "Герои определяются описанием и законами авторского мира."


def declared_cast(messages: list, char_by_seat: dict, caster_id: str, spell_name: str) -> bool:
    """Заявил ли игрок заклинание в новых репликах хода: разбор парсера с ``cast`` или название в тексте.
    Название — запасной путь, когда парсер не узнал заклинание в свободной фразе."""
    name = spell_name.strip().lower()
    for m in messages:
        ch = char_by_seat.get(m.seat_id)
        if ch is None or ch.id != caster_id:
            continue
        if any(a.get("verb") == "cast" for a in (m.intent or {}).get("actions") or []):
            return True
        if name and name in (m.content or "").lower():
            return True
    return False
