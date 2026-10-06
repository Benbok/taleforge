"""Формы героя, которые видит клиент: публичная часть, полный лист и ответ REST о герое.

Их собирают ``public_view`` и ``full_view`` (app/core/characters.py) и ``_view`` (app/api/characters.py), а эти
модели описывают результат для контракта сервера и клиента (app/contract.py). Новое поле листа начинается здесь.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


def absent() -> Any:
    """Поле, которого может не быть, но если оно есть — не null (в типах клиента ``x?: T``)."""
    return Field(default=None)


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Open(BaseModel):
    """Известные поля проверяются, новые пропускаются: форма шире, чем описано."""

    model_config = ConfigDict(extra="allow")


class Bond(Open):
    question: str
    answer: str


class HeroPublic(Strict):
    """Публичная часть героя: её видят все участники кампании."""

    id: str
    name: str
    seat_id: str | None
    status: str
    public_bio: str
    class_id: str | None
    origin_id: str | None
    level: int
    hp: int | None
    hp_max: int | None
    dead: bool
    death_saves: tuple[int, int] | None
    bonds: list[Bond]


class HeroAttack(Open):
    key: str
    name: str
    attack_bonus: int
    damage: str
    damage_type: str
    kind: Literal["melee", "ranged"]
    reach_ft: int = absent()
    normal_ft: int = absent()
    long_ft: int = absent()
    inventory_id: str = absent()


class HeroEffect(Strict):
    id: str
    template: str
    name: str
    stacks: int


class Derived(Strict):
    abilities: dict[str, int]
    mods: dict[str, int]
    ac: int
    hp_max: int
    saves: dict[str, int]
    skills: dict[str, int]
    pb: int
    speed: int
    attacks: list[HeroAttack]
    effects: list[HeroEffect]


class FeatureUses(Strict):
    key: str
    name: str
    max: int
    left: int
    per: Literal["short_rest", "long_rest"]
    per_ru: str
    unit: str


class Lineage(Strict):
    id: str
    name: str
    caste: str | None
    features: list[str]


class Progress(Strict):
    xp: int
    level_xp: int
    next_xp: int | None


class InventoryRow(Strict):
    id: str
    item: str
    name: str
    qty: int
    equipped: bool


class SheetParts(BaseModel):
    """Поля полного листа: их видят игрок героя, мастер и тот, кто ведёт героя за ушедшего игрока."""

    sheet: dict[str, Any]
    resources: dict[str, Any]
    # личную предысторию не видит тот, кто ведёт героя за ушедшего игрока
    private_backstory: str = absent()
    personality: dict[str, Any]
    review_comment: str | None
    derived: Derived = absent()
    features: list[FeatureUses] = absent()
    lineage: Lineage = absent()
    progress: Progress
    # книга заклинаний у заклинателей; её форма описана в клиенте (web/src/lib/spells.ts)
    spellbook: dict[str, Any] = absent()
    inventory: list[InventoryRow]
    # лист из REST (и его копия игроку по сокету) несёт ещё имена из каталога и состояние проверки
    stand_in: bool = absent()
    errors: list[str] = absent()
    class_name: str | None = absent()
    origin_name: str | None = absent()
    reviewer: Literal["ai", "master"] = absent()
    review_error: str | None = absent()


class HeroSheet(HeroPublic, SheetParts):
    """Полный лист героя (``full_view``)."""


class CharacterView(HeroPublic):
    """Герой в ответе REST: полный лист, если его можно видеть, иначе публичная часть; плюс имена из каталога и
    состояние проверки."""

    sheet: dict[str, Any] = absent()
    resources: dict[str, Any] = absent()
    private_backstory: str = absent()
    personality: dict[str, Any] = absent()
    review_comment: str | None = absent()
    derived: Derived = absent()
    features: list[FeatureUses] = absent()
    lineage: Lineage = absent()
    progress: Progress = absent()
    spellbook: dict[str, Any] = absent()
    inventory: list[InventoryRow] = absent()
    stand_in: bool = absent()
    errors: list[str] = absent()
    class_name: str | None = absent()
    origin_name: str | None = absent()
    reviewer: Literal["ai", "master"] = absent()
    review_error: str | None = absent()
