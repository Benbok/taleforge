"""Canonical executable actions shared by compilation and atomic resolution."""

from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from app.rules.universal.contracts import ClosedModel, Count
from app.rules.universal.profiles import EffectSpec, ProfileSpec


class ActionRef(ClosedModel):
    profile_id: str = Field(min_length=1, max_length=128)
    revision: Count = Field(ge=1)


class ProposedAction(ClosedModel):
    ref: ActionRef
    actor_id: str
    targets: list[str] = Field(default_factory=list, max_length=100)
    profile: ProfileSpec
    operations: list[EffectSpec] = Field(default_factory=list, max_length=16)
    reason: str = Field(default="", max_length=4000)
    difficulty: int = Field(default=12, ge=1, le=40, strict=True)
    edge: Literal["normal", "advantage", "disadvantage"] = "normal"
    critical_failure_consequence: Literal["self_damage_1"] = "self_damage_1"


@dataclass
class ResolutionContext:
    session: object
    campaign_id: str
    user_id: str
    seat_id: str
    actor_id: str
    dice: object
    allowed_target_ids: frozenset[str] | None = None
