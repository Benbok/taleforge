from __future__ import annotations

import re
from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer, WithJsonSchema, model_validator

AbilityKey = Literal["str", "dex", "con", "int", "wis", "cha"]
EnergyKey = Literal["str", "dex", "int", "wis", "cha"]
ABILITY_KEYS: tuple[AbilityKey, ...] = ("str", "dex", "con", "int", "wis", "cha")
ENERGY_KEYS: tuple[EnergyKey, ...] = ("str", "dex", "int", "wis", "cha")
START_ARRAY = (8, 10, 12, 13, 14, 15)


def exact_int(value):
    if type(value) is int:
        return value
    if isinstance(value, str) and re.fullmatch(r"-?(0|[1-9][0-9]*)", value):
        return int(value)
    raise ValueError("нужно точное целое число")


Count = Annotated[
    int,
    BeforeValidator(exact_int),
    Field(ge=0),
    PlainSerializer(str, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": "^(0|[1-9][0-9]*)$"}),
]
SignedCount = Annotated[
    int,
    BeforeValidator(exact_int),
    PlainSerializer(str, return_type=str, when_used="json"),
    WithJsonSchema({"type": "string", "pattern": "^-?(0|[1-9][0-9]*)$"}),
]


class ClosedModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AbilityScores(ClosedModel):
    str: Count = Field(ge=1)
    dex: Count = Field(ge=1)
    con: Count = Field(ge=1)
    int: Count = Field(ge=1)
    wis: Count = Field(ge=1)
    cha: Count = Field(ge=1)


class HeroDescription(ClosedModel):
    name: str = Field(default="", max_length=64)
    identity: str = Field(min_length=1, max_length=4000)
    appearance: str = Field(default="", max_length=4000)
    personality: str = Field(default="", max_length=4000)
    capabilities: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def identity_present(self):
        if not self.identity.strip():
            raise ValueError("опишите, кто ваш герой")
        return self


class StartingAllocationProposal(ClosedModel):
    abilities: AbilityScores
    explanations: dict[AbilityKey, str]

    @model_validator(mode="after")
    def exact_allocation(self):
        if sorted(self.abilities.model_dump().values()) != list(START_ARRAY):
            raise ValueError("используйте каждое значение 15, 14, 13, 12, 10, 8 ровно один раз")
        if set(self.explanations) != set(ABILITY_KEYS) or not all(x.strip() for x in self.explanations.values()):
            raise ValueError("нужно объяснение каждой характеристики")
        return self


class HeroBudget(ClosedModel):
    initial_scores: AbilityScores
    growth_total: Count = 0
    growth_allocations: dict[AbilityKey, Count] = Field(default_factory=dict)
    unspent: Count = 0

    @model_validator(mode="after")
    def balanced(self):
        if sorted(self.initial_scores.model_dump().values()) != list(START_ARRAY):
            raise ValueError("неверный стартовый набор")
        if sum(self.growth_allocations.values()) + self.unspent != self.growth_total:
            raise ValueError("бюджет развития не сходится")
        return self


class UniversalSheet(ClosedModel):
    schema_version: Literal[1] = 1
    rules_version: Literal["universal.v1"] = "universal.v1"
    level: Count = Field(default=1, ge=1)
    xp: Count = 0
    abilities: AbilityScores
    description: HeroDescription
    trained: list[str] = Field(default_factory=list)
    unspent_points: Count = 0
    budget: HeroBudget | None = None


class ActorDerived(ClosedModel):
    hp_max: Count
    energy_max: dict[EnergyKey, Count]
    ac: SignedCount
    modifiers: dict[AbilityKey, SignedCount]


class HeroCard(ClosedModel):
    id: str
    name: str
    revision: int
    level: Count
    sheet: UniversalSheet
    derived: ActorDerived
    hp: Count
    energies: dict[EnergyKey, Count]
    equipment: list[dict] = Field(default_factory=list)
    learned_abilities: list[dict] = Field(default_factory=list)
    editable: bool = True


class UniversalGameCard(HeroCard):
    seat_id: str | None
    status: str
    editable: Literal[False] = False
