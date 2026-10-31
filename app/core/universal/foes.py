"""Encounters of a scene: the server decides how many foes wait there and how strong, the model names them."""

import hashlib
from dataclasses import dataclass
from typing import Literal

# Shares in percent of 0, 1, 2, 3 and 4 foes in a new scene. The harder the world, the fewer empty places.
FOE_COUNTS = {
    "easy": (30, 50, 20, 0, 0),
    "normal": (15, 45, 35, 5, 0),
    "hard": (0, 30, 45, 25, 0),
    "deadly": (0, 0, 30, 45, 25),
}
# Shares in percent of weak, ordinary and strong foes: most of them are weak, so a hero can fight what he meets.
FOE_POWER = {
    "easy": (100, 0, 0),
    "normal": (70, 30, 0),
    "hard": (50, 40, 10),
    "deadly": (20, 50, 30),
}
POWERS = ("weak", "normal", "strong")
# hit points are 10 + the constitution score: weak 11, ordinary 20 (what every creature was), strong 24
POWER_ABILITIES = {
    "weak": dict(str=8, dex=10, con=1, int=6, wis=8, cha=6),
    "normal": dict(str=13, dex=12, con=10, int=8, wis=10, cha=8),
    "strong": dict(str=15, dex=12, con=14, int=8, wis=10, cha=8),
}
FALLBACK_FOES = {
    "weak": ("Враждебная фигура", "Недобрая тень, подступающая к героям."),
    "normal": ("Враждебная тварь", "Опасное существо, которое не собирается отступать."),
    "strong": ("Грозный противник", "Крупный и злобный противник, с которым шутки плохи."),
}


@dataclass(frozen=True)
class FoeSlot:
    ref: str
    power: Literal["weak", "normal", "strong"]


def _pick(roll: int, shares) -> int:
    total = 0
    for index, share in enumerate(shares):
        total += share
        if roll < total:
            return index
    return len(shares) - 1


def foe_slots(campaign, location_id: str, *, entry: bool = False) -> list[FoeSlot]:
    """The place where the story begins is not an ambush: its foes come with the next places."""
    if entry or (campaign.settings or {}).get("encounters_enabled") is False:
        return []
    difficulty = campaign.difficulty if campaign.difficulty in FOE_COUNTS else "normal"
    digest = hashlib.sha256(f"foes:{campaign.id}:{location_id}".encode()).digest()
    count = _pick(int.from_bytes(digest[:8]) % 100, FOE_COUNTS[difficulty])
    return [
        FoeSlot(f"foe_{index + 1}", POWERS[_pick(digest[8 + index] % 100, FOE_POWER[difficulty])])
        for index in range(count)
    ]
