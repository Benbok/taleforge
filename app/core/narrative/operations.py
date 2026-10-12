"""Static registry and specifications for narrative adaptation operations."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.core.narrative.contracts import LocalRef, Operation


class OperationSpec(BaseModel):
    """Specification of an adaptation operation kind and its static constraints."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str
    version: int = 1
    scopes: tuple[Literal["scene", "future"], ...]
    ground_kinds: tuple[Literal["consequence", "relationship", "interest", "divergence", "world_time"], ...]
    keys: tuple[str, ...] = ()
    cost: int = 0


GATE_A_ACTIVE_KINDS: frozenset[str] = frozenset(
    {
        "add_campaign_fact",
        "develop_actor_role",
        "revise_future_situation",
        "change_front_intent",
        "upsert_thread",
        "transition_thread",
        "reveal_fact",
    }
)

ACTIVE_OPERATION_KINDS: frozenset[str] = frozenset(
    GATE_A_ACTIVE_KINDS
    | {
        "introduce_actor",
        "settle_standing_response",
        "revise_draft_fact",
    }
)


def resolve_local_ref(bindings: dict[str, str], ref: LocalRef) -> str:
    """Resolve a LocalRef actor_slot against already executed batch entity bindings."""
    if ref.actor_slot not in bindings:
        raise ValueError(f"LocalRef actor_slot '{ref.actor_slot}' not found in executed bindings")
    return bindings[ref.actor_slot]

_OPERATION_SPECS: tuple[OperationSpec, ...] = (
    OperationSpec(
        kind="add_campaign_fact",
        version=1,
        scopes=("scene", "future"),
        ground_kinds=("consequence", "relationship", "divergence"),
        keys=("role", "motivation", "relationship", "secret_truth", "situation_premise"),
        cost=1,
    ),
    OperationSpec(
        kind="revise_draft_fact",
        version=1,
        scopes=("scene", "future"),
        ground_kinds=("divergence", "relationship"),
        keys=("role", "motivation", "relationship", "secret_truth", "situation_premise"),
        cost=0,
    ),
    OperationSpec(
        kind="develop_actor_role",
        version=1,
        scopes=("scene", "future"),
        ground_kinds=("consequence", "relationship", "interest", "divergence"),
        keys=("role", "motivation"),
        cost=0,
    ),
    OperationSpec(
        kind="introduce_actor",
        version=1,
        scopes=("scene", "future"),
        ground_kinds=("consequence", "relationship", "divergence"),
        keys=(),
        cost=1,
    ),
    OperationSpec(
        kind="revise_future_situation",
        version=1,
        scopes=("future",),
        ground_kinds=("consequence", "relationship", "divergence"),
        keys=(
            "update_open_node",
            "add_open_node",
            "bypass_open_node",
            "update_open_act",
            "retire_pending_act",
            "update_question",
        ),
        cost=0,
    ),
    OperationSpec(
        kind="change_front_intent",
        version=1,
        scopes=("scene", "future"),
        ground_kinds=("consequence", "relationship", "divergence", "world_time"),
        keys=(),
        cost=0,
    ),
    OperationSpec(
        kind="advance_front",
        version=1,
        scopes=("scene", "future"),
        ground_kinds=("world_time", "consequence"),
        keys=(),
        cost=0,
    ),
    OperationSpec(
        kind="upsert_thread",
        version=1,
        scopes=("scene", "future"),
        ground_kinds=("interest", "divergence", "consequence"),
        keys=(),
        cost=0,
    ),
    OperationSpec(
        kind="transition_thread",
        version=1,
        scopes=("scene", "future"),
        ground_kinds=("consequence", "relationship", "divergence", "interest"),
        keys=(),
        cost=0,
    ),
    OperationSpec(
        kind="reveal_fact",
        version=1,
        scopes=("scene",),
        ground_kinds=("consequence", "interest"),
        keys=(),
        cost=0,
    ),
    OperationSpec(
        kind="settle_standing_response",
        version=1,
        scopes=("scene", "future"),
        ground_kinds=("relationship", "consequence"),
        keys=(),
        cost=0,
    ),
)


def operation_specs() -> tuple[OperationSpec, ...]:
    """Return all defined operation specifications."""
    return _OPERATION_SPECS


def novelty_cost(
    operations: tuple[Operation, ...],
    existing_slots: frozenset[str] = frozenset(),
) -> int:
    """Calculate the aggregate novelty cost of a batch of operations."""
    total = 0
    seen_slots: set[str] = set()

    for op_item in operations:
        if op_item.kind == "add_campaign_fact":
            total += 1
        elif op_item.kind == "introduce_actor":
            if op_item.mode == "sketch":
                continue
            if op_item.actor_slot in existing_slots or op_item.actor_slot in seen_slots:
                continue
            seen_slots.add(op_item.actor_slot)
            total += 1

    return total
