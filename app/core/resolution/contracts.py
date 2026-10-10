"""Versioned resolution contracts, independent of tools and language models."""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

FailureCategory = Literal["invalid_arguments", "rule_denial", "unsupported", "technical_safe", "unknown"]


@dataclass(frozen=True)
class ActionContext:
    ref: "ActionRef"
    verbs: tuple[str, ...]
    target_ids: tuple[str, ...]
    place_id: str | None
    parsed: bool
    affected_in_combat: bool
    combat_related: bool
    completed_parts: tuple[int, ...]
    module_data_known: bool
    canonical_denial: bool


@dataclass(frozen=True)
class CapabilitySpec:
    id: str
    action_class: Literal["noncombat", "combat"]
    verbs: frozenset[str]
    operations: frozenset[str]
    atomic: bool
    allow_unsupported: bool
    allow_safe_failure: bool


@dataclass(frozen=True)
class Admission:
    route: Literal["ordinary", "repair", "fallback", "deny"]
    reason_code: str


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1


class ActionRef(Contract):
    campaign_id: str
    source_kind: Literal["message", "standing_response", "event"]
    source_id: str
    actor_id: str
    part: int = Field(ge=0)


class FailureInfo(Contract):
    code: str
    category: FailureCategory
    rolled_back: bool
    attempt_id: str


class ResolutionResult(Contract):
    execution: Literal["applied", "denied", "failed", "repeated"]
    game_outcome: Literal["success", "partial", "failure"] | None = None
    event_ids: list[str] = Field(default_factory=list)
    completed_parts: list[int] = Field(default_factory=list)
    failure: FailureInfo | None = None


def normalize_result(raw: dict[str, Any], *, attempt_id: str) -> ResolutionResult:
    """Adapt legacy tool responses without inferring permission from error text."""
    if raw.get("ok") is True:
        result = raw.get("result") or {}
        outcome = "failure" if result.get("success") is False else "success"
        return ResolutionResult(
            execution="repeated" if raw.get("repeated") else "applied",
            game_outcome=outcome,
            event_ids=[raw["event_id"]] if raw.get("event_id") else [],
        )
    failure = FailureInfo.model_validate(
        {
            **raw.get("failure", {"code": "unclassified", "category": "unknown", "rolled_back": False}),
            "attempt_id": attempt_id,
        }
    )
    return ResolutionResult(
        execution="failed" if failure.category == "technical_safe" else "denied",
        failure=failure,
    )
