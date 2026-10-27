"""Формы героя, которые видит клиент: публичная часть, полный лист и ответ REST о герое.

Их собирают ``public_view`` и ``full_view`` (app/core/characters.py) и ``_view`` (app/api/characters.py), а эти
модели описывают результат для контракта сервера и клиента (app/contract.py). Новое поле листа начинается здесь.
"""

from __future__ import annotations

from typing import Any

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


class CompanionPublic(Strict):
    id: str
    name: str
    hp: int | None
    hp_max: int | None
    down: bool
    dead: bool


class HeroPublic(Strict):
    """Публичная часть героя: её видят все участники кампании."""

    id: str
    name: str
    portrait_url: str | None = None
    seat_id: str | None
    status: str
    public_bio: str
    level: int
    hp: int | None
    hp_max: int | None
    dead: bool
    bonds: list[Bond]
    companions: list[CompanionPublic]


class TurnEconomy(Strict):
    action: bool
    attacks_left: int
    bonus: bool
    move_left_ft: int
    disengage: bool
    interaction_free: bool = True


class CharacterView(HeroPublic):
    """Public campaign character; owners receive UniversalGameCard separately."""
