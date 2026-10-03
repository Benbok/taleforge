"""РР-РјР°СЃС‚РµСЂ: С…РѕРґ РѕС‚ СЂРµРїР»РёРє РёРіСЂРѕРєРѕРІ РґРѕ РїРѕРІРµСЃС‚РІРѕРІР°РЅРёСЏ (РўР—, СЂР°Р·РґРµР»С‹ 5, 7, 7.1, 9).

РҐРѕРґ РјР°СЃС‚РµСЂР°:
1. РЎР±РѕСЂ СЂРµРїР»РёРє. РњР°СЃС‚РµСЂ РѕС‚РІРµС‡Р°РµС‚ РЅР° РїР°РєРµС‚: РєРѕРіРґР° РЅР°РїРёСЃР°Р»Рё РІСЃРµ РёРіСЂРѕРєРё СЃ РїРµСЂСЃРѕРЅР°Р¶Р°РјРё РёР»Рё РёСЃС‚РµРєР»Рѕ РѕРєРЅРѕ СЃР±РѕСЂР°.
2. Р¤Р°Р·Р° СЂРµС€РµРЅРёСЏ. РњРѕРґРµР»СЊ РІРёРґРёС‚ С‚Р°Р±Р»РёС†Сѓ СЃС†РµРЅС‹ РёР· Р‘Р” Рё РІС‹Р·С‹РІР°РµС‚ РёРЅСЃС‚СЂСѓРјРµРЅС‚С‹ (РЅРµ Р±РѕР»СЊС€Рµ 8). РљР°Р¶РґС‹Р№ РІС‹Р·РѕРІ РїСЂРѕРІРµСЂСЏРµС‚
   РІР°Р»РёРґР°С‚РѕСЂ, СЂРµР·СѓР»СЊС‚Р°С‚ СЃ РєСѓР±РёРєР°РјРё РІРѕР·РІСЂР°С‰Р°РµС‚СЃСЏ РјРѕРґРµР»Рё. РљРѕРЅС‚СЂР°РєС‚ РЅР°РјРµСЂРµРЅРёСЏ: РЅР° РєР°Р¶РґРѕРµ РґРµР№СЃС‚РІРёРµ РёРіСЂРѕРєР° РЅСѓР¶РµРЅ
   РІС‹Р·РѕРІ РёР»Рё СЏРІРЅС‹Р№ РѕС‚РєР°Р·; РµСЃР»Рё РјРѕРґРµР»СЊ РїСЂРѕРјРѕР»С‡Р°Р»Р°, РµС‘ РїСЂРѕСЃСЏС‚ РµС‰С‘ СЂР°Р·, РїРѕС‚РѕРј РєРѕРґ СЃР°Рј С„РёРєСЃРёСЂСѓРµС‚ РѕС‚РєР°Р·.
3. Р¤Р°Р·Р° РїРѕРІРµСЃС‚РІРѕРІР°РЅРёСЏ. РћС‚РґРµР»СЊРЅС‹Р№ Р·Р°РїСЂРѕСЃ Р±РµР· РёРЅСЃС‚СЂСѓРјРµРЅС‚РѕРІ: С‚РѕР»СЊРєРѕ СЂРµР·СѓР»СЊС‚Р°С‚С‹ С…РѕРґР° Рё СЃС†РµРЅР°.
4. РђСѓРґРёС‚РѕСЂ СЂР°Р·РјРµС‚РєРё. РЎСѓС‰РЅРѕСЃС‚Рё РІ С‚РµРєСЃС‚Рµ СЂР°Р·РјРµС‡РµРЅС‹ [[id|С‚РµРєСЃС‚]]; id РЅРµ РёР· СЂРµРµСЃС‚СЂР° вЂ” РїРѕРІС‚РѕСЂ, Р·Р°С‚РµРј СЂР°Р·РјРµС‚РєР° СЃРЅРёРјР°РµС‚СЃСЏ.
5. РўСЂР°РЅР·Р°РєС†РёСЏ С…РѕРґР°. РЎРѕР±С‹С‚РёСЏ, С€С‘РїРѕС‚С‹ Рё РїРѕРІРµСЃС‚РІРѕРІР°РЅРёРµ С„РёРєСЃРёСЂСѓСЋС‚СЃСЏ РІРјРµСЃС‚Рµ. РЎР±РѕР№ вЂ” РѕС‚РєР°С‚ РІСЃРµРіРѕ С…РѕРґР°.

РќРµ РІРѕС€Р»Рё РІ СЌС‚Р°Рї 3: РїР°СЂСЃРµСЂ РЅР°РјРµСЂРµРЅРёР№ Рё РјР°СЂС€СЂСѓС‚РёР·Р°С‚РѕСЂ РјРµС…Р°РЅРёРє (СЌС‚Р°Рї 4), СЃРІРѕРґРєРё Рё РїРѕРёСЃРє РїРѕ РїСЂР°РІРёР»Р°Рј (СЌС‚Р°Рї 5).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import jinja2
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.agents import character, memory, rhythm
from app.agents import intent as intents
from app.agents.llm import LLM, LLMError, LLMReply, model_for, parser_model_for
from app.emotion import EmotionEngine, PlayerActionContext
from app.agents.providers import explain
from app.core import audio, bonds, combat, persona, plot
from app.core.brief import brief_text
from app.core.campaigns import master_seat
from app.core.chat import active_session, next_seq, system_message
from app.core.linker import link_text
from app.db.models import (
    AgentConfig,
    Campaign,
    CampaignSecret,
    Character,
    Event,
    LlmCall,
    MasterTurn,
    Message,
    Scene,
    Summary,
    User,
    as_utc,
    now,
)
from app.gateway.events import envelope, publish_message
from app.rules.dice import Dice
from app.tools import fortune as fortune_tools
from app.tools import plot as plot_tools
from app.tools import progress as progress_tools
from app.tools import standing as standing_tools
from app.tools.audio import AUDIO_TOOLS
from app.tools.registry import REGISTRY, ToolContext, execute, tool_specs
from app.tools.runtime import flush_outbox, open_context, publish_changes

log = logging.getLogger(__name__)

MAX_CALLS = 8  # РІС‹Р·РѕРІРѕРІ РёРЅСЃС‚СЂСѓРјРµРЅС‚РѕРІ Р·Р° С…РѕРґ (СЂР°Р·РґРµР» 7)
PARSE_TIMEOUT = 30  # СЃРµРєСѓРЅРґ: РґРѕР»СЊС€Рµ вЂ” СЂРµРїР»РёРєР° СѓС…РѕРґРёС‚ РјР°СЃС‚РµСЂСѓ Р±РµР· СЂР°Р·Р±РѕСЂР°
MAX_STEPS = 12  # РѕР±СЂР°С‰РµРЅРёР№ Рє РјРѕРґРµР»Рё РІ С„Р°Р·Рµ СЂРµС€РµРЅРёСЏ
HISTORY = 20  # РїРѕСЃР»РµРґРЅРёС… СЃРѕРѕР±С‰РµРЅРёР№ РІ РєРѕРЅС‚РµРєСЃС‚Рµ (СЂР°Р·РґРµР» 9)
PLAYER_KINDS = ("action", "speech", "whisper")
CATCH_UP_SYSTEM = (
    "РРіСЂРѕРє С‚РµРєСЃС‚РѕРІРѕР№ СЂРѕР»РµРІРѕР№ РёРіСЂС‹ РЅРµРЅР°РґРѕР»РіРѕ РІС‹РїР°Р» РёР· СЃРµС‚Рё. РўРµР±Рµ РґР°СЋС‚ СЃРѕРѕР±С‰РµРЅРёСЏ, РєРѕС‚РѕСЂС‹Рµ РѕРЅ РїСЂРѕРїСѓСЃС‚РёР». "
    "РџРµСЂРµСЃРєР°Р¶Рё РµРјСѓ РїРѕ-СЂСѓСЃСЃРєРё РІ 2вЂ“4 РїСЂРµРґР»РѕР¶РµРЅРёСЏС…, С‡С‚Рѕ РїСЂРѕРёР·РѕС€Р»Рѕ Рё РЅР° С‡С‘Рј РѕСЃС‚Р°РЅРѕРІРёР»РёСЃСЊ, РѕР±СЂР°С‰Р°СЏСЃСЊ РЅР° В«РІС‹В». "
    "Р‘РµР· С‡РёСЃРµР» С…РёС‚РѕРІ Рё СѓСЂРѕРЅР°, РЅРёС‡РµРіРѕ РЅРµ РІС‹РґСѓРјС‹РІР°Р№: С‚РѕР»СЊРєРѕ С‚Рѕ, С‡С‚Рѕ РµСЃС‚СЊ РІ СЃРѕРѕР±С‰РµРЅРёСЏС…."
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
    """РРЅСЃС‚СЂСѓРјРµРЅС‚С‹ С„Р°Р·С‹ СЂРµС€РµРЅРёСЏ. РРЅСЃС‚СЂСѓРјРµРЅС‚С‹ СЃСЋР¶РµС‚Р° вЂ” С‚РѕР»СЊРєРѕ РєРѕРіРґР° Сѓ РєР°РјРїР°РЅРёРё РµСЃС‚СЊ РєР°СЂРєР°СЃ, Р·РІСѓРєР° вЂ” РєРѕРіРґР° РІР»Р°РґРµР»РµС†
    РІРєР»СЋС‡РёР» РµРіРѕ Рё Р±РёР±Р»РёРѕС‚РµРєР° РЅРµ РїСѓСЃС‚Р°."""
    off = set() if plot.has_plan(ctx.world.plot) else set(plot_tools.PLOT_TOOLS)
    if not audio.enabled(ctx.campaign):
        off |= set(AUDIO_TOOLS)
    return [n for n in DECISION_TOOLS if n not in off]


_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(Path(__file__).parent / "prompts"),
    autoescape=False,
    keep_trailing_newline=False,
)


def render(name: str, **kw: Any) -> str:
    return _env.get_template(name).render(**kw).strip()


def _routable_cast(ctx: ToolContext, intent: dict | None) -> dict | None:
    """Р—Р°РєР»РёРЅР°РЅРёРµ РёР· РєРЅРёРіРё РіРµСЂРѕСЏ СЃ СЏСЃРЅРѕР№ С†РµР»СЊСЋ СЃРµСЂРІРµСЂ С‚РІРѕСЂРёС‚ СЃР°Рј; РїР»РѕС‰Р°РґРЅС‹Рµ РѕСЃС‚Р°СЋС‚СЃСЏ РјР°СЃС‚РµСЂСѓ (РєС‚Рѕ РІ РѕР±Р»Р°СЃС‚Рё)."""
    from app.core.spells import spell_catalog
    from app.rules.dnd5e.spells import target_kind

    args = intents.routable_cast(intent)
    if args is None:
        return None
    spell = spell_catalog(ctx.world.catalog).spells.get(args["spell_id"])
    if spell is None or target_kind(spell) == "area":
        return None
    if target_kind(spell) == "enemy" and not args.get("target_ids"):
        return None
    return args


def _world_choices(cat) -> str:
    """РљР»Р°СЃСЃС‹ Рё РїСЂРѕРёСЃС…РѕР¶РґРµРЅРёСЏ РјРёСЂР° РєР°РјРїР°РЅРёРё вЂ” СЂР°РјРєР°, РїРѕ РєРѕС‚РѕСЂРѕР№ РР-РјР°СЃС‚РµСЂ СЃРІРµСЂСЏРµС‚ РёСЃС‚РѕСЂРёСЋ РіРµСЂРѕСЏ."""
    origins = ", ".join(e.name for e in cat.by_kind("origin")) or "вЂ”"
    classes = ", ".join(e.name for e in cat.by_kind("class")) or "вЂ”"
    return f"РџСЂРѕРёСЃС…РѕР¶РґРµРЅРёСЏ РјРёСЂР°: {origins}. РљР»Р°СЃСЃС‹ РјРёСЂР°: {classes}."


class MasterService:
    """РћС‡РµСЂРµРґСЊ С…РѕРґРѕРІ РР-РјР°СЃС‚РµСЂР° РїРѕ РєР°РјРїР°РЅРёСЏРј. РћРґРёРЅ С…РѕРґ РєР°РјРїР°РЅРёРё Р·Р° СЂР°Р·; СЂРµРїР»РёРєРё, РїСЂРёС€РµРґС€РёРµ РІРѕ РІСЂРµРјСЏ С…РѕРґР°,
    СѓС…РѕРґСЏС‚ РІ СЃР»РµРґСѓСЋС‰РёР№ РїР°РєРµС‚."""

    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        bus,
        llm: LLM,
        dice_factory=Dice,
        media_dir: Path | None = None,
        tts: Any = None,
    ):
        self.maker = sessionmaker
        self.bus = bus
        self.llm = llm
        self.dice_factory = dice_factory
        self.media_dir = media_dir
        self.tts = tts
        self._tasks: dict[str, asyncio.Task] = {}
        self._pending: set[str] = set()
        self._locks: dict[str, asyncio.Lock] = {}
        self._background: set[asyncio.Task] = set()
        self._timers: dict[str, asyncio.Task] = {}  # С‚Р°Р№РјРµСЂ С…РѕРґР° РіРµСЂРѕСЏ РІ Р±РѕСЋ, РїРѕ РєР°РјРїР°РЅРёСЏРј
        # prompt_id в†’ (РєР°РјРїР°РЅРёСЏ, РјРµСЃС‚Рѕ, РѕС‚РІРµС‚, РєРЅРѕРїРєР°): РѕС‚РєСЂС‹С‚СѓСЋ РєРЅРѕРїРєСѓ СЃРЅРёРјРѕРє РѕС‚РґР°С‘С‚ Рё РїРѕСЃР»Рµ РїРµСЂРµРїРѕРґРєР»СЋС‡РµРЅРёСЏ
        self._reactions: dict[str, tuple[str, str, asyncio.Future, dict]] = {}
        self._summarizing: set[str] = set()
        self._intro_locks: dict[str, asyncio.Lock] = {}
        self.presence = None  # app/gateway/presence.py: РєС‚Рѕ РёР· РёРіСЂРѕРєРѕРІ СѓС€С‘Р» РІРѕ РІСЂРµРјСЏ СЃРµСЃСЃРёРё (СЂР°Р·РґРµР» 11)
        self.players = None  # app/agents/player.py: РР-РёРіСЂРѕРєРё (СЂР°Р·РґРµР» 5.2)
        self._seen: dict[str, tuple[frozenset, str]] = {}  # РїР°РІС€РёРµ РіРµСЂРѕРё Рё СЂРµР¶РёРј СЃС†РµРЅС‹: РґР»СЏ СЃРёР»СЊРЅС‹С… СЃРѕР±С‹С‚РёР№

    # --- РѕС‡РµСЂРµРґСЊ ---

    def notify(self, campaign_id: str) -> None:
        """РџСЂРёС€Р»Р° СЂРµРїР»РёРєР° РёРіСЂРѕРєР°: Р·Р°РїСѓСЃС‚РёС‚СЊ СЃР±РѕСЂ РїР°РєРµС‚Р° РёР»Рё РѕС‚РјРµС‚РёС‚СЊ, С‡С‚Рѕ РїРѕСЃР»Рµ С‚РµРєСѓС‰РµРіРѕ С…РѕРґР° РЅСѓР¶РµРЅ РµС‰С‘ РѕРґРёРЅ."""
        task = self._tasks.get(campaign_id)
        if task is not None and not task.done():
            self._pending.add(campaign_id)
            return
        self._tasks[campaign_id] = asyncio.create_task(self._loop(campaign_id))

    def schedule_review(self, campaign_id: str, character_id: str) -> None:
        self._spawn(self.review_character(campaign_id, character_id))

    def schedule_summary(self, campaign_id: str, kind: str = "rolling", session_id: str | None = None) -> None:
        self._spawn(self.summarize(campaign_id, kind, session_id=session_id))

    def schedule_bonds(self, campaign_id: str, character_id: str) -> None:
        from app.agents import prelude

        self._spawn(prelude.ask_questions(self, campaign_id, character_id))

    def schedule_hook(self, campaign_id: str, character_id: str) -> None:
        from app.agents import prelude

        self._spawn(prelude.make_hook(self, campaign_id, character_id))

    def schedule_session_open(self, campaign_id: str, session_id: str | None) -> None:
        """РЎС‚Р°СЂС‚ СЃРµСЃСЃРёРё: РІСЃС‚СѓРїР»РµРЅРёРµ РґР»СЏ РЅРѕРІС‹С… РіРµСЂРѕРµРІ, Р·Р°С‚РµРј С†РµР»СЊ РЅР° РІРµС‡РµСЂ (РР-РјР°СЃС‚РµСЂ СЃ РєР°СЂРєР°СЃРѕРј)."""
        from app.agents import rhythm

        async def run() -> None:
            await self.introduce(campaign_id)
            if session_id:
                await self._safe(rhythm.session_goal(self, campaign_id, session_id), "С†РµР»СЊ РЅР° РІРµС‡РµСЂ")

        self._spawn(run())

    def schedule_session_close(self, campaign_id: str, session_id: str | None, ended: bool) -> None:
        """РљРѕРЅРµС† СЃРµСЃСЃРёРё: СЃРІРѕРґРєР°, Р·Р°С‚РµРј Р·Р°С†РµРїРєР° РЅР° СЃР»РµРґСѓСЋС‰РёР№ СЂР°Р· РёР»Рё, РїСЂРё Р·Р°РІРµСЂС€РµРЅРёРё РєР°РјРїР°РЅРёРё, СЌРїРёР»РѕРі."""
        from app.agents import rhythm

        async def run() -> None:
            # СЃРЅР°С‡Р°Р»Р° СЃРІРѕРґРєР° СЃРµСЃСЃРёРё: СЌРїРёР»РѕРі Рё Р·Р°С†РµРїРєР° РѕРїРёСЂР°СЋС‚СЃСЏ РЅР° РЅРµС‘, Р° Р·Р°РїРёСЃСЊ РїРѕ РѕС‡РµСЂРµРґРё РЅРµ СЃРїРѕСЂРёС‚ Р·Р° Р±Р°Р·Сѓ
            await self._safe(self.summarize(campaign_id, "session", session_id=session_id), "СЃРІРѕРґРєР° СЃРµСЃСЃРёРё")
            await self._safe(
                character.chronicle(self, campaign_id, "СЃРµСЃСЃРёСЏ Р·Р°РєРѕРЅС‡РёР»Р°СЃСЊ", session_id=session_id), "Р»РµС‚РѕРїРёСЃСЊ"
            )
            if ended:
                await self._safe(rhythm.epilogue(self, campaign_id), "СЌРїРёР»РѕРі")
            else:
                await self._safe(rhythm.session_hook(self, campaign_id, session_id), "Р·Р°С†РµРїРєР° РЅР° СЃР»РµРґСѓСЋС‰СѓСЋ СЃРµСЃСЃРёСЋ")

        self._spawn(run())

    async def _safe(self, coro, what: str):
        try:
            return await coro
        except Exception:  # noqa: BLE001 вЂ” СЂРёС‚Рј СЃРµСЃСЃРёРё РЅРµ РґРѕР»Р¶РµРЅ СЂРѕРЅСЏС‚СЊ СЃРµСЂРІРµСЂ
            log.exception("%s РЅРµ СѓРґР°Р»РѕСЃСЊ", what)
            return None

    async def introduce(self, campaign_id: str) -> str | None:
        """Р’СЃС‚СѓРїР»РµРЅРёРµ РґР»СЏ РµС‰С‘ РЅРµ РїСЂРµРґСЃС‚Р°РІР»РµРЅРЅС‹С… РіРµСЂРѕРµРІ; РѕРґРЅРѕ РЅР° РєР°РјРїР°РЅРёСЋ Р·Р° СЂР°Р·."""
        from app.agents import prelude

        async with self._intro_locks.setdefault(campaign_id, asyncio.Lock()):
            try:
                return await prelude.introduce(self, campaign_id)
            except Exception:  # noqa: BLE001 вЂ” Р±РµР· РІСЃС‚СѓРїР»РµРЅРёСЏ РёРіСЂР° РІСЃС‘ СЂР°РІРЅРѕ РёРґС‘С‚
                log.exception("РІСЃС‚СѓРїР»РµРЅРёРµ РІ РєР°РјРїР°РЅРёРё %s РЅРµ СѓРґР°Р»РѕСЃСЊ", campaign_id)
                return None

    def schedule_replan(self, campaign_id: str) -> None:
        """РџРµСЂРµСЃРјРѕС‚СЂ РѕСЃС‚Р°РІС€РёС…СЃСЏ Р°РєС‚РѕРІ РїРѕСЃР»Рµ Р·Р°РєСЂС‹С‚РёСЏ Р°РєС‚Р° (СЂР°Р·РґРµР» 3): РІ С„РѕРЅРµ, С…РѕРґ РµРіРѕ РЅРµ Р¶РґС‘С‚."""
        from app.agents import architect

        self._spawn(architect.revise(self, campaign_id))

    def _spawn(self, coro) -> None:
        t = asyncio.create_task(coro)
        self._background.add(t)
        t.add_done_callback(self._background.discard)

    async def wait_idle(self, campaign_id: str | None = None) -> None:
        # С…РѕРґ РјРѕР¶РµС‚ Р·Р°РїСѓСЃС‚РёС‚СЊ С„РѕРЅРѕРІСѓСЋ Р·Р°РґР°С‡Сѓ РІ СЃР°РјРѕРј РєРѕРЅС†Рµ (РїРµСЂРµСЃРјРѕС‚СЂ РєР°СЂРєР°СЃР°), РїРѕСЌС‚РѕРјСѓ РїСЂРѕРІРµСЂСЏРµРј РїРѕ РєСЂСѓРіСѓ
        while True:
            agents = self.players._tasks if self.players is not None else set()
            if self._background:
                await asyncio.wait(set(self._background))
            elif agents:
                await asyncio.wait(set(agents))
            elif (t := self._tasks.get(campaign_id)) is not None and not t.done():
                await asyncio.wait({t})
            else:
                return

    def wake_players(self, cid: str) -> None:
        """РќРѕРІРѕРµ РїРѕРІРµСЃС‚РІРѕРІР°РЅРёРµ РІ РѕС‚РІРµС‚ Р¶РёРІРѕРјСѓ РёРіСЂРѕРєСѓ: РР-РёРіСЂРѕРєРё РјРѕРіСѓС‚ РѕС‚РєР»РёРєРЅСѓС‚СЊСЃСЏ."""
        if self.players is not None:
            self.players.after_narration(cid)

    async def stop(self) -> None:
        tasks = [*self._tasks.values(), *self._background, *self._timers.values()]
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
            log.exception("РѕС‡РµСЂРµРґСЊ РјР°СЃС‚РµСЂР° РєР°РјРїР°РЅРёРё %s", cid)
        finally:
            self._tasks.pop(cid, None)

    async def _collect_delay(self, cid: str) -> float | None:
        """РЎРєРѕР»СЊРєРѕ РµС‰С‘ Р¶РґР°С‚СЊ СЂРµРїР»РёРє. None вЂ” С…РѕРґ РЅРµ РЅСѓР¶РµРЅ: РјР°СЃС‚РµСЂ РЅРµ РР, СЃРµСЃСЃРёРё РЅРµС‚ РёР»Рё РЅРѕРІС‹С… СЂРµРїР»РёРє РЅРµС‚."""
        async with self.maker() as s:
            c = await s.get(Campaign, cid)
            if c is None or master_seat(c).occupant_type != "agent" or await active_session(s, cid) is None:
                return None
            new = await _new_player_messages(s, c)
            if not new:
                return None
            sc = await s.get(Scene, cid)
            if sc is not None and sc.mode == "combat" and sc.turn_order:
                # РІ Р±РѕСЋ РјР°СЃС‚РµСЂ РѕС‚РІРµС‡Р°РµС‚ СЃСЂР°Р·Сѓ РЅР° РґРµР№СЃС‚РІРёРµ РіРµСЂРѕСЏ, С‡РµР№ С…РѕРґ; РѕСЃС‚Р°Р»СЊРЅРѕРµ Р¶РґС‘С‚ СЌС‚РѕРіРѕ РѕС‚РІРµС‚Р°
                st = sc.state or {}
                cur = await s.get(Character, sc.turn_order[int(st.get("turn", 0)) % len(sc.turn_order)]["id"])
                if cur is not None and any(m.kind == "action" and m.seat_id == cur.seat_id for m in new):
                    return 0
                return None
            agents = {x.id for x in c.seats if x.occupant_type == "agent"}
            players = {
                ch.seat_id
                for ch in await s.scalars(
                    select(Character).where(Character.campaign_id == cid, Character.status.in_(("approved", "active")))
                )
                if ch.seat_id
            }
            if self.presence is not None:
                players -= self.presence.away(cid)  # СѓС€РµРґС€РµРіРѕ РёРіСЂРѕРєР° РЅРµ Р¶РґС‘Рј
            players -= agents  # Р¶РёРІС‹Рµ РёРіСЂРѕРєРё Р·Р°РєСЂС‹РІР°СЋС‚ РѕРєРЅРѕ СЃР±РѕСЂР°; РР С…РѕРґРёС‚ СЃРёРЅС…СЂРѕРЅРЅРѕ РїРµСЂРµРґ РјР°СЃС‚РµСЂРѕРј
            wrote = {m.seat_id for m in new}
            if players and players <= wrote:
                return 0
            window = float((c.settings or {}).get("collect_window_sec", 60))
            waited = (datetime.now(UTC) - as_utc(new[0].created_at)).total_seconds()
            return max(0.0, window - waited)

    # --- С…РѕРґ ---

    async def _status(self, cid: str, stage: str) -> None:
        await self.bus.publish(cid, envelope("master.status", cid, {"stage": stage}), None)

    async def _states(self, cid: str, ids: list[str], state: str) -> None:
        if ids:
            await self.bus.publish(cid, envelope("message.state", cid, {"ids": ids, "state": state}), None)

    async def run_turn(self, cid: str) -> str | None:
        lock = self._locks.setdefault(cid, asyncio.Lock())
        async with lock:
            if self.players is not None:
                await self.players.take_turns(cid)
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
                    msg = await system_message(s, c, "Р›РёРјРёС‚ СЂР°СЃС…РѕРґРѕРІ РЅР° РјРѕРґРµР»Рё РёСЃС‡РµСЂРїР°РЅ: РјР°СЃС‚РµСЂ РјРѕР»С‡РёС‚.", game)
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
                    await self._states(cid, [m.id for m in new], "failed")
                    return None
            turn = MasterTurn(campaign_id=cid, session_id=game.id, upto_seq=new[-1].seq, trace={"from_seq": new[0].seq})
            s.add(turn)
            await s.commit()
            turn_id = turn.id
            ids = [m.id for m in new]

        await self._states(cid, ids, "processing")
        await self.introduce(cid)  # РЅРѕРІРёС‡РѕРє Р·Р° СЃС‚РѕР»РѕРј: РјР°СЃС‚РµСЂ СЃРЅР°С‡Р°Р»Р° РїСЂРµРґСЃС‚Р°РІР»СЏРµС‚ РµРіРѕ
        calls: list[LlmCall] = []
        replan = False
        await self._status(cid, "listening")
        try:
            async with self.maker() as s:
                published = await self._play(s, cid, turn_id, calls)
            if published["skipped"]:
                return turn_id
            await publish_changes(self.bus, published["ctx"], published["messages"], published["names"])
            await self._states(cid, published["ids"], "answered")
            await self.after_turn(published["ctx"])
            replan = "replan" in published["ctx"].signals
            if self.players is not None:
                self.players.reset_round(cid)
            self.schedule_summary(cid)  # СЃРІРѕРґРєР° РѕР±РЅРѕРІРёС‚СЃСЏ, РµСЃР»Рё РЅР°Р±СЂР°Р»РѕСЃСЊ summary_every СЃРѕРѕР±С‰РµРЅРёР№
        except Exception as e:  # noqa: BLE001 вЂ” СЃР±РѕР№ С…РѕРґР° РЅРµ РґРѕР»Р¶РµРЅ СЂРѕРЅСЏС‚СЊ СЃРµСЂРІРµСЂ; С…РѕРґ РѕС‚РєР°С‚С‹РІР°РµС‚СЃСЏ С†РµР»РёРєРѕРј
            log.exception("С…РѕРґ РјР°СЃС‚РµСЂР° %s РЅРµ СѓРґР°Р»СЃСЏ", turn_id)
            async with self.maker() as s:
                t = await s.get(MasterTurn, turn_id)
                t.status, t.finished_at = "failed", now()
                t.trace = {**(t.trace or {}), "error": f"{type(e).__name__}: {e}"}
                c = await s.get(Campaign, cid)
                msg = await system_message(
                    s, c, "РњР°СЃС‚РµСЂ РЅРµ СЃРјРѕРі Р·Р°РІРµСЂС€РёС‚СЊ С…РѕРґ. РќРёС‡РµРіРѕ РЅРµ РёР·РјРµРЅРёР»РѕСЃСЊ: РїРѕРІС‚РѕСЂРёС‚Рµ РґРµР№СЃС‚РІРёРµ.", None
                )
                sc = await s.get(Scene, cid)
                if sc is not None and (sc.state or {}).get("submitted"):
                    sc.state = {**sc.state, "submitted": False}  # Р·Р°СЏРІРєСѓ РјРѕР¶РЅРѕ РїРѕРІС‚РѕСЂРёС‚СЊ
                await s.commit()
            await publish_message(self.bus, msg)
            await self._states(cid, ids, "failed")
        finally:
            await self._status(cid, "idle")
            if calls:
                async with self.maker() as s:
                    s.add_all(calls)
                    await s.commit()
        if replan:
            self.schedule_replan(cid)  # РїРѕСЃР»Рµ СѓС‡С‘С‚Р° РІС‹Р·РѕРІРѕРІ: РїРµСЂРµСЃРјРѕС‚СЂ РїРёС€РµС‚ РІ С‚Сѓ Р¶Рµ РєР°РјРїР°РЅРёСЋ
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
        stream_callback: Any = None,
    ) -> LLMReply:
        model = override_model or model_for()
        try:
            reply = await self.llm.complete(
                messages,
                model=model,
                tools=tools,
                max_tokens=8192,
                temperature=0.2 if purpose == "decide" else cfg.temperature,
                api_base=(cfg.settings or {}).get("api_base"),
                stream_callback=stream_callback,
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
        names = await _names(s, c)
        if not new:  # РІСЃРµ СЂРµРїР»РёРєРё РїР°РєРµС‚Р° РѕС‚РјРµРЅРµРЅС‹, РїРѕРєР° С…РѕРґ РЅР°С‡РёРЅР°Р»СЃСЏ: РјРѕРґРµР»СЊ РЅРµ Р·РѕРІС‘Рј
            turn.status, turn.finished_at = "skipped", now()
            await s.commit()
            return {"ctx": ctx, "messages": [], "names": names, "ids": [], "skipped": True}
        history = await _history(s, c, new[0].seq if new else turn.upto_seq + 1)
        char_by_seat = {
            ch.seat_id: ch
            for ch in ctx.world.characters.values()
            if ch.seat_id and ch.status in ("approved", "active", "dead")
        }

        system = await self._system_prompt(s, c, cfg, ctx)

        emotion_engine = EmotionEngine(llm_client=self.llm, persona_id=(cfg.settings or {}).get("persona_id", "tired_mentor"))
        emotion_prompt = ""
        for m in new:
            if m.kind == "action":
                actor_id = m.seat_id
                char_name = char_by_seat[actor_id].name if actor_id in char_by_seat else "Unknown"
                act_ctx = PlayerActionContext(player_id=actor_id or "", character_name=char_name, action_text=m.content)
                emotion_prompt = await emotion_engine.process(ctx.game_session_id, act_ctx)
        if emotion_prompt:
            system += "\n" + emotion_prompt

        convo = _render_history(history, char_by_seat, names)
        news = _render_new(new, char_by_seat, names)
        required = {
            char_by_seat[m.seat_id].id
            for m in new
            if m.kind == "action"
            and m.seat_id in char_by_seat
            and char_by_seat[m.seat_id].status in ("approved", "active")
        }
        hero_turn = combat.current_character(ctx)  # РІ Р±РѕСЋ: С‡РµР№ С…РѕРґ Р·Р°РєСЂС‹РІР°РµС‚ СЌС‚РѕС‚ РѕС‚РІРµС‚ РјР°СЃС‚РµСЂР°
        combat_note = ""
        if hero_turn is not None:
            combat_note = (
                f"\n\nРРґС‘С‚ Р±РѕР№, СЂР°СѓРЅРґ {ctx.world.scene.round}. РЎРµР№С‡Р°СЃ С…РѕРґ {hero_turn.name} ({hero_turn.id}): "
                "РѕР±СЂР°Р±РѕС‚Р°Р№ С‚РѕР»СЊРєРѕ РµРіРѕ РґРµР№СЃС‚РІРёРµ. РҐРѕРґС‹ СЃСѓС‰РµСЃС‚РІ СЃРµСЂРІРµСЂ РїСЂРѕРІРµРґС‘С‚ СЃР°Рј РїРѕСЃР»Рµ С‚РІРѕРµРіРѕ РѕС‚РІРµС‚Р° РїРѕ РёС… "
                "РїСЂРѕС„РёР»СЋ РїРѕРІРµРґРµРЅРёСЏ вЂ” РЅРµ Р°С‚Р°РєСѓР№ Р·Р° СЃСѓС‰РµСЃС‚РІ Рё РЅРµ РјРµРЅСЏР№ РѕС‡РµСЂРµРґСЊ."
            )

        # РњР°СЂС€СЂСѓС‚РёР·Р°С‚РѕСЂ РјРµС…Р°РЅРёРє (СЂР°Р·РґРµР» 7): РѕРґРЅРѕР·РЅР°С‡РЅСѓСЋ Р°С‚Р°РєСѓ РѕСЂСѓР¶РёРµРј СЃРµСЂРІРµСЂ РїСЂРѕРІРѕРґРёС‚ СЃР°Рј, РјРѕРґРµР»СЊ РµС‘ С‚РѕР»СЊРєРѕ РѕРїРёС€РµС‚
        trace_calls: list[dict] = []
        routed: list[str] = []
        for m in new:
            name, args = "resolve_attack", intents.routable_attack(m.intent) if m.kind == "action" else None
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
            if hero_turn is not None and actor != hero_turn.id:
                continue
            await self._status(cid, "rolling")
            r = await execute(ctx, name, args, key=f"{turn_id}:route:{m.id}")
            trace_calls.append({"tool": name, "args": args, "result": r, "routed": True})
            if r.get("ok"):
                routed.append(f"{actor}: {name} СѓР¶Рµ РІС‹РїРѕР»РЅРµРЅ СЃРµСЂРІРµСЂРѕРј РїРѕ РЅР°РјРµСЂРµРЅРёСЋ")
            else:
                routed.append(
                    f"{actor}: {name} РѕС‚РєР»РѕРЅС‘РЅ СЃРµСЂРІРµСЂРѕРј: {r.get('error')} вЂ” РѕР±СЉСЏСЃРЅРё РёРіСЂРѕРєСѓ РІ РїРѕРІРµСЃС‚РІРѕРІР°РЅРёРё"
                )
        route_note = ""
        if routed:
            route_note = "\n\nРЈР¶Рµ СЃРґРµР»Р°РЅРѕ СЃРµСЂРІРµСЂРѕРј (РЅРµ РїРѕРІС‚РѕСЂСЏР№ СЌС‚Рё РІС‹Р·РѕРІС‹):\n- " + "\n- ".join(routed)

        await self._status(cid, "remembering")
        memory_note = await self._memory_block(s, c, ctx, new)
        # РјРёСЂ РЅРµ Р¶РґС‘С‚: СЃРѕР·СЂРµРІС€РёРµ РѕС‚РІРµС‚С‹ РЅР° РїРѕСЃС‚СѓРїРєРё РіРµСЂРѕРµРІ Рё СЃР»СѓС‡Р°Р№РЅРѕСЃС‚Рё, РІС‹РїР°РІС€РёРµ, РїРѕРєР° С€Р»Рѕ РёРіСЂРѕРІРѕРµ РІСЂРµРјСЏ
        world_note = await standing_tools.run_standing(ctx) + await fortune_tools.run_watch(ctx)
        msgs: list[dict] = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    f"{memory_note}РўР°Р±Р»РёС†Р° СЃС†РµРЅС‹:\n{ctx.world.scene_table()}\n\n{world_note}"
                    f"РќРµРґР°РІРЅРёРµ СЃРѕРѕР±С‰РµРЅРёСЏ С‡Р°С‚Р°:\n{convo or 'РїРѕРєР° РЅРµС‚'}\n\n"
                    f"РќРѕРІС‹Рµ СЂРµРїР»РёРєРё РёРіСЂРѕРєРѕРІ:\n{news}{combat_note}{route_note}\n\nР¤Р°Р·Р° СЂРµС€РµРЅРёСЏ: РІС‹Р·РѕРІРё РЅСѓР¶РЅС‹Рµ "
                    "РёРЅСЃС‚СЂСѓРјРµРЅС‚С‹. "
                    "РљРѕРіРґР° РІСЃРµ РґРµР№СЃС‚РІРёСЏ Р·Р°РєСЂС‹С‚С‹, РѕС‚РІРµС‚СЊ РѕРґРЅРёРј СЃР»РѕРІРѕРј В«РіРѕС‚РѕРІРѕВ» Р±РµР· РІС‹Р·РѕРІРѕРІ."
                ),
            },
        ]
        done_calls = retries = 0
        for _ in range(MAX_STEPS):
            reply = await self._ask(
                calls, cfg, cid, seat.id, turn_id, "decide", msgs, tool_specs(ctx.world, decision_tools(ctx))
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
                                f"РќРµ Р·Р°РєСЂС‹С‚С‹ РґРµР№СЃС‚РІРёСЏ РїРµСЂСЃРѕРЅР°Р¶РµР№: {names_open}. РќР° РєР°Р¶РґРѕРµ РґРµР№СЃС‚РІРёРµ РІС‹Р·РѕРІРё РёРЅСЃС‚СЂСѓРјРµРЅС‚ "
                                "РёР»Рё cancel_action СЃ РїСЂРёС‡РёРЅРѕР№."
                            ),
                        }
                    )
                    continue
                break
            for call in reply.tool_calls:
                if done_calls >= MAX_CALLS:
                    result = {
                        "ok": False,
                        "error": f"Р»РёРјРёС‚ {MAX_CALLS} РІС‹Р·РѕРІРѕРІ Р·Р° С…РѕРґ РёСЃС‡РµСЂРїР°РЅ: РїРµСЂРµС…РѕРґРё Рє РїРѕРІРµСЃС‚РІРѕРІР°РЅРёСЋ",
                    }
                elif "__invalid_json__" in call.arguments:
                    result = {"ok": False, "error": "Р°СЂРіСѓРјРµРЅС‚С‹ вЂ” РЅРµ JSON-РѕР±СЉРµРєС‚"}
                else:
                    if call.name in ROLL_TOOLS:
                        await self._status(cid, "rolling")
                    result = await execute(ctx, call.name, call.arguments, key=f"{turn_id}:{call.id}")
                    if call.name not in AUDIO_TOOLS:  # Р·РІСѓРє РЅРµ РѕС‚РЅРёРјР°РµС‚ РІС‹Р·РѕРІС‹ Сѓ РјРµС…Р°РЅРёРєРё
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

        # РљРѕРЅС‚СЂР°РєС‚ РЅР°РјРµСЂРµРЅРёСЏ: РјРѕР»С‡Р°РЅРёРµ Р·Р°РїСЂРµС‰РµРЅРѕ вЂ” РєРѕРґ СЃР°Рј С„РёРєСЃРёСЂСѓРµС‚ РѕС‚РєР°Р· (СЂР°Р·РґРµР» 7.1)
        for cid_ in sorted(required - ctx.closed):
            r = await execute(
                ctx,
                "cancel_action",
                {"character_id": cid_, "reason": "РјР°СЃС‚РµСЂ РЅРµ РѕР±СЂР°Р±РѕС‚Р°Р» РґРµР№СЃС‚РІРёРµ"},
                key=f"{turn_id}:auto_cancel:{cid_}",
            )
            trace_calls.append({"tool": "cancel_action", "auto": True, "result": r})

        combat_notes: list[str] = []
        if combat.in_combat(ctx):
            acted = hero_turn is not None and any(m.kind == "action" and m.seat_id == hero_turn.seat_id for m in new)
            if acted and combat.current_id(ctx) == hero_turn.id:
                await combat.finish_turn(ctx, combat_notes)
            await self._status(cid, "rolling")
            combat_notes += await combat.run_until_hero(ctx, f"{turn_id}:combat", self._ask_reaction)

        plot_notes = await plot_tools.run_clock(ctx)  # Р·Р»РѕРґРµРё РЅРµ Р¶РґСѓС‚: С€Р°РіРё СѓРіСЂРѕР·С‹ РїРѕ РёРіСЂРѕРІС‹Рј РґРЅСЏРј

        await self._status(cid, "describing")
        tts_on = bool((c.settings or {}).get("tts_enabled", True))
        tts_voice = (c.settings or {}).get("tts_voice")
        tts_ready = getattr(self, "tts", None) and getattr(self, "media_dir", None) and tts_on

        voice_line_text: str | None = None
        voice_data = None

        if tts_ready:
            try:
                voice_line_text = await self._voice_line(calls, cfg, c, seat.id, turn_id, system, ctx, combat_notes)
                if voice_line_text:
                    tts_provider = (c.settings or {}).get("tts_provider")
                    voice_data = await self.tts.voice_for_narration(self.media_dir, cid, voice_line_text, provider=tts_provider, voice_name=tts_voice)
            except Exception:
                log.warning("РѕС€РёР±РєР° РіРµРЅРµСЂР°С†РёРё/РѕР·РІСѓС‡РєРё voice_line", exc_info=True)
                voice_line_text = None
                voice_data = None

        msg_data: dict[str, Any] = {}
        if voice_data:
            if voice_line_text:
                voice_data["text"] = voice_line_text
            msg_data["voice"] = voice_data

        msg = Message(
            campaign_id=cid,
            session_id=ctx.game_session_id,
            seq=await next_seq(s, cid),
            seat_id=seat.id,
            kind="narration",
            content="",
            data=msg_data or None,
        )
        s.add(msg)
        await s.flush()
        
        await publish_message(self.bus, msg)

        async def stream_chunk(chunk: str):
            await self.bus.publish(cid, envelope("message.chunk", cid, {"id": msg.id, "chunk": chunk}), None)

        narration, audit = await self._narrate(
            calls, cfg, c, seat.id, turn_id, system, convo, news, ctx, combat_notes, plot_notes,
            stream_callback=stream_chunk
        )

        whispers = await flush_outbox(s, ctx)
        linked = await link_text(s, cid, narration)

        msg.content = linked
        
        turn.status, turn.finished_at, turn.narration_message_id = "done", now(), msg.id
        turn.trace = {
            "calls": trace_calls,
            "audit": audit,
            "voice_line": voice_line_text,
            "required": sorted(required),
            "closed": sorted(ctx.closed),
            "combat": combat_notes,
            "plot_clock": plot_notes,
            "world": world_note,
        }
        await s.commit()
        
        return {"ctx": ctx, "messages": [*whispers, msg], "names": names, "ids": [m.id for m in new], "skipped": False}

    async def _narrate(
        self, calls, cfg, c, seat_id, turn_id, system, convo, news, ctx: ToolContext, notes=(), plot_notes=(), stream_callback=None
    ):
        results = _render_results(ctx)
        turn = combat.public_turn(ctx.world)
        prompt = render(
            "narrate.j2",
            results=results,
            scene=ctx.world.scene_table(),
            length="РѕС‚ РѕРґРЅРѕРіРѕ РґРѕ С‡РµС‚С‹СЂС‘С… Р°Р±Р·Р°С†РµРІ",
            combat_notes=list(notes),
            plot_notes=list(plot_notes),
            next_turn=turn["name"] if turn else None,
        )
        base = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": f"РќРµРґР°РІРЅРёРµ СЃРѕРѕР±С‰РµРЅРёСЏ С‡Р°С‚Р°:\n{convo or 'РїРѕРєР° РЅРµС‚'}\n\n"
                f"Р РµРїР»РёРєРё РёРіСЂРѕРєРѕРІ СЌС‚РѕРіРѕ С…РѕРґР°:\n{news}\n\n{prompt}",
            },
        ]
        known = set(ctx.world.characters) | set(ctx.world.entities)
        audit: dict[str, Any] = {"regenerated": False, "stripped": []}
        reply = await self._ask(calls, cfg, c.id, seat_id, turn_id, "narrate", base, None, stream_callback=stream_callback)
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
                        f"Р’ С‚РµРєСЃС‚Рµ СЂР°Р·РјРµС‡РµРЅС‹ СЃСѓС‰РЅРѕСЃС‚Рё, РєРѕС‚РѕСЂС‹С… РЅРµС‚ РІ СЂРµРµСЃС‚СЂРµ: {', '.join(unknown)}. РџРµСЂРµРїРёС€Рё РѕС‚РІРµС‚: "
                        "СЂР°Р·РјРµС‡Р°Р№ С‚РѕР»СЊРєРѕ id РёР· С‚Р°Р±Р»РёС†С‹ СЃС†РµРЅС‹, РЅРѕРІС‹С… СЃСѓС‰РµСЃС‚РІ Рё РїСЂРµРґРјРµС‚РѕРІ РЅРµ РІРІРѕРґРё."
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
        # РћС‡РёСЃС‚РєР° РѕС‚ СЃР»СѓС‡Р°Р№РЅС‹С… РІС‹Р·РѕРІРѕРІ РёРЅСЃС‚СЂСѓРјРµРЅС‚РѕРІ РІ С‚РµРєСЃС‚Рµ РјР°СЃС‚РµСЂР° (РЅР°РїСЂРёРјРµСЂ, set_soundscape {...})
        text = re.sub(r"^\s*[a-z_]+\s*\{.*?\}\s*", "", text, flags=re.DOTALL).strip()
        # РћС‡РёСЃС‚РєР° РѕС‚ РѕР±РѕСЂРІР°РЅРЅРѕРіРѕ РЅРµР·Р°РєСЂС‹С‚РѕРіРѕ С‚РµРіР° СЂР°Р·РјРµС‚РєРё РІ РєРѕРЅС†Рµ С‚РµРєСЃС‚Р°
        text = re.sub(r"\[\[[^\]]*$", "", text).rstrip()
        return text or "вЂ¦", audit

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
        lite_model = None
        custom_voice_model = (cfg.settings or {}).get("voice_line_model")
        if custom_voice_model:
            try:
                lite_model = model_for(None, custom_voice_model)
            except Exception:
                pass
        if not lite_model:
            voice_defaults = {
                "gemini": "gemini-3.5-flash-lite",
                "claude": "anthropic/claude-haiku-4-5",
            }
            default_candidate = voice_defaults.get(cfg.provider)
            if default_candidate:
                try:
                    lite_model = model_for(None, default_candidate)
                except Exception:
                    pass

        msgs = [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]
        reply = await self._ask(
            calls, cfg, c.id, seat_id, turn_id, "voice_line", msgs, None, override_model=lite_model
        )
        text = reply.text.strip().strip("\"'В«В»вЂ”вЂ“- ").strip()
        text = MARKUP.sub(r"\2", text)
        return text or "Р’РїРµСЂС‘Рґ!"

    async def _system_prompt(self, s, c: Campaign, cfg: AgentConfig, ctx: ToolContext) -> str:
        secret = await s.get(CampaignSecret, c.id)
        secrets = ""
        has_plot = bool(secret and plot.has_plan(secret.plot))
        if has_plot:
            # В«РЎСЋР¶РµС‚ СЃРµР№С‡Р°СЃВ» вЂ” С‚РµРєСѓС‰РёР№ Р°РєС‚ Рё С‡С‚Рѕ СЂСЏРґРѕРј; РІРµСЃСЊ РєР°СЂРєР°СЃ РјР°СЃС‚РµСЂ С‡РёС‚Р°РµС‚ С‡РµСЂРµР· get_plot
            extra = json.dumps(secret.setting, ensure_ascii=False)[:4000] if secret.setting else ""
            now_ = plot.now_block(secret.plot, location_entity_id=ctx.world.scene.location_id)
            secrets = (now_ + ("\n" + extra if extra else ""))[:16000]
        elif secret and (secret.setting or secret.plot):
            secrets = json.dumps({"setting": secret.setting, "plot": secret.plot}, ensure_ascii=False)[:12000]
        ties = [
            f"{ch.name} ({ch.id}):\n{text}"
            for ch in ctx.world.characters.values()
            if ch.status in ("approved", "active") and (text := bonds.render(ch, private=True))
        ]
        if ties:
            secrets = (secrets + "\n" if secrets else "") + "РЎРІСЏР·Рё РіРµСЂРѕРµРІ (РѕС‚РІРµС‚С‹ РёРіСЂРѕРєРѕРІ):\n" + "\n".join(ties)
        # С…Р°СЂР°РєС‚РµСЂС‹ РіРµСЂРѕРµРІ (Р°РЅРєРµС‚Р° Рё Р»РµС‚РѕРїРёСЃСЊ) РјР°СЃС‚РµСЂ РІРёРґРёС‚, РєР°Рє РІРёРґРёС‚ Р»РёСЃС‚: С‡С‚РѕР±С‹ NPC Рё СЃС†РµРЅС‹ С†РµРїР»СЏР»Рё РіРµСЂРѕРµРІ
        chars = []
        for ch in ctx.world.characters.values():
            if ch.status not in ("approved", "active"):
                continue
            if text := persona.render(ch.persona, await persona.notes_of(s, c.id, ch.id)):
                chars.append(f"{ch.name} ({ch.id}):\n{text}")
        if chars:
            secrets = (secrets + "\n" if secrets else "") + "РҐР°СЂР°РєС‚РµСЂС‹ РіРµСЂРѕРµРІ:\n" + "\n".join(chars)
        style = cfg.persona or ""
        own = persona.render((cfg.settings or {}).get("character"), await persona.notes_of(s, c.id, None), master=True)
        if own:
            style = (style + "\n\n" if style else "") + "РўРІРѕР№ С…Р°СЂР°РєС‚РµСЂ РєР°Рє РјР°СЃС‚РµСЂР°:\n" + own
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
            leveling=progress_tools.leveling(c),
            random_events=fortune_tools.random_events(c),
            audio=audio.prompt_block(c, ctx.world.scene),
        )

    # --- РїР°РјСЏС‚СЊ (СЂР°Р·РґРµР» 9) ---

    async def _memory_block(self, s, c: Campaign, ctx: ToolContext, new: list[Message]) -> str:
        """РЎРІРѕРґРєР° РєР°РјРїР°РЅРёРё Рё С„СЂР°РіРјРµРЅС‚С‹ РїСЂР°РІРёР» Рё Р»РѕСЂР°, РЅР°Р№РґРµРЅРЅС‹Рµ РїРѕ РЅРѕРІС‹Рј СЂРµРїР»РёРєР°Рј Рё РјРµСЃС‚Сѓ РґРµР№СЃС‚РІРёСЏ."""
        parts = []
        last = await memory.latest(s, c.id)
        text = memory.render_content(last.content) if last else ""
        if text:
            parts.append("РЎРІРѕРґРєР° РєР°РјРїР°РЅРёРё (Р±РµР· С‡РёСЃРµР»: С‡РёСЃР»Р° С‚РѕР»СЊРєРѕ РІ С‚Р°Р±Р»РёС†Рµ СЃС†РµРЅС‹):\n" + text)
        loc = ctx.world.entities.get(ctx.world.scene.location_id or "")
        query = " ".join(
            [m.content for m in new]
            + [intents.describe(m.intent) for m in new if m.intent]
            + ([loc.name] if loc else [])
        )
        found = memory.knowledge_block(ctx.world.catalog, query)
        if found:
            parts.append(found)
        return "".join(p + "\n\n" for p in parts)

    async def summarize(self, cid: str, kind: str = "rolling", *, session_id: str | None = None, force=False):
        """РќРѕРІР°СЏ РІРµСЂСЃРёСЏ СЃРІРѕРґРєРё. ``rolling`` вЂ” С‚РѕР»СЊРєРѕ РµСЃР»Рё РЅР°Р±СЂР°Р»РѕСЃСЊ ``summary_every`` РїСѓР±Р»РёС‡РЅС‹С… СЃРѕРѕР±С‰РµРЅРёР№,
        ``session`` вЂ” РІ РєРѕРЅС†Рµ СЃРµСЃСЃРёРё, РµСЃР»Рё РµСЃС‚СЊ С‡С‚Рѕ РґРѕР±Р°РІРёС‚СЊ. РЎР±РѕР№ РјРѕРґРµР»Рё СЃРІРѕРґРєСѓ РїСЂРѕСЃС‚Рѕ РїСЂРѕРїСѓСЃРєР°РµС‚."""
        if cid in self._summarizing:
            return None
        self._summarizing.add(cid)
        try:
            async with self.maker() as s:
                c = await s.get(Campaign, cid)
                seat = master_seat(c) if c else None
                if c is None or seat is None or seat.occupant_type != "agent":
                    return None
                prev = await memory.latest(s, cid)
                after = prev.upto_seq if prev else 0
                every = int((c.settings or {}).get("summary_every") or memory.SUMMARY_EVERY)
                rows = await memory.public_messages(s, cid, after)
                if not rows or (kind == "rolling" and not force and len(rows) < every):
                    return None
                cfg = await s.get(AgentConfig, seat.agent_config_id)
                ctx = await open_context(s, c, self.dice_factory(), turn_id=None, seat_id=seat.id)
                char_by_seat = {ch.seat_id: ch for ch in ctx.world.characters.values() if ch.seat_id}
                names = await _names(s, c)
                prompt = memory.summary_input(prev, rows, lambda m: _who(m, char_by_seat, names))
                upto = rows[-1].seq
                prev_version = prev.version if prev else 0
                model = parser_model_for()
                master_seat_id = seat.id
                api_base = (cfg.settings or {}).get("api_base")
                await s.rollback()
            call = LlmCall(campaign_id=cid, seat_id=master_seat_id, turn_id=None, purpose="summary", model=model)
            content = None
            try:
                reply = await self.llm.complete(
                    [{"role": "system", "content": memory.SUMMARY_SYSTEM}, {"role": "user", "content": prompt}],
                    model=model,
                    tools=[memory.tool_spec()],
                    max_tokens=2000,
                    temperature=0.2,
                    api_base=api_base,
                )
                call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
                call.cost, call.latency_ms = reply.cost, reply.latency_ms
                raw = next((t.arguments for t in reply.tool_calls if t.name == "submit_summary"), None)
                content = memory.check(raw) if raw is not None else None
                if content is None:
                    call.error = "СЃРІРѕРґРєР° РЅРµ РїСЂРѕС€Р»Р° СЃС…РµРјСѓ"
            except LLMError as e:
                call.error = str(e)[:2000]
            async with self.maker() as s:
                s.add(call)
                row = None
                if content is not None:
                    row = Summary(
                        campaign_id=cid,
                        session_id=session_id,
                        kind=kind,
                        version=prev_version + 1,
                        upto_seq=upto,
                        content=content,
                    )
                    s.add(row)
                await s.commit()
                row_id = row.id if row else None
            if row_id and kind == "session":
                # РёС‚РѕРі СЃРµСЃСЃРёРё РІСЃРµРј Р·Р° СЃС‚РѕР»РѕРј: СЃРІРѕРґРєР° СЃС‚СЂРѕРёС‚СЃСЏ С‚РѕР»СЊРєРѕ РёР· РїСѓР±Р»РёС‡РЅС‹С… СЃРѕРѕР±С‰РµРЅРёР№
                await self.bus.publish(cid, envelope("session.summary", cid, memory.public_summary(content)), None)
            return row_id
        except Exception:  # noqa: BLE001 вЂ” СЃРІРѕРґРєР° РЅРµ РґРѕР»Р¶РЅР° СЂРѕРЅСЏС‚СЊ С…РѕРґ
            log.exception("СЃРІРѕРґРєР° РєР°РјРїР°РЅРёРё %s РЅРµ СѓРґР°Р»Р°СЃСЊ", cid)
            return None
        finally:
            self._summarizing.discard(cid)

    # --- СЃРІРѕРґРєР° РїСЂРѕРїСѓС‰РµРЅРЅРѕРіРѕ (СЂР°Р·РґРµР» 11) ---

    async def catch_up(self, cid: str, seat_id: str, from_seq: int) -> str | None:
        """РРіСЂРѕРє РІРµСЂРЅСѓР»СЃСЏ РїРѕСЃР»Рµ РѕС„Р»Р°Р№РЅР°: РєРѕСЂРѕС‚РєР°СЏ СЃРІРѕРґРєР° С‚РѕРіРѕ, С‡С‚Рѕ РѕРЅ РїСЂРѕРїСѓСЃС‚РёР», С‚РѕР»СЊРєРѕ РµРјСѓ. РџРёС€РµС‚ РґРµС€С‘РІР°СЏ РјРѕРґРµР»СЊ
        РР-РјР°СЃС‚РµСЂР°; Сѓ Р¶РёРІРѕРіРѕ РјР°СЃС‚РµСЂР° РјРѕРґРµР»Рё РЅРµС‚ вЂ” С‚РѕРіРґР° Р±РµР· РјРѕРґРµР»Рё: СЃРєРѕР»СЊРєРѕ РїСЂРѕРїСѓС‰РµРЅРѕ Рё РїРѕСЃР»РµРґРЅСЏСЏ СЃС†РµРЅР°."""
        from app.core.chat import visible

        async with self.maker() as s:
            c = await s.get(Campaign, cid)
            if c is None:
                return None
            q = select(Message).where(Message.campaign_id == cid, Message.seq > from_seq).order_by(Message.seq)
            rows = [m for m in (await s.scalars(q.limit(200))).all() if visible(m, seat_id) and m.kind != "ooc"]
            if not rows:
                return None
            seat = master_seat(c)
            cfg = await s.get(AgentConfig, seat.agent_config_id) if seat.agent_config_id else None
            chars = (await s.scalars(select(Character).where(Character.campaign_id == cid))).all()
            char_by_seat = {ch.seat_id: ch for ch in chars if ch.seat_id}
            names = await _names(s, c)
            lines = [_who(m, char_by_seat, names) + ": " + MARKUP.sub(r"\2", m.content) for m in rows]
            last = next((m.content for m in reversed(rows) if m.kind == "narration"), None)
            master_seat_id, missed = seat.id, len(rows)
            api_base = (cfg.settings or {}).get("api_base") if cfg is not None else None
            model = parser_model_for() if cfg is not None else None
            await s.rollback()
        text = None
        if model is not None:
            call = LlmCall(campaign_id=cid, seat_id=master_seat_id, turn_id=None, purpose="catchup", model=model)
            try:
                reply = await self.llm.complete(
                    [{"role": "system", "content": CATCH_UP_SYSTEM}, {"role": "user", "content": "\n".join(lines)}],
                    model=model,
                    max_tokens=1500,
                    temperature=0.2,
                    api_base=api_base,
                )
                call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
                call.cost, call.latency_ms = reply.cost, reply.latency_ms
                text = MARKUP.sub(r"\2", reply.text or "").strip()[:1200] or None
                if text is None:
                    call.error = "РїСѓСЃС‚Р°СЏ СЃРІРѕРґРєР°"
            except LLMError as e:
                call.error = str(e)[:2000]
            async with self.maker() as s:
                s.add(call)
                await s.commit()
        if text is None:
            text = f"РџСЂРѕРїСѓС‰РµРЅРѕ СЃРѕРѕР±С‰РµРЅРёР№: {missed}."
            if last is not None:
                scene = MARKUP.sub(r"\2", last).strip()
                text += " РџРѕСЃР»РµРґРЅРµРµ РѕС‚ РјР°СЃС‚РµСЂР°: В«" + (scene[:400] + "вЂ¦" if len(scene) > 400 else scene) + "В»"
        async with self.maker() as s:
            msg = Message(
                campaign_id=cid,
                session_id=(g.id if (g := await active_session(s, cid)) else None),
                seq=await next_seq(s, cid),
                kind="system",
                visible_to=[seat_id],
                content="РџРѕРєР° РІР°СЃ РЅРµ Р±С‹Р»Рѕ. " + text,
                data={"catch_up": True},
            )
            s.add(msg)
            await s.commit()
        await publish_message(self.bus, msg)
        return msg.id

    # --- РїР°СЂСЃРµСЂ РЅР°РјРµСЂРµРЅРёР№ (СЂР°Р·РґРµР» 6) ---

    async def parse_intent(self, cid: str, seat_id: str | None, text: str) -> intents.ParseResult:
        """Р Р°Р·Р±РёСЂР°РµС‚ РґРµР№СЃС‚РІРёРµ РёРіСЂРѕРєР° РґРѕ Р·Р°РїРёСЃРё РІ С‡Р°С‚. РўРѕР»СЊРєРѕ РїСЂРё РР-РјР°СЃС‚РµСЂРµ: Сѓ Р¶РёРІРѕРіРѕ РјР°СЃС‚РµСЂР° РјРѕРґРµР»Рё РЅРµС‚.
        Р›СЋР±РѕР№ СЃР±РѕР№ РїР°СЂСЃРµСЂР° вЂ” СЂРµРїР»РёРєР° РїСЂРѕС…РѕРґРёС‚ Р±РµР· РЅР°РјРµСЂРµРЅРёСЏ."""
        async with self.maker() as s:
            c = await s.get(Campaign, cid)
            seat = master_seat(c) if c else None
            if c is None or seat is None or seat.occupant_type != "agent" or seat_id is None:
                return intents.ParseResult()
            if await active_session(s, cid) is None:
                return intents.ParseResult()  # РІРЅРµ СЃРµСЃСЃРёРё РґРµР№СЃС‚РІРёРµ РІСЃС‘ СЂР°РІРЅРѕ РЅРµ РїСЂРёРјСѓС‚
            cfg = await s.get(AgentConfig, seat.agent_config_id)
            ctx = await open_context(s, c, self.dice_factory(), turn_id=None, seat_id=seat.id)
            ch = next(
                (
                    x
                    for x in ctx.world.characters.values()
                    if x.seat_id == seat_id and x.status in ("approved", "active")
                ),
                None,
            )
            if ch is None:
                return intents.ParseResult()
            info, values = intents.context_for(ctx.world, ch)
            ch_id, provider, cfg_model, master_seat_id = ch.id, cfg.provider, cfg.model, seat.id
            api_base = (cfg.settings or {}).get("api_base")
            await s.rollback()
        model = parser_model_for()
        call = LlmCall(campaign_id=cid, seat_id=master_seat_id, turn_id=None, purpose="parse", model=model)
        try:
            reply = await asyncio.wait_for(
                self._parse_call(model, info, text, values, api_base, provider=provider), timeout=PARSE_TIMEOUT
            )
        except TimeoutError:
            call.error = f"РїР°СЂСЃРµСЂ РЅРµ РѕС‚РІРµС‚РёР» Р·Р° {PARSE_TIMEOUT} СЃ"
            reply = None
        except LLMError as e:
            call.error = str(e)[:2000]
            reply = None
        if reply is not None:
            call.model, call.tokens_in, call.tokens_out = reply.model, reply.tokens_in, reply.tokens_out
            call.cost, call.latency_ms = reply.cost, reply.latency_ms
        raw = next((t.arguments for t in (reply.tool_calls if reply else []) if t.name == "submit_intent"), None)
        async with self.maker() as s:
            s.add(call)
            await s.commit()
            if raw is None:
                return intents.ParseResult(notes=["РїР°СЂСЃРµСЂ РЅРµ РѕС‚РІРµС‚РёР»"])
            c = await s.get(Campaign, cid)
            ctx = await open_context(s, c, self.dice_factory(), turn_id=None, seat_id=seat_id)
            ch = ctx.world.characters.get(ch_id)
            if ch is None:
                return intents.ParseResult()
            return intents.check(raw, ctx.world, ch)

    async def _parse_call(
        self,
        model: str,
        info: str,
        text: str,
        values: dict,
        api_base: str | None = None,
        provider: str | None = None,
    ) -> LLMReply:
        tool_choice = {"type": "function", "function": {"name": "submit_intent"}} if provider == "gemini" else None
        return await self.llm.complete(
            [
                {"role": "system", "content": intents.PARSER_SYSTEM},
                {"role": "user", "content": f"{info}\n\nР РµРїР»РёРєР° РёРіСЂРѕРєР°:\n{text}"},
            ],
            model=model,
            tools=[intents.tool_spec(values)],
            tool_choice=tool_choice,
            max_tokens=500,
            temperature=0.0,
            api_base=api_base,
        )

    # --- РїРѕС€Р°РіРѕРІС‹Р№ СЂРµР¶РёРј: С…РѕРґ, С‚Р°Р№РјР°СѓС‚, СЂРµР°РєС†РёРё (СЂР°Р·РґРµР» 5, 7.2) ---

    async def after_turn(self, ctx: ToolContext) -> None:
        """РџРѕСЃР»Рµ С„РёРєСЃР°С†РёРё С…РѕРґР°: РІСЃРµРј вЂ” С‡РµР№ С…РѕРґ, Рё С‚Р°Р№РјРµСЂ С…РѕРґР° РіРµСЂРѕСЏ."""
        cid = ctx.campaign.id
        turn = combat.public_turn(ctx.world)
        await self.bus.publish(cid, envelope("turn.changed", cid, {"turn": turn}), None)
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
        """РЎРёР»СЊРЅРѕРµ СЃРѕР±С‹С‚РёРµ вЂ” РіРёР±РµР»СЊ РіРµСЂРѕСЏ, РєРѕРЅРµС† Р±РѕСЏ РёР»Рё РјРѕРјРµРЅС‚, РѕС‚РјРµС‡РµРЅРЅС‹Р№ РјР°СЃС‚РµСЂРѕРј (``mark_moment``):
        Р»РµС‚РѕРїРёСЃСЊ С…Р°СЂР°РєС‚РµСЂР° РїРёС€РµС‚СЃСЏ СЃСЂР°Р·Сѓ, РЅРµ Р¶РґС‘С‚ РєРѕРЅС†Р° СЃРµСЃСЃРёРё."""
        cid = ctx.campaign.id
        heroes = ctx.world.characters.values()
        dead = frozenset(ch.id for ch in heroes if ch.status == "dead" or (ch.resources or {}).get("dead"))
        mode = ctx.world.scene.mode
        before = self._seen.get(cid)
        self._seen[cid] = (dead, mode)
        reasons = []
        if before is not None:
            reasons += [f"РїР°Р» РіРµСЂРѕР№ {ctx.world.characters[i].name}" for i in dead - before[0]]
            if before[1] == "combat" and mode != "combat":
                reasons.append("Р±РѕР№ Р·Р°РєРѕРЅС‡РёР»СЃСЏ")
        for ev in ctx.events:
            if ev.tool == "mark_moment":
                p = ev.payload or {}
                reasons.append(f"{p.get('label') or 'СЃРёР»СЊРЅС‹Р№ РјРѕРјРµРЅС‚'}: {p.get('text') or ''}".rstrip(": "))
        if reasons:
            self._spawn(self._safe(character.chronicle(self, cid, "; ".join(reasons)), "Р»РµС‚РѕРїРёСЃСЊ"))

    async def _timeout_after(self, cid: str, marker: str | None, deadline: float) -> None:
        try:
            await asyncio.sleep(max(0.0, deadline - time.time()))
            await self.run_timeout(cid, marker)
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001
            log.exception("С‚Р°Р№РјР°СѓС‚ С…РѕРґР° РІ РєР°РјРїР°РЅРёРё %s", cid)

    async def resume_timers(self) -> None:
        """РџРѕСЃР»Рµ РїРµСЂРµР·Р°РїСѓСЃРєР° СЃРµСЂРІРµСЂР°: СЃРЅРѕРІР° Р·Р°РІРµСЃС‚Рё С‚Р°Р№РјРµСЂС‹ С…РѕРґРѕРІ РІ РёРґСѓС‰РёС… Р±РѕСЏС…."""
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
        """Р’СЂРµРјСЏ С…РѕРґР° РіРµСЂРѕСЏ РІС‹С€Р»Рѕ: РґРµР№СЃС‚РІРёРµ РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ вЂ” В«РІС‹Р¶РёРґР°РµС‚В», Р·Р°С‚РµРј С…РѕРґСЏС‚ СЃСѓС‰РµСЃС‚РІР°."""
        return await self.advance(cid, "timeout", marker=marker)

    async def advance(self, cid: str, reason: str, *, marker: str | None = None, seat_id: str | None = None):
        """РЎРґРІРёРіР°РµС‚ РѕС‡РµСЂРµРґСЊ Р±РѕСЏ Р±РµР· Р·Р°СЏРІРєРё РіРµСЂРѕСЏ Рё РїСЂРѕРІРѕРґРёС‚ С…РѕРґС‹ СЃСѓС‰РµСЃС‚РІ РґРѕ СЃР»РµРґСѓСЋС‰РµРіРѕ РіРµСЂРѕСЏ.

        ``timeout`` вЂ” РІС‹С€Р»Рѕ РІСЂРµРјСЏ (РіРµСЂРѕР№ РІС‹Р¶РёРґР°РµС‚); ``pass`` вЂ” РёРіСЂРѕРє СЃР°Рј РїСЂРѕРїСѓСЃС‚РёР» С…РѕРґ (С‚РѕР»СЊРєРѕ РјРµСЃС‚Рѕ РіРµСЂРѕСЏ, С‡РµР№ С…РѕРґ);
        ``master`` вЂ” Р¶РёРІРѕР№ РјР°СЃС‚РµСЂ Р·Р°РєСЂС‹Р» С…РѕРґ РіРµСЂРѕСЏ; ``sync`` вЂ” РѕС‡РµСЂРµРґСЊ С‚РѕР»СЊРєРѕ С‡С‚Рѕ СЃРѕР±СЂР°РЅР°: РїРµСЂРІС‹РјРё РјРѕРіСѓС‚ Р±С‹С‚СЊ СЃСѓС‰РµСЃС‚РІР°;
        ``away`` вЂ” РёРіСЂРѕРє РіРµСЂРѕСЏ, С‡РµР№ С…РѕРґ, СѓС€С‘Р» РёР· СЃРµС‚Рё (СЂР°Р·РґРµР» 11).
        Р’РѕР·РІСЂР°С‰Р°РµС‚ id С…РѕРґР° РјР°СЃС‚РµСЂР° РёР»Рё None, РµСЃР»Рё СЃРґРІРёРіР°С‚СЊ РЅРµС‡РµРіРѕ."""
        lock = self._locks.setdefault(cid, asyncio.Lock())
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
                        return None  # РіРµСЂРѕР№ СѓСЃРїРµР» Р·Р°СЏРІРёС‚СЊ РґРµР№СЃС‚РІРёРµ: С…РѕРґ РІРµРґС‘С‚ РјР°СЃС‚РµСЂ
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
                        return None  # РёРіСЂРѕРє СѓСЃРїРµР» РІРµСЂРЅСѓС‚СЊСЃСЏ, РёР»Рё РіРµСЂРѕСЏ СѓР¶Рµ РІРµРґС‘С‚ РґСЂСѓРіРѕР№
                    notes: list[str] = []
                    if hero is not None and reason != "sync":
                        what = {
                            "timeout": "РІС‹Р¶РёРґР°РµС‚",
                            "pass": "РїСЂРѕРїСѓСЃРєР°РµС‚ С…РѕРґ",
                            "master": "Р·Р°РІРµСЂС€Р°РµС‚ С…РѕРґ",
                            "away": "РїСЂРѕРїСѓСЃРєР°РµС‚ С…РѕРґ: РёРіСЂРѕРє РІРЅРµ СЃРµС‚Рё",
                        }[reason]
                        await ctx.record("turn_end", actor_id=hero.id, payload={"reason": reason, "action": what})
                        if reason == "timeout":
                            notes.append(f"РІСЂРµРјСЏ С…РѕРґР° {hero.name} РІС‹С€Р»Рѕ: {hero.name} РІС‹Р¶РёРґР°РµС‚")
                        elif reason == "pass":
                            notes.append(f"{hero.name} РїСЂРѕРїСѓСЃРєР°РµС‚ С…РѕРґ")
                        elif reason == "away":
                            notes.append(f"{hero.name} РїСЂРѕРїСѓСЃРєР°РµС‚ С…РѕРґ: РёРіСЂРѕРє РІРЅРµ СЃРµС‚Рё")
                        await combat.finish_turn(ctx, notes)
                    await self._status(cid, "rolling")
                    notes += await combat.run_until_hero(ctx, f"{turn.id}:combat", self._ask_reaction)
                    names = await _names(s, c)
                    messages = await flush_outbox(s, ctx)
                    acted = [e for e in ctx.events if e.tool != "turn_end"]
                    msg = None
                    if seat.occupant_type == "agent" and acted:
                        cfg = await s.get(AgentConfig, seat.agent_config_id)
                        await self._status(cid, "describing")
                        system = await self._system_prompt(s, c, cfg, ctx)
                        news = "- " + "\n- ".join(notes) if notes else "РЅРµС‚"
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
        """РљРЅРѕРїРєР° СЂРµР°РєС†РёРё РёРіСЂРѕРєСѓ СЃ С‚Р°Р№РјРµСЂРѕРј (РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ 15 СЃ). РќРµС‚ РѕС‚РІРµС‚Р° вЂ” СЂРµР°РєС†РёСЏ РЅРµ РёСЃРїРѕР»СЊР·СѓРµС‚СЃСЏ."""
        if not ch.seat_id:
            return False
        seat = next((x for x in ctx.campaign.seats if x.id == ch.seat_id), None)
        if seat is not None and seat.role == "player" and seat.occupant_type == "agent":
            return not seat.delegated_from  # РР-РёРіСЂРѕРє Р±СЊС‘С‚ РІСЃР»РµРґ; Р·Р° СѓС€РµРґС€РµРіРѕ РёРіСЂРѕРєР° вЂ” РѕСЃС‚РѕСЂРѕР¶РЅРѕ, РЅРµ Р±СЊС‘С‚
        cid = ctx.campaign.id
        wait = float((ctx.campaign.settings or {}).get("reaction_sec") or combat.REACTION_SEC)
        prompt_id = "rx_" + uuid.uuid4().hex[:12]
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._reactions[prompt_id] = (cid, ch.seat_id, fut, None)
        hero = ctx.world.actor(ch.id)
        payload = {
            "prompt_id": prompt_id,
            "character_id": ch.id,
            "trigger": f"В«{creature.name}В» РІС‹С…РѕРґРёС‚ РёР· Р±Р»РёР¶РЅРµРіРѕ Р±РѕСЏ",
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
        """РћС‚РєСЂС‹С‚Р°СЏ РєРЅРѕРїРєР° СЂРµР°РєС†РёРё СЌС‚РѕРіРѕ РјРµСЃС‚Р°, РµСЃР»Рё РµСЃС‚СЊ."""
        for c, seat, fut, payload in self._reactions.values():
            if c == cid and seat == seat_id and payload is not None and not fut.done():
                return payload
        return None

    # --- РїСЂРѕРІРµСЂРєР° РїРµСЂСЃРѕРЅР°Р¶Р° РР-РјР°СЃС‚РµСЂРѕРј (СЂР°Р·РґРµР» 5.1) ---

    async def review_character(self, cid: str, character_id: str) -> str | None:
        """РџСЂРѕРІРµСЂРєР° РіРµСЂРѕСЏ РР-РјР°СЃС‚РµСЂРѕРј. Р•СЃР»Рё РјРѕРґРµР»СЊ РЅРµРґРѕСЃС‚СѓРїРЅР° РёР»Рё С‚Р°Рє Рё РЅРµ РІС‹РЅРµСЃР»Р° СЂРµС€РµРЅРёСЏ, РіРµСЂРѕР№ РѕСЃС‚Р°С‘С‚СЃСЏ
        РЅР° РїСЂРѕРІРµСЂРєРµ, Р° РїСЂРёС‡РёРЅР° РїРёС€РµС‚СЃСЏ РІ Р¶СѓСЂРЅР°Р» Рё РІРёРґРЅР° РёРіСЂРѕРєСѓ Рё РІР»Р°РґРµР»СЊС†Сѓ: РІР»Р°РґРµР»РµС† РјРѕР¶РµС‚ РїСЂРѕРІРµСЂРёС‚СЊ СЃР°Рј."""
        lock = self._locks.setdefault(cid, asyncio.Lock())
        async with lock:
            calls: list[LlmCall] = []
            error = None
            try:
                attempted, status = await self._review(cid, character_id, calls)
                if attempted and not status:
                    error = "РјРѕРґРµР»СЊ РЅРµ РІС‹РЅРµСЃР»Р° СЂРµС€РµРЅРёСЏ Р·Р° С‚СЂРё РїРѕРїС‹С‚РєРё"
            except asyncio.CancelledError:
                raise
            except LLMError as e:
                attempted, status, error = True, None, explain(str(e))
            except Exception as e:  # noqa: BLE001 вЂ” СЃР±РѕР№ РїСЂРѕРІРµСЂРєРё РЅРµ РґРѕР»Р¶РµРЅ С‚РµСЂСЏС‚СЊСЃСЏ РјРѕР»С‡Р°
                log.exception("РїСЂРѕРІРµСЂРєР° РіРµСЂРѕСЏ %s СЃРѕСЂРІР°Р»Р°СЃСЊ", character_id)
                attempted, status, error = True, None, f"{type(e).__name__}: {e}"[:500]
            finally:
                if calls:
                    async with self.maker() as s:
                        s.add_all(calls)
                        await s.commit()
            if error:
                async with self.maker() as s:
                    failed = {"error": error}
                    s.add(Event(campaign_id=cid, tool="review_failed", target_id=character_id, payload=failed))
                    await s.commit()
                await self.bus.publish(
                    cid, envelope("character.review_failed", cid, {"character_id": character_id, "error": error}), None
                )
            return status

    async def _review(self, cid: str, character_id: str, calls: list) -> tuple[bool, str | None]:
        """РР-РїСЂРѕРІРµСЂРєР° РіРµСЂРѕСЏ. РЎРµСЃСЃРёСЏ Р‘Р” РЅРµ РґРµСЂР¶РёС‚СЃСЏ РІРѕ РІСЂРµРјСЏ РѕР±СЂР°С‰РµРЅРёСЏ Рє РјРѕРґРµР»Рё: РІ SQLite РѕС‚РєСЂС‹С‚Р°СЏ С‚СЂР°РЅР·Р°РєС†РёСЏ
        РЅРµ РґР°С‘С‚ РґСЂСѓРіРёРј РїРёСЃР°С‚СЊ, Рё РёРіСЂРѕРєРё РїРѕР»СѓС‡Р°Р»Рё В«database is lockedВ», РїРѕРєР° РјРѕРґРµР»СЊ РґСѓРјР°Р»Р°."""
        from app.core.characters import full_view

        async with self.maker() as s:
            c = await s.get(Campaign, cid)
            seat = master_seat(c)
            if seat.occupant_type != "agent":
                return False, None
            seat_id = seat.id
            cfg = await s.get(AgentConfig, seat.agent_config_id)
            ctx = await open_context(s, c, self.dice_factory(), turn_id=None, seat_id=seat_id)
            ch = ctx.world.characters.get(character_id)
            if ch is None or ch.status != "submitted":
                return False, None
            sheet = full_view(ch, ctx.world.catalog, ctx.world.inventory.get(ch.id, []), [])
            world = _world_choices(ctx.world.catalog)
            system = await self._system_prompt(s, c, cfg, ctx)
            tools = tool_specs(ctx.world, ["review_character"])
            s.expunge(cfg)  # РЅСѓР¶РµРЅ Рё РїРѕСЃР»Рµ Р·Р°РєСЂС‹С‚РёСЏ СЃРµСЃСЃРёРё: РїСЂРѕРІР°Р№РґРµСЂ, РјРѕРґРµР»СЊ, РЅР°СЃС‚СЂРѕР№РєРё
        msgs = [
            {"role": "system", "content": system},
            {
                "role": "user",
                "content": (
                    "РРіСЂРѕРє РїСЂРёСЃР»Р°Р» РїРµСЂСЃРѕРЅР°Р¶Р° РЅР° РїСЂРѕРІРµСЂРєСѓ. РџСЂР°РІРёР»Р° СЃРµСЂРІРµСЂ СѓР¶Рµ РїСЂРѕРІРµСЂРёР». РћС†РµРЅРё РёСЃС‚РѕСЂРёСЋ Рё "
                    "СЃРѕРѕС‚РІРµС‚СЃС‚РІРёРµ СЃРµС‚С‚РёРЅРіСѓ Рё РІС‹Р·РѕРІРё review_character: РѕРґРѕР±СЂРё РёР»Рё РІРµСЂРЅРё СЃ РєРѕРјРјРµРЅС‚Р°СЂРёРµРј. "
                    "РЎРѕРѕС‚РІРµС‚СЃС‚РІРёРµ РјРёСЂСѓ РїСЂРѕРІРµСЂСЏР№ РїРѕ РµРіРѕ С„Р°РєС‚Р°Рј: РєР»Р°СЃСЃ Рё РїСЂРѕРёСЃС…РѕР¶РґРµРЅРёРµ РІР·СЏС‚С‹ РёР· СЃРїРёСЃРєРѕРІ РјРёСЂР°, РЅРѕ "
                    "РёСЃС‚РѕСЂРёСЏ, РІРЅРµС€РЅРѕСЃС‚СЊ Рё С…Р°СЂР°РєС‚РµСЂ РЅРµ РґРѕР»Р¶РЅС‹ РІРІРѕРґРёС‚СЊ С‚Рѕ, С‡РµРіРѕ РІ РјРёСЂРµ РЅРµС‚ (С‡СѓР¶РёРµ СЂР°СЃС‹, РЅР°СЂРѕРґС‹, "
                    "Р±РѕРіРё, РјР°РіРёСЏ РёР»Рё Р·РµРјР»Рё, РїСЂРѕС‚РёРІРѕСЂРµС‡Р°С‰РёРµ Р»РѕСЂСѓ). Р’РѕР·РІСЂР°С‰Р°Р№ С‚РѕР»СЊРєРѕ Р·Р° СЏРІРЅРѕРµ РїСЂРѕС‚РёРІРѕСЂРµС‡РёРµ Рё "
                    "РІ РєРѕРјРјРµРЅС‚Р°СЂРёРё РЅР°Р·РѕРІРё РµРіРѕ Рё РїСЂРµРґР»РѕР¶Рё, РєР°Рє РїРѕРїСЂР°РІРёС‚СЊ РІ РґСѓС…Рµ РјРёСЂР°; СЃС‚РёР»СЊ Рё РјРµР»РѕС‡Рё РЅРµ РїРѕРІРѕРґ.\n"
                    + world
                    + "\n"
                    "РњРѕР¶РµС€СЊ С‚Р°Р№РЅРѕ СЃРІСЏР·Р°С‚СЊ РёСЃС‚РѕСЂРёСЋ РіРµСЂРѕСЏ СЃ СЃСЋР¶РµС‚РѕРј С‡РµСЂРµР· secret_link, Р° РµСЃР»Рё РµСЃС‚СЊ РєР°СЂРєР°СЃ вЂ” "
                    "РїСЂРёРІСЏР·Р°С‚СЊ СЌС‚Сѓ СЃРІСЏР·СЊ Рє СѓР·Р»Сѓ, NPC, Р·Р»РѕРґРµСЋ РёР»Рё РјРµСЃС‚Сѓ РєР°СЂРєР°СЃР° С‡РµСЂРµР· hook_ref.\n\n"
                    + json.dumps(sheet, ensure_ascii=False, default=str)
                ),
            },
        ]
        for _ in range(3):
            reply = await self._ask(calls, cfg, cid, seat_id, None, "review", msgs, tools)
            msgs.append(reply.message or {"role": "assistant", "content": reply.text})
            if not reply.tool_calls:
                msgs.append({"role": "user", "content": "Р’С‹Р·РѕРІРё review_character."})
                continue
            async with self.maker() as s:
                c = await s.get(Campaign, cid)
                ctx = await open_context(s, c, self.dice_factory(), turn_id=None, seat_id=seat_id)
                ch = ctx.world.characters.get(character_id)
                if ch is None or ch.status != "submitted":
                    return False, None  # РїРѕРєР° РјРѕРґРµР»СЊ РґСѓРјР°Р»Р°, РіРµСЂРѕСЏ РїСЂРѕРІРµСЂРёР» С‡РµР»РѕРІРµРє РёР»Рё РёРіСЂРѕРє РµРіРѕ РѕС‚РѕР·РІР°Р»
                status = None
                for call in reply.tool_calls:
                    args = {**call.arguments, "character_id": ch.id}
                    r = (
                        await execute(ctx, "review_character", args)
                        if call.name == "review_character"
                        else {"ok": False, "error": "Р·РґРµСЃСЊ РґРѕСЃС‚СѓРїРµРЅ С‚РѕР»СЊРєРѕ review_character"}
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
                await s.commit()
                if not status:
                    continue
                if ch.seat_id:
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
                return True, status
        return True, None


async def _new_player_messages(s, c: Campaign) -> list[Message]:
    """Р РµРїР»РёРєРё РёРіСЂРѕРєРѕРІ РїРѕСЃР»Рµ РїРѕСЃР»РµРґРЅРµРіРѕ С…РѕРґР° РјР°СЃС‚РµСЂР° (СѓРґР°С‡РЅРѕРіРѕ, РёРґСѓС‰РµРіРѕ РёР»Рё СЃРѕСЂРІР°РІС€РµРіРѕСЃСЏ: СЃРѕСЂРІР°РІС€РёР№СЃСЏ С…РѕРґ
    РїСЂРѕСЃРёС‚ РёРіСЂРѕРєРѕРІ РїРѕРІС‚РѕСЂРёС‚СЊ РґРµР№СЃС‚РІРёРµ, РїРѕСЌС‚РѕРјСѓ РµРіРѕ СЂРµРїР»РёРєРё РІС‚РѕСЂРѕР№ СЂР°Р· РЅРµ Р±РµСЂСѓС‚СЃСЏ)."""
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
        .where(Message.campaign_id == c.id, Message.seq < before_seq, Message.kind.notin_(("ooc", "roll")))
        .order_by(Message.seq.desc())
        .limit(HISTORY)
    )
    return list(reversed(rows.all()))


async def _names(s, c: Campaign) -> dict[str, str]:
    ids = [x.user_id for x in c.seats if x.user_id] + [c.owner_id]
    rows = await s.scalars(select(User).where(User.id.in_(ids)))
    return {u.id: u.name for u in rows}


KIND_RU = {
    "action": "РґРµР№СЃС‚РІРёРµ",
    "speech": "СЂРµС‡СЊ",
    "whisper": "С€С‘РїРѕС‚ РјР°СЃС‚РµСЂСѓ",
    "narration": "РјР°СЃС‚РµСЂ",
    "system": "СЃРёСЃС‚РµРјР°",
}


def _who(m: Message, char_by_seat: dict, names: dict) -> str:
    ch = char_by_seat.get(m.seat_id)
    player = names.get(m.author_user_id or "", "")
    if ch is not None:
        return f"{ch.name} ({ch.id}{', РёРіСЂРѕРє ' + player if player else ''})"
    return player or "РјР°СЃС‚РµСЂ"


def _render_history(rows: list[Message], char_by_seat: dict, names: dict) -> str:
    out = []
    for m in rows:
        if m.kind in ("narration",):
            out.append(f"[РјР°СЃС‚РµСЂ] {m.content}")
        elif m.kind == "system":
            out.append(f"[СЃРёСЃС‚РµРјР°] {m.content}")
        else:
            out.append(f"[{KIND_RU.get(m.kind, m.kind)}] {_who(m, char_by_seat, names)}: {m.content}")
    return "\n".join(out)


def _render_new(rows: list[Message], char_by_seat: dict, names: dict) -> str:
    out = []
    for m in rows:
        note = "" if m.seat_id in char_by_seat else " (Сѓ РёРіСЂРѕРєР° РµС‰С‘ РЅРµС‚ РїРµСЂСЃРѕРЅР°Р¶Р°)"
        out.append(f"- [{KIND_RU.get(m.kind, m.kind)}] {_who(m, char_by_seat, names)}{note}: {m.content}")
        if m.kind == "action" and m.intent:
            out.append(f"  РЅР°РјРµСЂРµРЅРёРµ (СЂР°Р·Р±РѕСЂ РїР°СЂСЃРµСЂР°): {intents.describe(m.intent)}")
    return "\n".join(out)


def _render_results(ctx: ToolContext) -> str:
    out = []
    for ev in ctx.events:
        if ev.tool in AUDIO_TOOLS:
            continue
        res = ev.payload.get("result", ev.payload)
        if ev.tool in plot_tools.PLOT_TOOLS or ev.tool == "threat_clock":
            mark = " [РЎР®Р–Р•Рў: С‚РѕР»СЊРєРѕ РґР»СЏ РјР°СЃС‚РµСЂР°, РїСЂСЏРјРѕ РЅРµ РЅР°Р·С‹РІР°Р№]"
        else:
            mark = " [РЎРљР Р«РўР«Р™ Р‘Р РћРЎРћРљ: РёРіСЂРѕРєР°Рј С‚РѕР»СЊРєРѕ РїРѕСЃР»РµРґСЃС‚РІРёСЏ]" if ev.hidden else ""
        out.append(f"- {ev.tool}{mark}: {json.dumps(res, ensure_ascii=False, default=str)}")
    return "\n".join(out)


