"""Compiler translating high-level narrative operations to executable tool calls."""

from __future__ import annotations

from app.core.narrative.contracts import (
    AdaptationProposal,
    NarrativeSnapshot,
)
from app.tools.operation_group import CompiledCall


def compile_operations(
    snapshot: NarrativeSnapshot,
    proposal: AdaptationProposal,
) -> tuple[CompiledCall, ...]:
    """Compile accepted narrative proposal operations into registered tool calls."""
    calls: list[CompiledCall] = []

    for index, op in enumerate(proposal.operations):
        call_key = f"{proposal.proposal_id}:{index}"

        if op.kind == "add_campaign_fact":
            calls.append(
                CompiledCall(
                    tool="apply_narrative_fact",
                    args={
                        "campaign_id": op.fact.ref.campaign_id,
                        "namespace": op.fact.ref.namespace,
                        "subject_id": op.fact.ref.subject_id,
                        "key": op.fact.ref.key,
                        "value": op.fact.value,
                        "kind": op.fact.kind,
                        "temporal_semantics": op.fact.temporal_semantics,
                        "freedom": op.fact.freedom,
                        "audience": list(op.fact.audience),
                        "depends_on": [d.model_dump() for d in op.fact.depends_on],
                        "snapshot_ref": op.fact.ref.snapshot_ref.model_dump(),
                    },
                    call_key=call_key,
                    metadata={"operation": op.kind},
                )
            )

        elif op.kind == "revise_draft_fact":
            calls.append(
                CompiledCall(
                    tool="apply_narrative_fact",
                    args={
                        "campaign_id": op.target_ref.campaign_id,
                        "namespace": op.target_ref.namespace,
                        "subject_id": op.target_ref.subject_id,
                        "key": op.target_ref.key,
                        "value": op.new_value,
                        "freedom": "draft",
                    },
                    call_key=call_key,
                    metadata={"operation": op.kind},
                )
            )

        elif op.kind == "develop_actor_role":
            calls.append(
                CompiledCall(
                    tool="apply_narrative_fact",
                    args={
                        "campaign_id": snapshot.source.campaign_id,
                        "namespace": "campaign",
                        "subject_id": op.entity_id,
                        "key": "role",
                        "value": op.new_role,
                        "kind": "truth",
                        "temporal_semantics": "current_state",
                        "freedom": "committed",
                        "audience": ["party"],
                        "depends_on": [],
                        "snapshot_ref": {
                            "kind": "event",
                            "source_id": proposal.proposal_id,
                            "typed_address": f"campaign:{op.entity_id}:role",
                        },
                    },
                    call_key=call_key,
                    metadata={"operation": op.kind, "entity_id": op.entity_id},
                )
            )

        elif op.kind == "upsert_thread":
            calls.append(
                CompiledCall(
                    tool="apply_narrative_thread",
                    args={
                        "campaign_id": snapshot.source.campaign_id,
                        "thread": op.thread.model_dump(),
                    },
                    call_key=call_key,
                    metadata={"operation": op.kind, "thread_id": op.thread.id},
                )
            )

        elif op.kind == "transition_thread":
            calls.append(
                CompiledCall(
                    tool="apply_narrative_thread",
                    args={
                        "campaign_id": snapshot.source.campaign_id,
                        "thread_id": op.thread_id,
                        "target_status": op.target_status,
                    },
                    call_key=call_key,
                    metadata={"operation": op.kind, "thread_id": op.thread_id},
                )
            )

        elif op.kind == "revise_future_situation":
            calls.append(
                CompiledCall(
                    tool="apply_future_situation",
                    args={
                        "campaign_id": snapshot.source.campaign_id,
                        "patch": op.patch.model_dump(),
                    },
                    call_key=call_key,
                    metadata={"operation": op.kind},
                )
            )

        elif op.kind == "change_front_intent":
            calls.append(
                CompiledCall(
                    tool="apply_existing_front_intent",
                    args={
                        "campaign_id": snapshot.source.campaign_id,
                        "front_ref": op.front_ref.model_dump(),
                        "new_intent": op.new_intent,
                        "status": op.status,
                    },
                    call_key=call_key,
                    metadata={"operation": op.kind},
                )
            )

        elif op.kind == "reveal_fact":
            calls.append(
                CompiledCall(
                    tool="learn_fact",
                    args={
                        "character_ids": list(op.audience),
                        "fact_address": f"{op.fact_ref.namespace}:{op.fact_ref.subject_id}:{op.fact_ref.key}",
                    },
                    call_key=call_key,
                    metadata={"operation": op.kind},
                )
            )

        elif op.kind == "introduce_actor":
            if op.mode == "materialize":
                calls.append(
                    CompiledCall(
                        tool="spawn_entity",
                        args={
                            "creature_template_id": op.template_id,
                            "name": op.public_description,
                            "attitude": op.attitude,
                            "description": op.public_description,
                            "location_id": op.place_ref,
                            "actor_slot": op.actor_slot,
                        },
                        call_key=call_key,
                        local_binding=op.actor_slot,
                        metadata={"operation": op.kind, "actor_slot": op.actor_slot},
                    )
                )
            else:
                calls.append(
                    CompiledCall(
                        tool="apply_narrative_actor_sketch",
                        args={
                            "campaign_id": snapshot.source.campaign_id,
                            "actor_slot": op.actor_slot,
                            "template_id": op.template_id,
                            "place_ref": op.place_ref,
                            "attitude": op.attitude,
                            "public_description": op.public_description,
                        },
                        call_key=call_key,
                        local_binding=op.actor_slot,
                        metadata={"operation": op.kind, "actor_slot": op.actor_slot},
                    )
                )

        elif op.kind == "settle_standing_response":
            how_text = "; ".join(op.settled_effects) if op.settled_effects else proposal.summary
            calls.append(
                CompiledCall(
                    tool="resolve_response",
                    args={
                        "response_id": op.response_id,
                        "how": how_text or "разрешено в ходе адаптации сюжета",
                    },
                    call_key=call_key,
                    metadata={"operation": op.kind, "response_id": op.response_id},
                )
            )

        elif op.kind == "advance_front":
            calls.append(
                CompiledCall(
                    tool="apply_advance_front",
                    args={
                        "campaign_id": snapshot.source.campaign_id,
                        "front_ref": op.front_ref.model_dump(),
                        "steps": op.steps,
                        "ground_ref": op.ground_ref,
                    },
                    call_key=call_key,
                    metadata={"operation": op.kind},
                )
            )

    return tuple(calls)
