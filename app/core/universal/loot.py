"""Серверный бюджет и ограниченные профили находок в сцене."""

import hashlib
from dataclasses import dataclass
from typing import Literal

from app.rules.universal.items import ItemProfile

LOOT_COUNTS = {"easy": (20, 50, 30), "normal": (30, 60, 10), "hard": (60, 40, 0), "deadly": (100, 0, 0)}
FALLBACK_NAMES = {"consumable": "Фляга с настойкой", "weapon": "Потёртый нож", "armor": "Кожаная куртка"}


@dataclass(frozen=True)
class LootSlot:
    ref: str
    kind: Literal["consumable", "weapon", "armor"]


def loot_slots(campaign, location_id: str) -> list[LootSlot]:
    if (campaign.settings or {}).get("loot_enabled") is False:
        return []
    digest = hashlib.sha256(f"loot:{campaign.id}:{location_id}".encode()).digest()
    zero, one, _ = LOOT_COUNTS.get(campaign.difficulty, LOOT_COUNTS["normal"])
    roll = int.from_bytes(digest[:8]) % 100
    count = 0 if roll < zero else 1 if roll < zero + one else 2
    result = []
    for i in range(count):
        kind_roll = digest[8 + i] % 100
        kind = "consumable" if kind_roll < 50 else "weapon" if kind_roll < 75 else "armor"
        result.append(LootSlot(f"loot_{i + 1}", kind))
    return result


def loot_profile(slot: LootSlot, name: str, description: str, attribute: str = "str") -> ItemProfile:
    if attribute not in {"str", "dex"}:
        raise ValueError("Оружию нужна сила или ловкость")
    return ItemProfile(
        name=name,
        description=description,
        kind=slot.kind,
        status="common",
        attribute=attribute if slot.kind == "weapon" else "str",
        base_dice="1d4" if slot.kind == "weapon" and attribute == "dex" else "1d6",
        defense_bonus=1 if slot.kind == "armor" else 0,
        restore_pool="hp" if slot.kind == "consumable" else None,
        restore_amount=6,
    )
