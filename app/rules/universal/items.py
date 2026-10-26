"""Bounded persisted gear; rarity never buys the same weapon property twice."""

from typing import Literal

from pydantic import Field, model_validator

from app.rules.universal.contracts import ClosedModel, Count
from app.rules.universal.profiles import ProfileSpec

ItemStatus = Literal["common", "rare", "unique", "epic"]
STATUS_NAMES = dict(common="Обычный", rare="Редкий", unique="Уникальный", epic="Эпический")
BONUS_BUDGET = dict(common=0, rare=1, unique=2, epic=3)


class GameItemAction(ClosedModel):
    kind: Literal["equip", "unequip", "consume", "weapon_attack", "guard"]
    request_key: str = Field(min_length=1, max_length=64)
    item_id: str | None = Field(default=None, max_length=32)
    target_id: str | None = Field(default=None, max_length=32)


class ItemProfile(ClosedModel):
    schema_version: Literal[1] = 1
    name: str = Field(min_length=1, max_length=128)
    description: str = Field(default="", max_length=1000)
    kind: Literal["weapon", "armor", "consumable"]
    status: ItemStatus = "common"
    attribute: Literal["str", "dex"] = "str"
    base_dice: Literal["1d4", "1d6"] = "1d6"
    attack_bonus: Count = Field(default=0, le=3)
    damage_bonus: Count = Field(default=0, le=3)
    defense_bonus: Count = Field(default=0, le=6)
    restore_pool: Literal["hp", "str", "dex", "int", "wis", "cha"] | None = None
    restore_amount: Count = Field(default=6, ge=1, le=100)

    @model_validator(mode="after")
    def bounded(self):
        budget = BONUS_BUDGET[self.status]
        if self.attack_bonus + self.damage_bonus > budget or self.defense_bonus > 3 + budget:
            raise ValueError("Свойства превышают бюджет статуса предмета")
        if self.kind != "weapon" and (self.attack_bonus or self.damage_bonus):
            raise ValueError("Боевые бонусы принадлежат оружию")
        if self.kind != "armor" and self.defense_bonus:
            raise ValueError("Защиту даёт только броня")
        if (self.kind == "consumable") != (self.restore_pool is not None):
            raise ValueError("Расходнику нужен один восстанавливаемый запас")
        return self


def item_attack_profile(item: ItemProfile, instance_id: str) -> ProfileSpec:
    item = ItemProfile.model_validate(item.model_dump())
    if item.kind != "weapon":
        raise ValueError("Это не оружие")
    return ProfileSpec(
        id="weapon-" + instance_id,
        attribute=item.attribute,
        kind="damage",
        use_kind="weapon_basic",
        base_dice=item.base_dice,
        item_id=instance_id,
        rarity=item.status,
        attack_bonus=item.attack_bonus,
        damage_bonus=item.damage_bonus,
    )
