"""Карточка сущности по клику на разметку ``[[id|текст]]`` (ТЗ, раздел 10; документ дизайна, «Карточки знаний»).

Сервер отдаёт только то, что открыто герою зрителя в ``knowledge``:

- 0 — видел: имя и внешнее описание;
- 1 — наслышан: добавляются слухи и повадки (описание вида из шаблона, манера поведения);
- 2 — изучил: примерное здоровье словами, видимые атаки, уязвимости;
- 3 — знает всё: КБ, хиты, характеристики, скорость, сопротивления — без секретов сюжета.

Кроме уровня карточка несёт то, что герой узнал в игре: факты от мастера (``known_facts``, только этого героя)
и «что вы слышали» — фразы из сообщений, которые видел этот игрок, где упомянута сущность. Карточка другого
героя — открытая биография, открытые ответы о связях и те же факты.

Место мастера видит уровень 3. Поля берутся по белому списку: секреты каркаса (``plot_id``), подсказки добычи и
заметки мастера в карточку не попадают никогда. Сущность, которую герой не видел (нет строки знаний, её нет
в текущей сцене и она не упоминалась в видимых ему сообщениях), для него не существует.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.catalog import campaign_catalog
from app.core.campaigns import Viewer
from app.core.characters import public_view
from app.core.rolls import ABILITY_RU, DAMAGE_RU
from app.core.world import get_scene
from app.db.models import Character, Entity, Knowledge, KnownFact, Message

LEVELS = {0: "видел", 1: "наслышан", 2: "изучил", 3: "знает всё"}
# манера поведения из шаблона (behavior.profile); заметки и ярлыки шаблона могут раскрывать тайны — их не показываем
BEHAVIOR_RU = {
    "aggressive": "нападает первым",
    "cowardly": "избегает схватки и бежит, когда становится опасно",
    "defender": "защищает своё и не преследует",
    "capturer": "старается схватить, а не убить",
    "noncombatant": "в бой не вступает",
}
LIVE_HEROES = ("approved", "active")


class InspectError(Exception):
    pass


def entity_type(e: Entity) -> str:
    """Тип для цвета разметки: враг, NPC, предмет или место (цвета задаёт тема пакета)."""
    if e.kind == "creature":
        return "creature" if (e.state or {}).get("attitude", "hostile") == "hostile" else "npc"
    if e.kind == "location":
        return "location"
    return "item"


async def viewer_hero(session: AsyncSession, viewer: Viewer) -> Character | None:
    if viewer.seat is None or viewer.seat.role != "player":
        return None
    q = select(Character).where(
        Character.campaign_id == viewer.campaign.id,
        Character.seat_id == viewer.seat.id,
        Character.status.in_(LIVE_HEROES),
    )
    return (await session.scalars(q)).first()


async def _mentioned(session: AsyncSession, viewer: Viewer, entity_id: str) -> bool:
    q = select(Message.visible_to).where(
        Message.campaign_id == viewer.campaign.id, Message.content.contains(f"[[{entity_id}|")
    )
    seat = viewer.seat.id if viewer.seat else None
    return any(v is None or seat in v for v in (await session.scalars(q)).all())


async def level_for(session: AsyncSession, viewer: Viewer, e: Entity) -> int | None:
    """Уровень знаний зрителя о сущности или None, если он её не видел."""
    if viewer.seat is not None and viewer.seat.role == "master":
        return 3
    hero = await viewer_hero(session, viewer)
    if hero is not None:
        row = await session.get(Knowledge, (hero.id, e.id))
        if row is not None:
            return row.level
    scene = await get_scene(session, viewer.campaign.id)
    here = scene.location_id and (e.id == scene.location_id or e.location_id == scene.location_id)
    if here or await _mentioned(session, viewer, e.id):
        return 0
    return None


MARKUP = re.compile(r"\[\[([^|\]]+)\|([^\]]+)\]\]")
SENTENCE = re.compile(r"(?<=[.!?…»])\s+")
HEARD_LIMIT = 4
HEARD_LEN = 240


def _plain(text: str) -> str:
    return MARKUP.sub(lambda m: m.group(2), text)


def _sentence_about(content: str, subject_id: str) -> str | None:
    """Фраза сообщения, где упомянута сущность, без разметки."""
    for s in SENTENCE.split(content):
        if f"[[{subject_id}|" in s:
            out = _plain(s).strip()
            return out if len(out) <= HEARD_LEN else out[: HEARD_LEN - 1].rstrip() + "…"
    return None


async def heard(session: AsyncSession, viewer: Viewer, subject_id: str) -> list[str]:
    """Что этот игрок слышал о сущности: последние фразы из видимых ему сообщений мастера, по порядку."""
    q = (
        select(Message.content, Message.visible_to)
        .where(
            Message.campaign_id == viewer.campaign.id,
            Message.kind.in_(("narration", "whisper")),
            Message.content.contains(f"[[{subject_id}|"),
        )
        .order_by(Message.seq.desc())
        .limit(40)
    )
    seat = viewer.seat.id if viewer.seat else None
    master = viewer.seat is not None and viewer.seat.role == "master"
    out: list[str] = []
    for content, visible_to in (await session.execute(q)).all():
        if visible_to is not None and not master and seat not in visible_to:
            continue  # чужой шёпот
        s = _sentence_about(content, subject_id)
        if s and s not in out:
            out.append(s)
        if len(out) >= HEARD_LIMIT:
            break
    return list(reversed(out))


async def facts(session: AsyncSession, viewer: Viewer, subject_id: str) -> list[str]:
    """Факты, которые мастер открыл герою зрителя. Место мастера видит факты всех героев."""
    q = select(KnownFact.text).where(KnownFact.campaign_id == viewer.campaign.id, KnownFact.subject_id == subject_id)
    if not (viewer.seat is not None and viewer.seat.role == "master"):
        hero = await viewer_hero(session, viewer)
        if hero is None:
            return []
        q = q.where(KnownFact.character_id == hero.id)
    rows = (await session.scalars(q.order_by(KnownFact.created_at))).all()
    return list(dict.fromkeys(rows))


def _condition(state: dict[str, Any]) -> str | None:
    if state.get("dead"):
        return "мёртв"
    hp, mx = state.get("hp"), state.get("hp_max")
    if hp is None or not mx:
        return None
    if hp >= mx:
        return "невредим"
    return "ранен" if hp > mx / 2 else "едва держится"


async def entity_card(session: AsyncSession, viewer: Viewer, entity_id: str) -> dict[str, Any]:
    ch = await session.get(Character, entity_id)
    if ch is not None and ch.campaign_id == viewer.campaign.id:
        if ch.status in ("draft", "submitted", "rejected"):
            raise InspectError("такого в мире нет")
        catalog = await campaign_catalog(session, viewer.campaign)
        pv = public_view(ch)
        for key in ("class", "origin"):
            rec = catalog.find(pv.get(f"{key}_id") or "")
            pv[f"{key}_name"] = rec.name if rec else None
        return {
            "id": ch.id,
            "type": "hero",
            "name": ch.name,
            "level": None,
            "hero": pv,
            "facts": await facts(session, viewer, ch.id),
            "heard": await heard(session, viewer, ch.id),
        }
    e = await session.get(Entity, entity_id)
    if e is None or e.campaign_id != viewer.campaign.id:
        raise InspectError("такого в мире нет")
    level = await level_for(session, viewer, e)
    if level is None:
        raise InspectError("такого в мире нет")
    card: dict[str, Any] = {
        "id": e.id,
        "type": entity_type(e),
        "name": e.name,
        "level": level,
        "level_name": LEVELS[level],
        "description": e.description or None,
        "locked": [LEVELS[i] for i in range(level + 1, 4)],  # что ещё можно узнать
    }
    rec = None
    if e.template_id and level >= 1:
        catalog = await campaign_catalog(session, viewer.campaign)
        rec = catalog.find(e.template_id)
    data = rec.data if rec else {}
    st = e.state or {}
    if level >= 1 and rec is not None:
        card["kind_name"] = rec.name
        if data.get("description") and data.get("description") != e.description:
            card["lore"] = data["description"]
        profile = (data.get("behavior") or {}).get("profile")
        if profile in BEHAVIOR_RU:
            card["habits"] = BEHAVIOR_RU[profile]
    if e.kind == "creature" and level >= 2:
        card["condition"] = _condition(st)
        card["attacks"] = [a.get("name") for a in data.get("actions") or [] if a.get("kind") != "multiattack"][:6]
        vul = data.get("damage_vulnerabilities") or []
        if vul:
            card["vulnerable"] = [DAMAGE_RU.get(x, x) for x in vul]
    if e.kind == "creature" and level >= 3:
        stats: dict[str, Any] = {"ac": data.get("ac"), "hp": st.get("hp"), "hp_max": st.get("hp_max")}
        abil = data.get("abilities")
        if isinstance(abil, dict) and abil:
            stats["abilities"] = {ABILITY_RU[k]: v for k, v in abil.items() if k in ABILITY_RU}
        if data.get("speed"):
            stats["speed"] = data["speed"]
        for key, word in (("damage_resistances", "resist"), ("damage_immunities", "immune")):
            if data.get(key):
                stats[word] = [DAMAGE_RU.get(x, x) for x in data[key]]
        card["stats"] = stats
    card["facts"] = await facts(session, viewer, e.id)
    card["heard"] = await heard(session, viewer, e.id)
    return card


async def types_for(session: AsyncSession, viewer: Viewer, ids: list[str]) -> dict[str, str]:
    """Типы сущностей для цвета разметки. Только тип: ни имени, ни описания здесь нет."""
    ids = [i for i in dict.fromkeys(ids) if isinstance(i, str)][:100]
    out: dict[str, str] = {}
    if not ids:
        return out
    cid = viewer.campaign.id
    for e in (await session.scalars(select(Entity).where(Entity.campaign_id == cid, Entity.id.in_(ids)))).all():
        out[e.id] = entity_type(e)
    rows = await session.scalars(select(Character.id).where(Character.campaign_id == cid, Character.id.in_(ids)))
    for i in rows.all():
        out[i] = "hero"
    return out
