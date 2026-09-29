"""Роли в отряде: чего не хватает и какие классы это закроют (ТЗ, раздел 5.2, подсказка для ИИ-игроков).

Роль класса берётся из записи пакета (``party_roles``), для классов SRD — из таблицы ниже по ``srd_ref``,
для остальных — по тегам (``caster`` — магия, ``martial`` — урон). Подсказка, а не правило: владелец решает сам.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.content.catalog import CatalogView, Entry
from app.db.models import Campaign, Character

ROLES = {
    "heal": "лечение",
    "tank": "защита",
    "damage": "урон",
    "scout": "разведка и ловкость",
    "magic": "магия",
}
SRD = {
    "Barbarian": ["tank", "damage"],
    "Bard": ["heal", "magic"],
    "Cleric": ["heal", "tank"],
    "Druid": ["heal", "magic"],
    "Fighter": ["tank", "damage"],
    "Monk": ["damage", "scout"],
    "Paladin": ["tank", "heal"],
    "Ranger": ["damage", "scout"],
    "Rogue": ["scout", "damage"],
    "Sorcerer": ["magic", "damage"],
    "Warlock": ["magic", "damage"],
    "Wizard": ["magic"],
}


def roles_of(e: Entry) -> list[str]:
    d = e.data
    own = [r for r in d.get("party_roles") or [] if r in ROLES]
    if own:
        return own
    ref = d.get("srd_ref")
    if isinstance(ref, dict) and ref.get("name") in SRD:
        return SRD[ref["name"]]
    name = e.id.removeprefix("class.").capitalize()
    if name in SRD:
        return SRD[name]
    tags = set(d.get("tags") or [])
    out = []
    if "caster" in tags:
        out.append("magic")
    if "martial" in tags:
        out.append("damage")
    return out


async def party_roles(session: AsyncSession, campaign: Campaign, cat: CatalogView) -> dict[str, Any]:
    """Какие роли уже есть у героев отряда, каких нет, и какие классы их закроют."""
    q = select(Character).where(Character.campaign_id == campaign.id, Character.status.in_(("approved", "active")))
    heroes = (await session.scalars(q)).all()
    classes = cat.by_kind("class")
    by_id = {e.id: e for e in classes}
    have: dict[str, list[str]] = {r: [] for r in ROLES}
    for ch in heroes:
        e = by_id.get((ch.sheet or {}).get("class_id") or "")
        for r in roles_of(e) if e else []:
            have[r].append(ch.name)
    missing = []
    for r, label in ROLES.items():
        if have[r]:
            continue
        fit = [{"id": e.id, "name": e.name} for e in classes if r in roles_of(e)]
        missing.append({"role": r, "label": label, "classes": fit})
    return {
        "have": [{"role": r, "label": ROLES[r], "heroes": names} for r, names in have.items() if names],
        "missing": missing,
        "heroes": len(heroes),
        "recommended": campaign.party_size_recommended,
    }
