"""Память кампании (ТЗ, раздел 9): сводки и сборка контекста мастера.

Сводку пишет дешёвая модель каждые ``summary_every`` сообщений (по умолчанию 30) и в конце сессии: прошлая сводка +
новые сообщения → новая версия, старые хранятся. В сводку идут только публичные сообщения — шёпоты и скрытые
броски остаются в журнале, поэтому пересказ «Ранее в кампании…» можно показывать всем игрокам. Числа (хиты,
предметы, эффекты) сводка не хранит: мастер всегда берёт их из БД на момент хода.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.core import knowledge
from app.db.models import Message, Summary

log = logging.getLogger(__name__)

SUMMARY_EVERY = 30
SUMMARY_INPUT_LIMIT = 200  # сообщений за раз; больше — значит сводку давно не делали, берём последние
PUBLIC_KINDS = ("action", "speech", "narration", "system")

SUMMARY_SYSTEM = (
    "Ты ведёшь летопись текстовой ролевой игры. Тебе дают прошлую сводку и новые сообщения чата. Верни один вызов "
    "submit_summary с обновлённой сводкой: объедини прошлую с новым, выполненное убери из активного, "
    "пиши коротко и по делу. "
    "Не записывай числа хитов, урона и инвентарь — их хранит игра. Ничего не выдумывай: только то, что есть в тексте. "
    "recap — 2–4 предложения для игроков: что произошло и на чём остановились."
)


class NpcNote(BaseModel):
    name: str = Field(max_length=80)
    relation: str = Field("", max_length=80, description="отношение к героям: друг, враг, должник, торговец")
    note: str = Field("", max_length=200)


class SummaryContent(BaseModel):
    quests: list[str] = Field(default_factory=list, max_length=20, description="активные задания и цели")
    events: list[str] = Field(default_factory=list, max_length=30, description="ключевые события по порядку")
    npcs: list[NpcNote] = Field(default_factory=list, max_length=30)
    threads: list[str] = Field(default_factory=list, max_length=20, description="открытые сюжетные нити, загадки")
    promises: list[str] = Field(default_factory=list, max_length=20, description="обещания и долги героев и NPC")
    recap: str = Field("", max_length=1200, description="пересказ для игроков: 2–4 предложения")


def tool_spec() -> dict[str, Any]:
    schema = SummaryContent.model_json_schema()
    npc = schema.pop("$defs", {}).get("NpcNote", {})
    npc.pop("title", None)
    for p in npc.get("properties", {}).values():
        p.pop("title", None)
    schema.pop("title", None)
    for p in schema["properties"].values():
        p.pop("title", None)
    schema["properties"]["npcs"] = {"type": "array", "items": npc, "maxItems": 30}
    return {
        "type": "function",
        "function": {
            "name": "submit_summary",
            "description": "Обновлённая сводка кампании.",
            "parameters": schema,
        },
    }


async def latest(s, campaign_id: str) -> Summary | None:
    q = select(Summary).where(Summary.campaign_id == campaign_id).order_by(Summary.version.desc()).limit(1)
    return (await s.scalars(q)).first()


async def public_messages(s, campaign_id: str, after_seq: int) -> list[Message]:
    """Публичные сообщения после ``after_seq``: без шёпотов (JSON null в SQLite не равен SQL NULL, поэтому
    видимость проверяется в Python)."""
    q = (
        select(Message)
        .where(Message.campaign_id == campaign_id, Message.seq > after_seq, Message.kind.in_(PUBLIC_KINDS))
        .order_by(Message.seq.desc())
        .limit(SUMMARY_INPUT_LIMIT)
    )
    return [m for m in reversed((await s.scalars(q)).all()) if not m.visible_to]


def render_content(c: dict[str, Any] | None) -> str:
    """Сводка для контекста мастера."""
    if not c:
        return ""
    out = []
    for key, title in (("quests", "Активные задания"), ("threads", "Открытые нити"), ("promises", "Обещания и долги")):
        if c.get(key):
            out.append(f"{title}: " + "; ".join(c[key]))
    if c.get("npcs"):
        npcs = []
        for n in c["npcs"]:
            bits = [n.get("relation"), n.get("note")]
            npcs.append(n["name"] + (f" ({', '.join(b for b in bits if b)})" if any(bits) else ""))
        out.append("NPC: " + "; ".join(npcs))
    if c.get("events"):
        out.append("Что было: " + "; ".join(c["events"][-15:]))
    return "\n".join(out)


def check(raw: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return SummaryContent.model_validate(raw).model_dump()
    except ValidationError:
        return None


def summary_input(prev: Summary | None, rows: list[Message], who) -> str:
    prev_text = json.dumps(prev.content, ensure_ascii=False) if prev else "сводки пока нет"
    lines = [f"[{m.seq}] {who(m)}: {m.content}" for m in rows]
    return f"Прошлая сводка:\n{prev_text}\n\nНовые сообщения:\n" + "\n".join(lines)


# --- сборка контекста (раздел 9) ---


def knowledge_block(catalog, query: str, *, rules_k: int = 4, lore_k: int = 3) -> str:
    """Релевантные фрагменты правил и лора для фазы решения. Мастер видит и скрытый лор."""
    parts = []
    rules = knowledge.rules_for(catalog, query, rules_k)
    if rules:
        parts.append("Правила к этому ходу:\n" + "\n".join(f"- {r.render()}" for r in rules))
    lore = knowledge.lore_for(catalog, query, lore_k)
    if lore:
        parts.append("Лор к этому ходу:\n" + "\n".join(f"- {r.render()}" for r in lore))
    return "\n\n".join(parts)
