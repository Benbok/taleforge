"""Serializable domain contracts and immutable DTOs for narrative adaptation.

All DTOs are frozen Pydantic models with schema_version=1, closed enums, and extra fields forbidden.
This module is isolated from DB, tools, agents, frameworks, and LLM providers.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class NarrativeContractModel(BaseModel):
    """Base immutable model for all narrative DTOs."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class NarrativePolicy(NarrativeContractModel):
    """Bounded server policy for admission, rates, and scopes."""

    version: int = 1
    mode: Literal["strict", "adaptive"] = "adaptive"
    allowed_scopes: tuple[Literal["scene", "future"], ...] = ("scene", "future")
    allowed_operation_kinds: tuple[str, ...] = (
        "add_campaign_fact",
        "develop_actor_role",
        "revise_future_situation",
        "change_front_intent",
        "upsert_thread",
        "transition_thread",
        "reveal_fact",
        "introduce_actor",
        "settle_standing_response",
        "revise_draft_fact",
    )
    max_operations: int = 8
    max_grounds: int = 8
    max_novelty_scene: int = 3
    max_novelty_session: int = 12
    max_offered_active_threads: int = 5
    max_llm_calls_per_job: int = 2
    max_snapshots_after_conflict: int = 1
    max_fact_dependencies: int = 16
    max_facts_visited: int = 64
    max_snapshot_grounds: int = 50
    max_snapshot_records: int = 80
    max_snapshot_threads: int = 20
    target_input_tokens: int = 6000
    max_claim_attempts: int = 6
    retry_intervals_seconds: tuple[int, ...] = (5, 15, 60)


class NarrativeSource(NarrativeContractModel):
    """Server-owned source identifier for scene or future adaptation."""

    campaign_id: str
    scope: Literal["scene", "future"]
    source_kind: Literal["turn", "work"]
    source_id: str
    stable_part: int = Field(default=0, ge=0)

    def source_key(self) -> str:
        """Stable string key used for idempotent receipts and leases."""
        return f"{self.campaign_id}:{self.source_kind}:{self.source_id}:{self.stable_part}"


class EvidenceRef(NarrativeContractModel):
    """Reference to durable historical evidence."""

    campaign_id: str
    kind: Literal["message", "event", "standing_response", "time_interval"]
    source_id: str


class EvidenceRecord(NarrativeContractModel):
    """Concrete evidence record loaded from campaign history."""

    ref: EvidenceRef
    status: Literal["applied", "stated", "question", "rejected", "observed", "elapsed"]
    subject_refs: tuple[str, ...] = ()
    audience: tuple[str, ...] = ()
    game_time: int = 0
    applied_result: str | None = None
    utterance_text: str | None = None


class Ground(NarrativeContractModel):
    """Verifiable justification for a narrative proposal."""

    kind: Literal["consequence", "relationship", "interest", "divergence", "world_time"]
    evidence_refs: tuple[EvidenceRef, ...]
    subject_refs: tuple[str, ...] = ()
    confidence: Literal["explicit", "inferred"] = "explicit"


class SnapshotRef(NarrativeContractModel):
    """Exact versioned address for immutable fact snapshots."""

    kind: Literal["package", "plan", "event"]
    source_id: str
    version: int | None = None
    typed_address: str


class FactRef(NarrativeContractModel):
    """Structured identifier for a narrative fact address."""

    campaign_id: str
    namespace: Literal["plan", "module", "campaign"]
    subject_id: str
    key: Literal["role", "motivation", "relationship", "secret_truth", "situation_premise"]
    version: int = 1
    snapshot_ref: SnapshotRef


class FactState(NarrativeContractModel):
    """Verified state of a narrative fact."""

    ref: FactRef
    kind: Literal["truth", "testimony", "intent"]
    temporal_semantics: Literal["historical", "current_state", "draft_only"]
    freedom: Literal["draft", "committed"]
    value: str
    audience: tuple[str, ...] = ()
    depends_on: tuple[FactRef, ...] = ()


class FactRevision(NarrativeContractModel):
    """Result of attempting to revise a draft narrative fact."""

    before: FactState
    after: FactState | None = None
    violations: tuple[str, ...] = ()


class ReadRef(NarrativeContractModel):
    """Read-set dependency element checked during optimistic concurrency."""

    kind: Literal["fact", "entity", "front", "thread", "permission"]
    id: str
    version: int | None = None
    digest: str | None = None


class FrontRef(NarrativeContractModel):
    """Structured reference to an antagonist front or campaign clock."""

    campaign_id: str
    source_kind: Literal["antagonist", "front"]
    source_id: str

    @property
    def id(self) -> str:
        return self.source_id


class FrontView(NarrativeContractModel):
    """Consistent read-view of an active front or antagonist threat."""

    ref: FrontRef
    owner_ref: str
    goal: str
    resource_refs: tuple[str, ...] = ()
    progress: int = 0
    maximum: int = 6
    status: Literal["active", "paused", "stopped", "completed"] = "active"
    known_fact_refs: tuple[FactRef, ...] = ()
    clock_at: int = 0
    period: int = 86400
    milestones: tuple[str, ...] = ()


class ReadyIntent(NarrativeContractModel):
    """Intent triggered by front readiness or clock threshold."""

    id: str
    front_ref: FrontRef
    kind: str
    description: str
    target_refs: tuple[str, ...] = ()
    payload: dict[str, Any] = Field(default_factory=dict)


class FrontTransition(NarrativeContractModel):
    """Result of advancing a front or changing its state."""

    front_ref: FrontRef
    previous_progress: int
    new_progress: int
    previous_status: str
    new_status: str
    transition_key: str
    violation: str | None = None
    ready_intent: ReadyIntent | None = None


class FrontTickResult(NarrativeContractModel):
    """Result of processing time ticks across all campaign fronts."""

    next_plan: dict[str, Any]
    progress_events: tuple[dict[str, Any], ...] = ()
    ready_intents: tuple[ReadyIntent, ...] = ()


class ThreadState(NarrativeContractModel):
    """Durable story hook or plot thread state."""

    id: str
    version: int = 1
    status: Literal["offered", "active", "resolved", "abandoned", "dormant", "hidden"] = "offered"
    audience: tuple[str, ...] = ()
    subject_refs: tuple[str, ...] = ()
    plan_refs: tuple[str, ...] = ()
    parent_id: str | None = None
    source_refs: tuple[str, ...] = ()


class ThreadTransition(NarrativeContractModel):
    """Result of attempting a thread state transition."""

    new_state: ThreadState | None = None
    violation: str | None = None


class VersionSet(NarrativeContractModel):
    """Set of version numbers required for optimistic concurrency guard."""

    world_revision: int
    plan_version: int
    narrative_revision: int
    policy_version: int
    operation_schema_version: int = 1


class Violation(NarrativeContractModel):
    """Structured error or policy violation."""

    code: str
    target_ref: str | None = None
    expected: str | None = None
    actual: str | None = None


class LocalRef(NarrativeContractModel):
    """Reference to an actor created by an earlier operation in the same batch."""

    actor_slot: str


class ActorAdmission(NarrativeContractModel):
    """Result of authorizing an actor slot for introduction or reuse."""

    allowed: bool
    reason_code: str
    existing_entity_id: str | None = None


class NarrativePermissions(NarrativeContractModel):
    """Explicit narrative permissions loaded from validated module metadata."""

    anchors: tuple[str, ...] = ()
    mutable_fact_addresses: tuple[str, ...] = ()
    operation_kinds: tuple[str, ...] = ()
    supplement_scopes: tuple[str, ...] = ()


class FuturePlanEdit(NarrativeContractModel):
    """Targeted edit to open nodes or acts in campaign plan."""

    kind: Literal[
        "update_open_node",
        "add_open_node",
        "bypass_open_node",
        "update_open_act",
        "retire_pending_act",
        "update_question",
    ]
    act_id: str
    node_id: str | None = None
    fields: dict[str, str] = Field(default_factory=dict)
    verified_refs: tuple[str, ...] = ()


class FutureSituationPatch(NarrativeContractModel):
    """Immutable sequence of targeted plan edits."""

    edits: tuple[FuturePlanEdit, ...] = ()


class QuestionState(NarrativeContractModel):
    """Dramatic campaign question and its resolution status."""

    id: str
    text: str
    subject_refs: tuple[str, ...] = ()
    status: Literal["open", "answered", "obsolete"] = "open"
    outcome: str | None = None


class SnapshotRequest(NarrativeContractModel):
    """Request DTO to assemble a bounded narrative snapshot."""

    source: NarrativeSource
    focus: str | None = None
    audience: tuple[str, ...] = ()
    evidence_refs: tuple[EvidenceRef, ...] = ()
    mutable_subject_refs: tuple[str, ...] = ()
    feedback: tuple[Violation, ...] = ()


class NarrativeSnapshot(NarrativeContractModel):
    """Serializable immutable snapshot for master/director authors."""

    source: NarrativeSource
    proposal_id: str
    base: VersionSet
    evidence: tuple[EvidenceRecord, ...] = ()
    facts: tuple[FactState, ...] = ()
    actors: tuple[str, ...] = ()
    fronts: tuple[FrontView, ...] = ()
    threads: tuple[ThreadState, ...] = ()
    read_set: tuple[ReadRef, ...] = ()
    permissions: NarrativePermissions = Field(default_factory=NarrativePermissions)
    budgets: dict[str, int] = Field(default_factory=dict)
    content_chain: tuple[str, ...] = ()
    feedback: tuple[Violation, ...] = ()
    author_attempt: int = 0


# Concrete Operation Models
class AddCampaignFactOp(NarrativeContractModel):
    kind: Literal["add_campaign_fact"] = "add_campaign_fact"
    fact: FactState


class ReviseDraftFactOp(NarrativeContractModel):
    kind: Literal["revise_draft_fact"] = "revise_draft_fact"
    target_ref: FactRef
    new_value: str


class DevelopActorRoleOp(NarrativeContractModel):
    kind: Literal["develop_actor_role"] = "develop_actor_role"
    entity_id: str
    new_role: str
    new_motivation: str | None = None


class IntroduceActorOp(NarrativeContractModel):
    kind: Literal["introduce_actor"] = "introduce_actor"
    actor_slot: str
    template_id: str
    place_ref: str
    attitude: Literal["friendly", "neutral", "hostile"] = "neutral"
    public_description: str
    mode: Literal["sketch", "materialize"] = "sketch"


class ReviseFutureSituationOp(NarrativeContractModel):
    kind: Literal["revise_future_situation"] = "revise_future_situation"
    patch: FutureSituationPatch


class ChangeFrontIntentOp(NarrativeContractModel):
    kind: Literal["change_front_intent"] = "change_front_intent"
    front_ref: FrontRef
    new_intent: str
    status: Literal["active", "paused", "stopped"] | None = None


class AdvanceFrontOp(NarrativeContractModel):
    kind: Literal["advance_front"] = "advance_front"
    front_ref: FrontRef
    steps: int = 1
    ground_ref: str | None = None


class UpsertThreadOp(NarrativeContractModel):
    kind: Literal["upsert_thread"] = "upsert_thread"
    thread: ThreadState


class TransitionThreadOp(NarrativeContractModel):
    kind: Literal["transition_thread"] = "transition_thread"
    thread_id: str
    target_status: Literal["offered", "active", "resolved", "abandoned", "dormant", "hidden"]


class RevealFactOp(NarrativeContractModel):
    kind: Literal["reveal_fact"] = "reveal_fact"
    fact_ref: FactRef
    audience: tuple[str, ...]


class SettleStandingResponseOp(NarrativeContractModel):
    kind: Literal["settle_standing_response"] = "settle_standing_response"
    response_id: str
    settled_effects: tuple[str, ...] = ()


Operation = Annotated[
    AddCampaignFactOp
    | ReviseDraftFactOp
    | DevelopActorRoleOp
    | IntroduceActorOp
    | ReviseFutureSituationOp
    | ChangeFrontIntentOp
    | AdvanceFrontOp
    | UpsertThreadOp
    | TransitionThreadOp
    | RevealFactOp
    | SettleStandingResponseOp,
    Field(discriminator="kind"),
]


class AdaptationProposal(NarrativeContractModel):
    """Proposal generated by master/director, awaiting admission and application."""

    schema_version: Literal[1] = 1
    proposal_id: str
    source: NarrativeSource
    base: VersionSet
    grounds: tuple[Ground, ...]
    summary: str
    operations: tuple[Operation, ...] = ()
    read_set: tuple[ReadRef, ...] = ()


class AdaptationAdmission(NarrativeContractModel):
    """Structured result of pure domain admission checks."""

    status: Literal["allowed", "denied", "deferred"]
    reason_code: str
    violations: tuple[Violation, ...] = ()
    read_set: tuple[ReadRef, ...] = ()
    novelty_cost: int = 0


class PublicEffect(NarrativeContractModel):
    """Public narration cue or verified state change for players."""

    kind: str
    description: str
    audience: tuple[str, ...] = ()


class AdaptationResult(NarrativeContractModel):
    """Final durable result of applying an adaptation proposal."""

    status: Literal["applied", "repeated", "no_change", "denied", "deferred", "stale", "failed"]
    reason_code: str
    event_ids: tuple[str, ...] = ()
    created_ids: tuple[str, ...] = ()
    versions: VersionSet | None = None
    budgets_used: dict[str, int] = Field(default_factory=dict)
    public_effects: tuple[PublicEffect, ...] = ()


class BoundaryRecord(NarrativeContractModel):
    """Durable trigger boundary that enqueues director work."""

    campaign_id: str
    kind: str
    source_id: str
    scope: Literal["scene", "future", "system"] = "future"
    evidence_refs: tuple[EvidenceRef, ...] = ()
    audience: tuple[str, ...] = ()
    focus: str | None = None
    session_budget_ref: str
    policy_version: int = 1

    @property
    def source_key(self) -> str:
        return f"{self.kind}:{self.source_id}"


class LeaseLost(RuntimeError):
    """Raised when a worker attempts to update a job with an expired or superseded lease."""


class WorkClaim(NarrativeContractModel):
    """Lease claim for background director worker jobs."""

    work_id: str
    campaign_id: str
    source: NarrativeSource
    proposal_id: str
    lease_token: str
    lease_until: datetime
    llm_calls: int = 0
    attempts: int = 0
    session_budget_ref: str
    phase: Literal["author", "apply"] = "author"
    draft: AdaptationProposal | None = None
    capacity_slot: int | None = None
    status: str = "preparing"
    # Boundary context preserved from the saved job (R11)
    evidence_refs: tuple[EvidenceRef, ...] = ()
    audience: tuple[str, ...] = ()
    focus: str | None = None
    mutable_subject_refs: tuple[str, ...] = ()
    feedback: tuple[Violation, ...] = ()


class DirectorInput(NarrativeContractModel):
    """Packed prompt and tool schema for director LLM call."""

    messages: tuple[dict[str, Any], ...] = ()
    tool_schema: dict[str, Any]
    permitted_refs: tuple[str, ...] = ()
    complete_for_edit: bool = True
    estimated_input_tokens: int = 0


class AuthorCallReport(NarrativeContractModel):
    """Runtime report of an author LLM invocation."""

    source: NarrativeSource
    author_attempt: int
    model: str
    tokens_in: int = 0
    tokens_out: int = 0
    cost: float = 0.0
    latency_ms: int = 0
    error: str | None = None


class PreparationReport(NarrativeContractModel):
    """Execution report from director narrative service."""

    work_id: str
    status: str
    reason_code: str
    calls_reserved: int = 0


class TurnBoundaryState(NarrativeContractModel):
    """Context state of the turn when evaluating narrative boundaries."""

    id: str
    phase: str = "turn"
    session_id: str | None = None
    focus: str | None = None
    audience: tuple[str, ...] | None = None
    external_boundary: bool = False


class NarrativePreparationStatusOut(NarrativeContractModel):
    """Safe preparation status exposed to campaign managers without spoilers or private reasons."""

    status: Literal["pending", "preparing", "ready", "failed"]
    error: str | None = None


def to_narrative_preparation_status(
    status_str: str | None,
    error: str | None = None,
) -> NarrativePreparationStatusOut:
    """Map domain preparation status into a safe public status."""
    st = (status_str or "").lower()
    if st in ("ready", "active", "done", "completed"):
        mapped = "ready"
    elif st in ("generating", "preparing", "in_progress", "busy"):
        mapped = "preparing"
    elif st in ("failed", "error"):
        mapped = "failed"
    else:
        mapped = "pending"
    return NarrativePreparationStatusOut(status=mapped, error=error)
