"""Shared equipment rules used by the master tool and player REST actions."""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from typing import Any

from app.core import economy
from app.core.character_form import current_form
from app.core.weapon_enchantments import release_weapon
from app.db.models import Character, InventoryItem
from app.tools.registry import ToolContext, ToolError


@dataclass
class EquipmentPlan:
    item: InventoryItem
    equipped: bool
    category: str
    armor_type: str | None
    displaced: list[InventoryItem] = field(default_factory=list)
    weapon_operations: int = 0
    shield_operations: int = 0

    @property
    def changed(self) -> bool:
        return bool(
            self.weapon_operations or self.shield_operations or self.displaced or self.item.equipped != self.equipped
        )

    @property
    def action_cost(self) -> int:
        return self.shield_operations + max(0, self.weapon_operations - 1)


def _can_handle_form(world, ch: Character) -> None:
    form = current_form(ch, world.scene.game_time)
    if form and not form.get("can_handle_items", False):
        raise ToolError(
            f"{ch.name}: облик «{form['name']}» не позволяет брать и передавать снаряжение. "
            "Предмет остаётся на месте; сначала нужно вернуться в подходящий облик.",
            code="form_cannot_handle_items",
            category="rule_denial",
        )


def _kind(world, item: InventoryItem) -> tuple[str, dict]:
    rec = world.catalog.get(item.item_template_id, "item_template")
    data = rec.data
    return str(data.get("category") or ""), data


def _hands(data: dict) -> int:
    return 2 if "two_handed" in (data.get("properties") or []) else 1


def inventory_properties(cat, item_template_id: str) -> dict[str, Any]:
    rec = cat.find(item_template_id, "item_template")
    data = rec.data if rec is not None else {}
    damage = data.get("damage")
    return {
        "category": data.get("category"),
        "damage": {
            "dice": str(damage.get("dice")),
            "type": str(damage.get("type")),
        }
        if isinstance(damage, dict) and damage.get("dice") and damage.get("type")
        else None,
        "properties": [str(value) for value in data.get("properties") or []],
        "armor_type": data.get("armor_type"),
        "ac_base": data.get("ac_base"),
        "ac_bonus": data.get("ac_bonus"),
        "dex_cap": data.get("dex_cap"),
        "two_handed": "two_handed" in (data.get("properties") or []),
    }


def _equipped_items(world, hero_id: str) -> list[InventoryItem]:
    return [item for item in world.inventory.get(hero_id, []) if item.equipped]


def plan_equipment(world, character_id: str, inventory_id: str, equipped: bool) -> EquipmentPlan:
    ch = world.characters.get(character_id)
    if ch is None:
        raise ToolError(f"персонаж {character_id} не найден")
    _can_handle_form(world, ch)
    item = next((row for row in world.inventory.get(character_id, []) if row.id == inventory_id), None)
    if item is None:
        raise ToolError(f"у {ch.name} нет предмета {inventory_id}")
    category, data = _kind(world, item)
    armor_type = data.get("armor_type") if category == "armor" else None
    if category not in {"weapon", "armor"}:
        raise ToolError(f"«{world.item_name(item)}» нельзя надеть или взять как оружие")

    in_combat = world.in_fight(character_id)
    if in_combat and category == "armor" and armor_type != "shield":
        raise ToolError(f"{ch.name}: доспех в бою нельзя надеть или снять")
    if in_combat and not economy.active(world, character_id):
        raise ToolError(f"{ch.name}: менять снаряжение можно только в свой ход боя")
    if item.equipped == equipped:
        return EquipmentPlan(item, equipped, category, armor_type)

    displaced: list[InventoryItem] = []
    if equipped and category == "armor":
        for other in _equipped_items(world, character_id):
            if other is item:
                continue
            other_category, other_data = _kind(world, other)
            if other_category == "armor" and ((other_data.get("armor_type") == "shield") == (armor_type == "shield")):
                displaced.append(other)
        if armor_type == "shield":
            weapons = []
            hands = 1
            for other in _equipped_items(world, character_id):
                if other is item or other in displaced:
                    continue
                other_category, other_data = _kind(world, other)
                if other_category == "weapon":
                    weapons.append((other, _hands(other_data)))
                    hands += _hands(other_data)
            for other, used in sorted(weapons, key=lambda row: row[0].id):
                if hands <= 2:
                    break
                displaced.append(other)
                hands -= used
    elif equipped and category == "weapon":
        weapons = []
        shield_hands = 0
        for other in _equipped_items(world, character_id):
            if other is item:
                continue
            other_category, other_data = _kind(world, other)
            if other_category == "weapon":
                weapons.append((other, _hands(other_data)))
            elif other_category == "armor" and other_data.get("armor_type") == "shield":
                shield_hands = 1
        total_hands = _hands(data) + shield_hands + sum(hands for _, hands in weapons)
        for other, hands in sorted(weapons, key=lambda row: row[0].id):
            if total_hands <= 2:
                break
            displaced.append(other)
            total_hands -= hands
        if total_hands > 2 and shield_hands:
            for other in _equipped_items(world, character_id):
                other_category, other_data = _kind(world, other)
                if other_category == "armor" and other_data.get("armor_type") == "shield":
                    displaced.append(other)
                    total_hands -= 1
                    break

    weapon_operations = 0
    shield_operations = 0
    if category == "weapon":
        weapon_operations += 1
    elif category == "armor" and armor_type == "shield":
        shield_operations += 1
    for other in displaced:
        other_category, other_data = _kind(world, other)
        if other_category == "weapon":
            weapon_operations += 1
        elif other_category == "armor" and other_data.get("armor_type") == "shield":
            shield_operations += 1
    return EquipmentPlan(item, equipped, category, armor_type, displaced, weapon_operations, shield_operations)


def _reserve_cost(ctx: ToolContext, hero_id: str, plan: EquipmentPlan) -> None:
    if not ctx.world.in_fight(hero_id):
        return
    # Preflight the complete composite change on a local ledger so no action
    # or free interaction is consumed when one of its operations cannot fit.
    trial = economy.ledger(ctx.world, hero_id)
    if plan.weapon_operations:
        paid = max(0, plan.weapon_operations - (0 if trial.get("interaction_used") else 1))
        for _ in range(paid):
            economy._need_action(ctx.world, hero_id, trial, "предмет")
    for _ in range(plan.shield_operations):
        economy._need_action(ctx.world, hero_id, trial, "предмет")

    if plan.weapon_operations:
        economy.charge_interaction(ctx, hero_id, plan.weapon_operations)
    for _ in range(plan.shield_operations):
        economy.charge(ctx, hero_id, "use_object")


async def set_equipment(ctx: ToolContext, character_id: str, inventory_id: str, equipped: bool = True) -> dict:
    ch = ctx.world.characters.get(character_id)
    if ch is None:
        raise ToolError(f"персонаж {character_id} не найден")
    plan = plan_equipment(ctx.world, character_id, inventory_id, equipped)
    if not plan.changed:
        return {
            "character": ch.name,
            "item": ctx.world.item_name(plan.item),
            "equipped": equipped,
            "ac": ctx.world.actor(character_id).ac,
            "repeated": True,
        }

    inverse: list[dict] = [
        {"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(ctx.world.scene.state)}
    ]
    for row in [*plan.displaced, plan.item]:
        inverse.append({"table": "inventory", "id": row.id, "field": "equipped", "before": row.equipped})
    _reserve_cost(ctx, character_id, plan)

    for row in plan.displaced:
        if row.equipped:
            released = release_weapon(ch, row.id)
            if released:
                inverse.append(released)
            row.equipped = False
    if not equipped:
        released = release_weapon(ch, plan.item.id)
        if released:
            inverse.append(released)
    plan.item.equipped = equipped
    ctx.world.invalidate(character_id)
    result = {
        "character": ch.name,
        "item": ctx.world.item_name(plan.item),
        "equipped": equipped,
        "ac": ctx.world.actor(character_id).ac,
    }
    await ctx.record("equip_item", target_id=character_id, payload=result, inverse=inverse)
    return result


def equipment_state(world, character_id: str) -> dict:
    """Mechanical switch descriptions for a full hero sheet."""
    out: dict[str, dict] = {}
    for item in world.inventory.get(character_id, []):
        try:
            plan = plan_equipment(world, character_id, item.id, not item.equipped)
            active_turn = economy.active(world, character_id)
            led = economy.ledger(world, character_id) if active_turn else None
            action_cost = (
                plan.shield_operations
                + max(0, plan.weapon_operations - (0 if led and led.get("interaction_used") else 1))
                if active_turn
                else 0
            )
            available = (1 + int(led.get("extra") or 0) - int(led.get("actions") or 0)) if led else 0
            allowed = not active_turn or action_cost <= available
            out[item.id] = {
                "allowed": allowed,
                "reason": (
                    None
                    if allowed
                    else (
                        f"{world.characters[character_id].name}: на это нужно действий: "
                        f"{action_cost}, осталось: {available}"
                    )
                ),
                "action_cost": action_cost,
                "interaction_count": plan.weapon_operations,
                "displaced_ids": [row.id for row in plan.displaced],
            }
        except ToolError as exc:
            out[item.id] = {
                "allowed": False,
                "reason": str(exc),
                "action_cost": 0,
                "interaction_count": 0,
                "displaced_ids": [],
            }
    return out
