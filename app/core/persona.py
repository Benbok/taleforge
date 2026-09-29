"""Характер героя и ИИ-мастера (ТЗ, раздел 5.2; этап 9б).

Анкета — свободный текст и поля-подсказки вместе: текст задаёт, кто он, поля не дают модели скатиться в шаблон.
Ядро — поля, отмеченные неизменными: их не трогает летопись. Летопись — записи «что изменилось и почему» после
сессии и сильных событий; владелец может поправить или откатить любую запись. Модель получает анкету вместе с
действующими записями летописи.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import PersonaNote

HERO_FIELDS: dict[str, tuple[str, str]] = {
    "conflict": ("Противоречие", "что в нём спорит само с собой: храбрый, но боится ответственности"),
    "want": ("Чего хочет", "чего добивается прямо сейчас и в жизни"),
    "fear": ("Чего боится", "что его пугает или от чего он бежит"),
    "voice": ("Голос", "2–3 фразы, как он говорит: слова, ритм, привычки"),
    "party": ("Отношение к отряду", "кому доверяет, кого терпит, кому что-то должен"),
    "secret": ("Тайна или долг", "что скрывает или кому обязан"),
    "never": ("Чего никогда не сделает", "черта, которую он не переступит"),
    "goal": ("Цель в кампании", "чего хочет добиться к концу истории"),
}
HERO_CORE = ["voice", "never", "conflict"]

MASTER_FIELDS: dict[str, tuple[str, str]] = {
    "tricks": ("Любимые приёмы", "чем мастер любит удивлять: детали, повороты, ритм сцены"),
    "samples": ("Образцы повествования", "2–3 абзаца, как мастер описывает сцену"),
    "never": ("Чего мастер никогда не делает", "запреты: темы, приёмы, решения за игроков"),
    "party": ("Отношение к отряду", "как мастер смотрит на героев: сочувствует, испытывает, дразнит"),
}
MASTER_CORE = ["samples", "never"]

TEXT_MAX, FIELD_MAX, NOTES_MAX = 4000, 1000, 12


def fields_for(master: bool) -> dict[str, tuple[str, str]]:
    return MASTER_FIELDS if master else HERO_FIELDS


def normalize(raw: dict[str, Any] | None, master: bool = False) -> dict[str, Any]:
    """Анкета в хранимом виде: лишние ключи отбрасываются, длина ограничивается, ядро — только из известных полей."""
    raw = raw or {}
    known = fields_for(master)
    fields = {k: str(v).strip()[:FIELD_MAX] for k, v in (raw.get("fields") or {}).items() if k in known and v}
    fields = {k: v for k, v in fields.items() if v}
    core = raw.get("core")
    core = [k for k in (core if isinstance(core, list) else (MASTER_CORE if master else HERO_CORE)) if k in known]
    return {"text": str(raw.get("text") or "").strip()[:TEXT_MAX], "fields": fields, "core": list(dict.fromkeys(core))}


def empty(sheet: dict[str, Any] | None) -> bool:
    return not sheet or (not sheet.get("text") and not sheet.get("fields"))


def schema(master: bool = False) -> dict[str, Any]:
    """Поля анкеты для клиента: подписи, подсказки и ядро по умолчанию."""
    return {
        "fields": [{"id": k, "label": v[0], "hint": v[1]} for k, v in fields_for(master).items()],
        "core": MASTER_CORE if master else HERO_CORE,
    }


def render(sheet: dict[str, Any] | None, notes: list[PersonaNote], master: bool = False) -> str:
    """Анкета и летопись одним текстом для подсказки модели."""
    sheet = normalize(sheet, master)
    lines: list[str] = []
    if sheet["text"]:
        lines.append(sheet["text"])
    for k, (label, _) in fields_for(master).items():
        if sheet["fields"].get(k):
            mark = " (неизменно)" if k in sheet["core"] else ""
            lines.append(f"{label}{mark}: {sheet['fields'][k]}")
    active = [n for n in notes if n.reverted_at is None]
    if active:
        lines.append("Как изменился по ходу кампании (свежее — ниже; это важнее исходной анкеты, кроме неизменного):")
        lines += [f"- {n.text}" + (f" ({n.cause})" if n.cause else "") for n in active[-NOTES_MAX:]]
    return "\n".join(lines)


async def notes_of(s: AsyncSession, campaign_id: str, character_id: str | None) -> list[PersonaNote]:
    q = select(PersonaNote).where(PersonaNote.campaign_id == campaign_id)
    who = PersonaNote.character_id
    q = q.where(who.is_(None) if character_id is None else who == character_id)
    return list((await s.scalars(q.order_by(PersonaNote.created_at, PersonaNote.id))).all())


def note_out(n: PersonaNote) -> dict[str, Any]:
    return {
        "id": n.id,
        "text": n.text,
        "cause": n.cause,
        "source": n.source,
        "edited": n.edited,
        "reverted": n.reverted_at is not None,
        "created_at": n.created_at.isoformat() if n.created_at else None,
    }


def revert(n: PersonaNote, back: bool = True) -> None:
    n.reverted_at = datetime.now(UTC) if back else None


def edit_note(n: PersonaNote, text: str | None, cause: str | None, reverted: bool | None) -> None:
    if text is not None and text.strip() != n.text:
        n.text, n.edited = text.strip()[:500], True
    if cause is not None and cause.strip() != n.cause:
        n.cause, n.edited = cause.strip()[:300], True
    if reverted is not None:
        revert(n, reverted)


# Таблицы характера пакета (вид записи persona_table): черта идёт в свободный текст, остальное — в поля.
TABLE_SLOTS: dict[str, tuple[str | None, str]] = {
    "trait": (None, "Черта"),
    "ideal": ("want", "Идеал"),
    "bond": ("secret", "Привязанность"),
    "flaw": ("conflict", "Слабость"),
}


def from_tables(
    sheet: dict[str, Any] | None, tables: list[dict[str, Any]], hero_ids: set[str], pick
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    """По строке из таблиц пакета в пустые места анкеты; заполненное не трогает. ``pick(rows)`` выбирает строку.
    Таблица с ``for`` действует только для героя с этим классом или происхождением и вытесняет общую."""
    out = normalize(sheet)
    taken: list[dict[str, str]] = []
    for slot, (field, label) in TABLE_SLOTS.items():
        own = [t for t in tables if t.get("slot") == slot and set(t.get("for") or []) & hero_ids]
        common = [t for t in tables if t.get("slot") == slot and not t.get("for")]
        rows = [r for t in (own or common) for r in t.get("rows") or [] if isinstance(r, str) and r.strip()]
        if not rows:
            continue
        if field is None:
            if out["text"]:
                continue
            out["text"] = pick(rows).strip()[:TEXT_MAX]
            taken.append({"slot": slot, "label": label, "text": out["text"]})
        elif not out["fields"].get(field):
            out["fields"][field] = pick(rows).strip()[:FIELD_MAX]
            taken.append({"slot": slot, "label": label, "text": out["fields"][field]})
    return out, taken
