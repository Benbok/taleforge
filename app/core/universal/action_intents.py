"""Untrusted semantic model choices, separate from executable runtime operations."""

import json
from typing import Literal

from pydantic import Field, model_validator

from app.rules.universal.contracts import AbilityKey, ClosedModel
from app.rules.universal.profiles import ProfileSpec

ActionCategory = Literal["narrative", "ordinary_check", "ability", "weapon_attack", "world_denial", "unsupported"]
IntentEffect = Literal[
    "check", "damage", "heal", "cannot_act", "cannot_move", "cannot_target", "check_bonus", "defense_bonus", "narrative"
]


class EffectIntent(ClosedModel):
    kind: IntentEffect
    resistance_attribute: AbilityKey | None = None


class ActionIntent(ClosedModel):
    kind: ActionCategory
    name: str = Field(default="", max_length=128)
    reason: str = Field(default="", max_length=4000)
    public_reason: str = Field(default="", max_length=4000)
    attribute: AbilityKey = "wis"
    difficulty: int = Field(default=12, ge=1, le=40, strict=True)
    effect: IntentEffect = "check"
    extra_effects: list[EffectIntent] = Field(default_factory=list, max_length=15)
    intensity: Literal["light", "normal", "strong"] = "normal"
    base_dice: Literal["1d4", "1d6", "1d8"] = "1d6"
    duration: int = Field(default=1, ge=1, le=100, strict=True)
    clock: Literal["immediate", "turn", "round", "step", "scene"] = "immediate"
    target_scope: Literal["self", "actors", "scene"] = "self"
    targets: list[str] = Field(default_factory=list, max_length=100)
    known_profile_id: str | None = Field(default=None, min_length=1, max_length=128)
    known_revision: int = Field(default=1, ge=1, strict=True)


class LegacyAdmission(ClosedModel):
    """Read old saved admissions and deterministic provider fixtures without trusting their labels."""

    kind: Literal["denied", "narrative", "check", "ability"]
    reason: str = Field(min_length=1, max_length=4000)
    public_reason: str = Field(default="", max_length=4000)
    attribute: AbilityKey = "wis"
    difficulty: int = Field(default=12, ge=1, le=40, strict=True)
    profile: ProfileSpec | None = None
    targets: list[str] = Field(default_factory=list, max_length=100)
    known_profile_id: str | None = None
    known_revision: int = Field(default=1, ge=1, strict=True)

    @model_validator(mode="after")
    def compatible_fields(self):
        if self.kind in {"narrative", "denied", "check"} and (self.profile is not None or self.known_profile_id):
            raise ValueError("Only admitted abilities may supply profiles")
        return self


def parse_intent(raw: str | dict):
    if isinstance(raw, str):
        raw = raw.strip()
        if raw.startswith("```") and raw.endswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        raw = json.loads(raw)
    if not isinstance(raw, dict):
        raise ValueError("Action proposal must be an object")
    if "profile" in raw or raw.get("kind") in {"check", "denied"}:
        return LegacyAdmission.model_validate(raw)
    return ActionIntent.model_validate(raw)
