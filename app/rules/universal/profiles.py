"""Bounded, deterministic Universal prototype math; no persistence or model calls.

Status budgets are provisional designer configuration, not approved balance.
The server still authorizes ownership, equipped items and applicability.
"""

from __future__ import annotations

from fractions import Fraction
from math import ceil
from typing import Literal

from pydantic import Field, model_validator

from app.rules.universal.contracts import (
    AbilityKey,
    ClosedModel,
    Count,
    EnergyKey,
    SignedCount,
    UniversalSheet,
)
from app.rules.universal.failures import ActionFailure

ItemStatus = Literal["common", "rare", "unique", "epic"]
Intensity = Literal["light", "normal", "strong"]
EffectKind = Literal[
    "damage", "heal", "check_bonus", "defense_bonus", "cannot_act", "cannot_move", "cannot_target", "narrative"
]
INTENSITY_MULTIPLIERS = {"light": Fraction(1, 2), "normal": Fraction(1), "strong": Fraction(2)}
RARITY_MULTIPLIERS = {"common": Fraction(1), "rare": Fraction(5, 4), "unique": Fraction(3, 2), "epic": Fraction(2)}
ITEM_BONUS_BUDGETS = {"common": 0, "rare": 1, "unique": 2, "epic": 3}
CONTROLS = {"cannot_act", "cannot_move", "cannot_target"}


class ResistanceSpec(ClosedModel):
    source_attribute: AbilityKey
    attribute: AbilityKey
    difficulty: SignedCount | None = None
    on_success: Literal["negate"] = "negate"
    on_failure: Literal["apply"] = "apply"


class EffectSpec(ClosedModel):
    id: str = Field(min_length=1, max_length=128)
    source_id: str = Field(default="", max_length=128)
    target_id: str = Field(default="", max_length=128)
    kind: EffectKind
    value: SignedCount = 0
    clock: Literal["immediate", "turn", "round", "step", "scene"] = "immediate"
    remaining: Count = 1
    starts_at: Count = 0
    resistance: ResistanceSpec | None = None

    @model_validator(mode="after")
    def bounded_value(self):
        if self.kind in CONTROLS | {"narrative"} and self.value != 0:
            raise ValueError("effect value is compiled from the profile, never supplied as arbitrary damage")
        if self.kind in {"damage", "heal"} and self.value < 0:
            raise ValueError("damage and healing cannot be negative")
        if self.kind in {"check_bonus", "defense_bonus"} and not 1 <= self.value <= 3:
            raise ValueError("numeric bonus must fit the provisional 1..3 budget")
        return self


class ProfileSpec(ClosedModel):
    id: str = Field(min_length=1, max_length=128)
    revision: Count = Field(default=1, ge=1)
    attribute: AbilityKey
    kind: Literal["damage", "heal", "control", "defense", "narrative", "check"]
    use_kind: Literal["ability", "weapon_basic"] = "ability"
    base_dice: Literal["1d4", "1d6", "1d8"] = "1d6"
    attack_bonus: Count = 0
    damage_bonus: Count = 0
    intensity: Intensity = "normal"
    rarity: ItemStatus = "common"
    target_count: int = Field(default=1, ge=1, le=100, strict=True)
    duration: Count = Field(default=1, ge=1)
    resource_key: EnergyKey | None = None
    effects: list[EffectSpec] = Field(default_factory=list, max_length=16)
    use_conditions: list[str] = Field(default_factory=list, max_length=16)
    trained: bool = False
    item_id: str | None = Field(default=None, min_length=1, max_length=128)

    @model_validator(mode="after")
    def bounded_profile(self):
        budget = ITEM_BONUS_BUDGETS[self.rarity]
        if self.rarity != "common" and self.item_id is None:
            raise ValueError("rarity power requires a participating saved item")
        if self.attack_bonus + self.damage_bonus > budget:
            raise ValueError("item bonuses exceed the shared status budget")
        if (self.attack_bonus or self.damage_bonus) and self.item_id is None:
            raise ValueError("item bonuses require a participating saved item")
        if self.base_dice == "1d8" and not any(x.strip() for x in self.use_conditions):
            raise ValueError("heavy dice require a saved use condition")
        if len({e.id for e in self.effects}) != len(self.effects):
            raise ValueError("effect IDs must be unique")
        numeric = [e for e in self.effects if e.kind != "narrative"]
        if self.kind == "narrative" and numeric:
            raise ValueError("narrative profiles cannot grant numeric effects")
        if self.kind == "control" and (not numeric or numeric[0].kind not in CONTROLS):
            raise ValueError("control requires a specific prohibition as its main effect")
        if self.kind == "defense" and (not numeric or numeric[0].kind not in {"check_bonus", "defense_bonus"}):
            raise ValueError("defense requires an explicit bounded bonus")
        if (
            self.kind == "check"
            and self.resource_key is None
            and (self.effects or self.intensity != "normal" or self.target_count != 1 or self.duration != 1)
        ):
            raise ValueError("ordinary free checks cannot add numeric effects or intensity")
        for effect in self.effects:
            if effect.kind in {"damage", "heal"} and effect.value != 0:
                raise ValueError("damage/heal templates are compiled from profile budgets")
            if effect.kind in {"check_bonus", "defense_bonus"}:
                if effect.value != {"light": 1, "normal": 2, "strong": 3}[self.intensity]:
                    raise ValueError("bonus must match the intensity budget")
            if effect.remaining > self.duration:
                raise ValueError("effect duration exceeds paid profile duration")
        if self.use_kind == "weapon_basic" and (
            self.kind != "damage"
            or self.intensity != "normal"
            or self.target_count != 1
            or self.duration != 1
            or self.effects
            or self.attribute not in {"str", "dex"}
        ):
            raise ValueError("only a single ordinary physical weapon attack may be free")
        return self


class EffectOutcome(ClosedModel):
    effect_id: str
    target_id: str
    applied: bool
    natural: int | None = Field(default=None, ge=1, le=20, strict=True)
    total: SignedCount | None = None
    difficulty: SignedCount | None = None


class DieProof(ClosedModel):
    sides: int = Field(ge=2, strict=True)
    value: int = Field(ge=1, strict=True)


class CheckProof(ClosedModel):
    target_id: str
    effect_id: str = "primary"
    attribute: AbilityKey
    natural: int = Field(ge=1, le=20, strict=True)
    modifier: SignedCount
    total: SignedCount
    difficulty: SignedCount | None = None
    success: bool
    mode: Literal["normal", "advantage", "disadvantage"] = "normal"
    kind: Literal["check", "attack", "resistance"] = "check"
    critical: bool = False
    critical_failure: bool = False
    invested: int = Field(default=0, ge=0, strict=True)


class CheckNarration(ClosedModel):
    success: str = Field(min_length=1, max_length=4000, description="Concrete observable success result, not trying.")
    failure: str = Field(
        min_length=1, max_length=4000, description="Concrete failure result, no invented world prohibition."
    )
    critical_success: str | None = Field(default=None, min_length=1, max_length=4000)
    critical_failure: str | None = Field(default=None, min_length=1, max_length=4000)

    @model_validator(mode="after")
    def distinct_results(self):
        self.success, self.failure = self.success.strip(), self.failure.strip()
        if not self.success or not self.failure or self.success == self.failure:
            raise ValueError("A check needs distinct, nonempty success and failure results")
        for critical, regular in [("critical_success", self.success), ("critical_failure", self.failure)]:
            value = getattr(self, critical)
            if value is not None:
                value = value.strip()
                if not value or value == regular:
                    raise ValueError("Critical consequences must be nonempty and distinct from ordinary results")
                setattr(self, critical, value)
        return self


class ActionOutcome(ClosedModel):
    status: Literal["applied", "denied", "repeated", "failed"] = "applied"
    success: bool = False
    natural: int | None = Field(default=None, ge=1, le=20, strict=True)
    total: SignedCount | None = None
    damage: Count = 0
    cost: Count = 0
    effect_outcomes: list[EffectOutcome] = Field(default_factory=list)
    public_effects: list[EffectSpec] = Field(default_factory=list)
    private_effects: list[EffectSpec] = Field(default_factory=list)
    critical: bool = False
    critical_failure: bool = False
    rolls: list[int] = Field(default_factory=list)
    failure: ActionFailure | None = None
    checks: list[CheckProof] = Field(default_factory=list)
    draws: list[DieProof] = Field(default_factory=list)
    description: str | None = Field(default=None, max_length=4000)


def validate_profile(profile: ProfileSpec | dict) -> ProfileSpec:
    # Revalidate even constructed/mutated Pydantic instances at the trust boundary.
    return ProfileSpec.model_validate(profile.model_dump() if isinstance(profile, ProfileSpec) else profile)


def _integer(value: int, minimum: int | None = None) -> int:
    if type(value) is not int or (minimum is not None and value < minimum):
        raise ValueError("expected an exact integer within the permitted range")
    return value


def numeric_component_count(profile: ProfileSpec) -> int:
    numeric = sum(e.kind != "narrative" for e in profile.effects)
    # control/defense encode their main component explicitly in effects.
    primary = profile.kind in {"damage", "heal"} or (profile.kind == "check" and profile.resource_key is not None)
    return numeric + primary


def resource_cost(profile: ProfileSpec, level: int) -> int:
    p = validate_profile(profile)
    _integer(level, 1)
    if p.use_kind == "weapon_basic":
        return 0
    q = INTENSITY_MULTIPLIERS[p.intensity]
    return level * ceil(3 * q * q) * p.target_count * p.duration * numeric_component_count(p)


def bind_resistance(resistance: ResistanceSpec, source_score: int) -> ResistanceSpec:
    score = _integer(source_score, 1)
    return ResistanceSpec.model_validate({**resistance.model_dump(), "difficulty": 10 + (score - 10) // 2})


def resolve_resistance(
    dice, target_id: str, effect_id: str, target_attribute: int, resistance: ResistanceSpec
) -> EffectOutcome:
    score = _integer(target_attribute, 1)
    if resistance.difficulty is None:
        raise ValueError("resistance DC must be fixed from source score before rolling")
    check = resolve_check(dice, score, False, resistance.difficulty)
    return EffectOutcome(
        effect_id=effect_id,
        target_id=target_id,
        natural=check.natural,
        total=check.total,
        difficulty=resistance.difficulty,
        applied=not check.success,
    )


def resolve_check(
    dice, attribute: int, trained: bool, difficulty: int, edge: str = "normal", bonus: int = 0
) -> ActionOutcome:
    score = _integer(attribute, 1)
    _integer(bonus, 0)
    _integer(difficulty)
    if type(trained) is not bool or edge not in {"normal", "advantage", "disadvantage"}:
        raise ValueError("invalid check parameters")
    rolls = [dice.d20()]
    if edge != "normal":
        rolls.append(dice.d20())
    natural = min(rolls) if edge == "disadvantage" else max(rolls)
    total = natural + (score - 10) // 2 + (2 if trained else 0) + bonus
    return ActionOutcome(
        success=natural == 20 or (natural != 1 and total >= difficulty),
        natural=natural,
        total=total,
        rolls=rolls,
        critical=natural == 20,
        critical_failure=natural == 1,
    )


def damage_amount(
    dice, sheet: UniversalSheet, profile: ProfileSpec, critical: bool = False, immune: bool = False
) -> int:
    p = validate_profile(profile)
    # Rarity may buy flat item bonuses OR a multiplier, never both.
    rarity = Fraction(1) if p.attack_bonus or p.damage_bonus else RARITY_MULTIPLIERS[p.rarity]
    sides = int(p.base_dice[2:])
    rolled = sum(dice.die(sides) for _ in range(2 if critical else 1))
    base = rolled + (getattr(sheet.abilities, p.attribute) - 10) // 2 + 2 * (sheet.level - 1) + p.damage_bonus
    amount = max(1, (INTENSITY_MULTIPLIERS[p.intensity] * rarity * max(0, base)).__floor__())
    return 0 if immune else amount


def resolve_attack(
    dice, sheet: UniversalSheet, target_ac: int, profile: ProfileSpec, critical: bool = False, immune: bool = False
) -> ActionOutcome:
    p = validate_profile(profile)
    _integer(target_ac)
    cost = resource_cost(p, sheet.level)
    check = resolve_check(dice, getattr(sheet.abilities, p.attribute), p.trained, target_ac - p.attack_bonus)
    critical_hit = check.natural == 20 or (critical and check.natural != 1)
    fumble = check.natural == 1
    success = not fumble and (critical_hit or check.success)
    damage = damage_amount(dice, sheet, p, critical_hit, immune) if success else 0
    return ActionOutcome(
        success=success,
        natural=check.natural,
        total=check.total + p.attack_bonus,
        damage=damage,
        cost=cost,
        critical=critical_hit,
        critical_failure=fumble,
        rolls=check.rolls,
    )


def restore(current: int, maximum: int, amount: int) -> int:
    _integer(current, 0)
    _integer(maximum, 0)
    _integer(amount, 0)
    if current > maximum:
        raise ValueError("current resource exceeds its maximum")
    return min(maximum, current + amount)
