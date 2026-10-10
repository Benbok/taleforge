"""Short-lived, item-bound weapon enchantments (SRD 5.1).

Keep mechanical state in character resources. Only a held, matching inventory
item receives the derived bonus. The world clock (not wall time) governs expiry.
"""

from __future__ import annotations

import copy
import re
from typing import Any

from app.db.models import Character, InventoryItem

SHILLELAGH = "shillelagh"
ELIGIBLE = frozenset({"item.club", "item.quarterstaff"})
_DAMAGE = re.compile(r"^(\d+d\d+)([+-]\d+)?(.*)$")


def active_shillelagh(ch: Character, inventory: list[InventoryItem], game_time: int) -> dict[str, Any] | None:
    state = (ch.resources or {}).get(SHILLELAGH)
    if not isinstance(state, dict) or int(state.get("expires_at") or 0) <= game_time:
        return None
    weapon_id = state.get("inventory_id")
    if not any(it.id == weapon_id and it.equipped and it.item_template_id in ELIGIBLE for it in inventory):
        return None
    if state.get("ability") not in ("int", "wis", "cha"):
        return None
    return state


def enchant_attack(attack: dict[str, Any], state: dict[str, Any], mods: dict[str, int]) -> None:
    """Replace weapon die and STR bonus, preserving extras such as Dueling style."""
    if attack.get("inventory_id") != state["inventory_id"] or attack.get("kind") != "melee":
        return
    match = _DAMAGE.fullmatch(str(attack["damage"]))
    if not match:
        return
    ability = state["ability"]
    spell_mod = mods[ability]
    previous_mod = mods[attack.get("ability", "str")]
    attack["attack_bonus"] += spell_mod - previous_mod
    remainder = match.group(3)
    attack["damage"] = f"1d8{spell_mod:+d}" + remainder
    attack["ability"] = ability
    attack["magical"] = True
    attack["enchantment"] = "spell.shillelagh"


def release_weapon(ch: Character, inventory_id: str) -> dict[str, Any] | None:
    """End the buff immediately when the held weapon is dropped or released.

    Returns an undo snapshot for tool transaction rollback and replay.
    """
    state = (ch.resources or {}).get(SHILLELAGH)
    if not isinstance(state, dict) or state.get("inventory_id") != inventory_id:
        return None
    before = copy.deepcopy(ch.resources or {})
    ch.resources = {k: v for k, v in (ch.resources or {}).items() if k != SHILLELAGH}
    return {"table": "characters", "id": ch.id, "field": "resources", "before": before}
