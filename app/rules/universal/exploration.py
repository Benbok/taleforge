"""Closed semantic actions and server budgets for stage2A. No storage or model I/O."""

import hashlib
import json
from typing import Literal

from pydantic import Field, model_validator

from app.rules.universal.contracts import AbilityKey, ClosedModel, Count
from app.rules.universal.profiles import ActionOutcome, CheckNarration

SourceKind = Literal["mundane", "supernatural", "item"]
ResolutionKind = Literal["automatic", "check", "attack", "resistance"]
EffectKind = Literal[
    "observe",
    "speak",
    "wait",
    "hold_breath",
    "cosmetic",
    "illumination",
    "camouflage",
    "change_form",
    "create_object",
    "take",
    "place",
    "give",
    "fill",
    "pour",
    "empty",
    "consume",
    "dismiss",
    "damage",
    "heal",
    "cannot_move",
    "cannot_act",
    "cannot_target",
    "check_bonus",
    "defense_bonus",
]
ObjectTemplate = Literal["vessel", "wood_source", "water_source", "energy_tonic", "observer"]
TIMED_KINDS = frozenset(
    {
        "illumination",
        "camouflage",
        "change_form",
        "hold_breath",
        "cannot_move",
        "cannot_act",
        "cannot_target",
        "check_bonus",
        "defense_bonus",
    }
)
ORDINARY_KINDS = frozenset(
    {"observe", "speak", "wait", "hold_breath", "take", "place", "give", "fill", "pour", "empty", "consume", "dismiss"}
)
MAGIC_KINDS = frozenset(
    {
        "cosmetic",
        "illumination",
        "camouflage",
        "change_form",
        "create_object",
        "damage",
        "heal",
        "cannot_move",
        "cannot_act",
        "cannot_target",
        "check_bonus",
        "defense_bonus",
    }
)
MATERIALS = Literal["wood", "plant", "stone"]


class RequirementV2(ClosedModel):
    id: str = Field(min_length=1, max_length=64)
    quote: str = Field(min_length=1, max_length=1000)
    effect: EffectKind


class EffectIntentV2(ClosedModel):
    kind: EffectKind
    required_by: list[str] = Field(default_factory=list, max_length=16)
    target_id: str | None = Field(default=None, max_length=64)
    source_id: str | None = Field(default=None, max_length=64)
    object_id: str | None = Field(default=None, max_length=64)
    recipient_id: str | None = Field(default=None, max_length=64)
    effect_id: str | None = Field(default=None, max_length=64)
    label: str = Field(default="", max_length=128)
    appearance: str = Field(default="", max_length=500)
    lifetime: Literal["instant", "timed", "permanent"] = "instant"
    template: ObjectTemplate = "vessel"
    material: MATERIALS = "wood"
    form: Literal["plant_bush"] = "plant_bush"
    aspect: Literal["general", "sight", "hearing"] = "general"
    capacity_ml: int = Field(default=300, ge=1, le=2000, strict=True)
    amount: Count = Field(default=300, ge=1, le=1_000_000)
    quantity: int = Field(default=1, ge=1, le=10, strict=True)

    @model_validator(mode="after")
    def lifetime_supported(self):
        if self.lifetime == "permanent" and self.kind != "create_object":
            raise ValueError("Only a created ordinary object may be a permanent result")
        return self


class IntroductionV2(ClosedModel):
    ref: str = Field(min_length=1, max_length=48)
    template: ObjectTemplate
    name: str = Field(min_length=1, max_length=128)
    evidence_quote: str = Field(min_length=1, max_length=1000)
    amount: Count = Field(default=1000, ge=1, le=1_000_000)


class AbilityDefinitionV2(ClosedModel):
    schema_version: Literal[2] = 2
    id: str = Field(default="", max_length=128)
    revision: Count = Field(default=1, ge=1)
    name: str = Field(min_length=1, max_length=128)
    source: SourceKind
    delivery: Literal["ordinary", "spell", "innate", "item"] = "spell"
    attribute: AbilityKey = "wis"
    intensity: Literal["light", "normal", "strong"] = "light"
    target_count: int = Field(default=1, ge=1, le=100, strict=True)
    duration_seconds: Count = Field(default=18, ge=1, le=600)
    effects: list[EffectIntentV2] = Field(min_length=1, max_length=16)

    @model_validator(mode="after")
    def energy_source(self):
        if self.source == "supernatural" and self.attribute == "con":
            raise ValueError("CON has no supernatural energy pool")
        return self


class IntentV2(ClosedModel):
    schema_version: Literal[2] = 2
    name: str = Field(default="", max_length=128)
    source: SourceKind
    delivery: Literal["ordinary", "spell", "innate", "item"] = "ordinary"
    resolution: ResolutionKind = "check"
    attribute: AbilityKey = "wis"
    intensity: Literal["light", "normal", "strong"] = "normal"
    difficulty: int = Field(default=12, ge=1, le=40, strict=True)
    edge: Literal["normal", "advantage", "disadvantage"] = "normal"
    targets: list[str] = Field(default_factory=list, max_length=100)
    requirements: list[RequirementV2] = Field(default_factory=list, max_length=16)
    effects: list[EffectIntentV2] = Field(min_length=1, max_length=16)
    introductions: list[IntroductionV2] = Field(default_factory=list, max_length=8)
    duration_seconds: Count = Field(default=18, ge=1, le=600)
    elapsed_game_seconds: Count = Field(default=6, ge=0, le=3600)
    public_reason: str = Field(default="", max_length=4000)
    check_outcomes: CheckNarration | None = None
    known_profile_id: str | None = Field(default=None, max_length=128)
    known_revision: Count = Field(default=1, ge=1)


class IntentReview(ClosedModel):
    verdict: Literal["pass", "mismatch", "clarify", "unsupported"]
    message: str = Field(default="", max_length=1000)
    covered_requirements: list[str] = Field(default_factory=list, max_length=16)


class ExplorationAction(ClosedModel):
    schema_version: Literal[2] = 2
    actor_id: str
    source_message_id: str
    source_hash: str
    definition: AbilityDefinitionV2
    resolution: ResolutionKind
    attribute: AbilityKey
    difficulty: int = Field(ge=1, le=40, strict=True)
    edge: Literal["normal", "advantage", "disadvantage"] = "normal"
    targets: list[str] = Field(min_length=1, max_length=100)
    operations: list[EffectIntentV2] = Field(min_length=1, max_length=16)
    introductions: list[IntroductionV2] = Field(default_factory=list, max_length=8)
    cost: Count
    elapsed_game_seconds: Count
    check_outcomes: CheckNarration | None = None
    public_reason: str = Field(default="", max_length=4000)


class EffectChange(ClosedModel):
    kind: str
    subject_id: str
    description: str
    data: dict = Field(default_factory=dict)
    private: bool = False


class ExplorationOutcome(ActionOutcome):
    schema_version: Literal[2] = 2
    changes: list[EffectChange] = Field(default_factory=list)
    ability_ref: str | None = None
    elapsed_game_seconds: Count = 0
    game_seconds: Count = 0


def definition_key(definition: AbilityDefinitionV2) -> str:
    data = definition.model_dump(mode="json", exclude={"id", "revision", "name"})
    bindings = {
        "target_id",
        "source_id",
        "object_id",
        "recipient_id",
        "effect_id",
        "label",
        "appearance",
        "required_by",
    }
    data["effects"] = [effect.model_dump(mode="json", exclude=bindings) for effect in definition.effects]
    return "ability2-" + hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:24]


def exploration_cost(definition: AbilityDefinitionV2, level: int) -> int:
    if type(level) is not int or level < 1:
        raise ValueError("Level must be a positive exact integer")
    if definition.source != "supernatural":
        return 0
    base = {"light": 1, "normal": 3, "strong": 12}[definition.intensity] * level
    units = 0
    for effect in definition.effects:
        if effect.kind == "hold_breath":
            continue  # Physical auxiliary action is not a second spell.
        timed = effect.kind in TIMED_KINDS or effect.lifetime == "timed"
        duration = (definition.duration_seconds + 5) // 6 if timed else 1
        units += duration * effect.quantity
    return base * max(1, units) * definition.target_count


def exploration_capabilities():
    return dict(
        schema_version=2,
        ordinary_effects=sorted(ORDINARY_KINDS),
        supernatural_effects=sorted(MAGIC_KINDS),
        default_action_seconds="6",
        default_effect_seconds="18",
        max_effect_seconds="600",
        every_supernatural_use_costs_energy=True,
        forms=["plant_bush"],
        object_templates=["vessel", "wood_source", "water_source", "energy_tonic", "observer"],
    )
