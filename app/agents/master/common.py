"""Общее для ИИ-мастера: пределы хода, набор инструментов фазы решения, шаблоны промптов."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import jinja2

from app.agents import intent as intents
from app.core import adventure, audio, plot
from app.core.chat import TURN_KINDS
from app.tools import plot as plot_tools
from app.tools.audio import AUDIO_TOOLS
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
DECISION_TOOLS = [n for n in REGISTRY if n != "review_character"]


def decision_tools(ctx: ToolContext) -> list[str]:
    """Инструменты фазы решения. Инструменты сюжета — только когда у кампании есть каркас, звука — когда владелец
    включил его и библиотека не пуста."""
    off = set() if plot.has_plan(ctx.world.plot) else set(plot_tools.PLOT_TOOLS)
    if not adventure.is_module(ctx.campaign):
        off.add("enter_room")
    if not audio.enabled(ctx.campaign):
        off |= set(AUDIO_TOOLS)
    return [n for n in DECISION_TOOLS if n not in off]


_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(Path(__file__).resolve().parents[1] / "prompts"),
    autoescape=False,
    keep_trailing_newline=False,
)


def render(name: str, **kw: Any) -> str:
    return _env.get_template(name).render(**kw).strip()


def _routable_cast(ctx: ToolContext, intent: dict | None) -> dict | None:
    """Заклинание из книги героя с ясной целью сервер творит сам; площадные остаются мастеру (кто в области)."""
    from app.core.spells import spell_catalog
    from app.rules.dnd5e.spells import target_kind

    args = intents.routable_cast(intent)
    if args is None:
        return None
    chosen = args.pop("area_chosen", False)  # окно сотворения: кого накрывает область, игрок отметил сам
    spell = spell_catalog(ctx.world.catalog).spells.get(args["spell_id"])
    if spell is None or (target_kind(spell) == "area" and not chosen):
        return None
    if target_kind(spell) == "enemy" and not args.get("target_ids"):
        return None
    return args


def _world_choices(cat) -> str:
    """Классы и происхождения мира кампании — рамка, по которой ИИ-мастер сверяет историю героя."""
    origins = ", ".join(e.name for e in cat.by_kind("origin")) or "—"
    classes = ", ".join(e.name for e in cat.by_kind("class")) or "—"
    return f"Происхождения мира: {origins}. Классы мира: {classes}."
