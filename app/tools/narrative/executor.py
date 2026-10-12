"""Durable execution of narrative adaptation proposals with receipts and guards (Task 9)."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.narrative.contracts import (
    AdaptationProposal,
    AdaptationResult,
    FactState,
    NarrativePolicy,
    NarrativeSource,
    SnapshotRef,
    SnapshotRequest,
    VersionSet,
)
from app.core.narrative.policy import admit_adaptation
from app.core.world_tx import WorldConflict, world_write
from app.db.models import Campaign, Event
from app.db.narrative import ensure_state
from app.rules.dice import Dice
from app.tools.narrative.compiler import compile_operations
from app.tools.narrative.context import load_snapshot
from app.tools.operation_group import CompiledCall, run_operation_group
from app.tools.registry import ToolContext, ToolError
from app.tools.runtime import open_context


def narrative_key(source: NarrativeSource) -> str:
    """Stable SHA-256 idempotency key for narrative adaptations."""
    return hashlib.sha256(source.source_key().encode("utf-8")).hexdigest()


async def find_receipt(session: AsyncSession, source: NarrativeSource) -> Event | None:
    """Find existing durable receipt for narrative source."""
    key = narrative_key(source)
    stmt = select(Event).where(
        Event.campaign_id == source.campaign_id,
        Event.idempotency_key == key,
        Event.tool == "adapt_story",
    )
    return await session.scalar(stmt)


async def write_fact_snapshots(ctx: ToolContext, changed: tuple[FactState, ...]) -> SnapshotRef:
    """Record immutable snapshot event for changed facts and return durable address."""
    ev = await ctx.record(
        "narrative_fact_snapshot",
        hidden=True,
        payload={
            "schema_version": 1,
            "facts": [f.model_dump() for f in changed],
        },
    )
    return SnapshotRef(
        kind="event",
        source_id=ev.id,
        version=1,
        typed_address=f"event:{ev.id}",
    )


async def apply_in_context(
    ctx: ToolContext,
    proposal: AdaptationProposal,
    *,
    policy: NarrativePolicy,
) -> AdaptationResult:
    """Validate and execute narrative adaptation proposal within active context.

    Follows spec §10.2:
    1. Search for receipt by stable source key. If present, return repeated result.
    2. Obtain world guard and verify optimistic revision concurrency.
    3. Reload snapshot, verify base and read_set, then run domain admission.
    4. Compile operations and run atomically via shared operation group runner.
    5. Save state revision, novelty budgets, fact snapshots, and durable parent receipt.
    """
    # 1. Receipt check
    receipt = await find_receipt(ctx.session, proposal.source)
    if receipt is not None:
        stored_payload = receipt.payload.get("adaptation") or {}
        stored = AdaptationResult.model_validate(stored_payload)
        return stored.model_copy(update={"status": "repeated"})

    # Check strict policy mode early
    if policy.mode == "strict":
        return AdaptationResult(
            status="denied",
            reason_code="policy_strict_mode",
            budgets_used={},
        )

    # 2. Concurrency guard: verify world revision
    if ctx.world.revision != proposal.base.world_revision:
        return AdaptationResult(
            status="stale",
            reason_code="stale_read_set",
            budgets_used={},
        )

    try:
        await world_write(ctx.session, ctx.campaign.id, expected_revision=proposal.base.world_revision)
    except WorldConflict:
        return AdaptationResult(
            status="stale",
            reason_code="stale_read_set",
            budgets_used={},
        )

    # 3. Re-read snapshot & verify base / read_set
    snapshot = await load_snapshot(
        ctx,
        SnapshotRequest(
            source=proposal.source,
            evidence_refs=tuple(ev for g in proposal.grounds for ev in g.evidence_refs),
        ),
        policy=policy,
    )
    # Match proposal_id so admission checks match the proposal's allocated id
    snapshot = snapshot.model_copy(update={"proposal_id": proposal.proposal_id})

    if (
        proposal.base.plan_version != snapshot.base.plan_version
        or proposal.base.narrative_revision != snapshot.base.narrative_revision
        or proposal.base.policy_version != snapshot.base.policy_version
    ):
        return AdaptationResult(
            status="stale",
            reason_code="stale_read_set",
            budgets_used={},
        )

    # Check read_set versions
    fact_map = {f"{f.ref.namespace}:{f.ref.subject_id}:{f.ref.key}": f for f in snapshot.facts}
    thread_map = {t.id: t for t in snapshot.threads}
    for item in proposal.read_set:
        if item.kind == "fact" and item.version is not None:
            f = fact_map.get(item.id)
            if f is not None and f.ref.version != item.version:
                return AdaptationResult(status="stale", reason_code="stale_read_set", budgets_used={})
        elif item.kind == "thread" and item.version is not None:
            t = thread_map.get(item.id)
            if t is not None and t.version != item.version:
                return AdaptationResult(status="stale", reason_code="stale_read_set", budgets_used={})

    # Domain admission check
    admission = admit_adaptation(snapshot, proposal, policy)
    if admission.status == "denied":
        return AdaptationResult(
            status="denied",
            reason_code=admission.reason_code,
            budgets_used={},
        )
    if admission.status == "deferred":
        return AdaptationResult(
            status="deferred",
            reason_code=admission.reason_code,
            budgets_used={},
        )

    # 4. Handle empty operations (no_change)
    if len(proposal.operations) == 0:
        res = AdaptationResult(
            status="no_change",
            reason_code="no_change",
            versions=snapshot.base,
            budgets_used={},
        )
        key = narrative_key(proposal.source)
        orig_call_key, orig_first_event = ctx.call_key, ctx._first_event
        ctx.call_key, ctx._first_event = key, None
        receipt_ev = await ctx.record(
            "adapt_story",
            hidden=True,
            payload={
                "schema_version": 1,
                "fingerprint": hashlib.sha256(proposal.model_dump_json().encode("utf-8")).hexdigest(),
                "source": proposal.source.model_dump(),
                "proposal_id": proposal.proposal_id,
                "adaptation": res.model_dump(),
            },
        )
        ctx.call_key, ctx._first_event = orig_call_key, orig_first_event
        res = res.model_copy(update={"event_ids": (receipt_ev.id,)})
        receipt_ev.payload["adaptation"] = res.model_dump()
        return res

    # 5. Compile and execute operations group
    calls = compile_operations(snapshot, proposal)

    def validate_step(c_ctx: ToolContext, call: CompiledCall, bindings: dict[str, Any]) -> None:
        # Combat scope lock check
        if c_ctx.world.scene.mode == "combat" or (proposal.source.scope == "scene" and c_ctx.world.in_fight()):
            raise ToolError("адаптация во время боя", code="combat_scope_locked", category="rule_denial")

        # Nonlocal actor check for scene scope
        if proposal.source.scope == "scene":
            actor_id = call.args.get("subject_id") or call.args.get("entity_id") or call.args.get("character_id")
            if actor_id:
                source_place = c_ctx.world.home() or c_ctx.world.scene.location_id
                if actor_id in c_ctx.world.characters:
                    ch = c_ctx.world.characters[actor_id]
                    if c_ctx.world.place_of(ch) != source_place:
                        raise ToolError("герой вне сцены", code="nonlocal_effect_denied", category="rule_denial")
                elif actor_id in c_ctx.world.entities:
                    ent = c_ctx.world.entities[actor_id]
                    if ent.location_id != source_place and ent.location_id != c_ctx.world.scene.location_id:
                        raise ToolError("существо вне сцены", code="nonlocal_effect_denied", category="rule_denial")

    def annotate_event(event: Event, call: CompiledCall) -> None:
        event.payload = {
            **event.payload,
            "narrative_source": proposal.source.model_dump(),
            "proposal_id": proposal.proposal_id,
        }

    group_res = await run_operation_group(
        ctx,
        calls,
        validate_step=validate_step,
        annotate_event=annotate_event,
    )

    if not group_res.ok:
        if isinstance(group_res.error, ToolError):
            if group_res.error.code == "combat_scope_locked":
                return AdaptationResult(
                    status="deferred",
                    reason_code="combat_scope_locked",
                    budgets_used={},
                )
            return AdaptationResult(
                status="denied",
                reason_code=group_res.error.code or "execution_failed",
                budgets_used={},
            )
        if group_res.raw_error:
            return AdaptationResult(
                status="denied",
                reason_code="execution_failed",
                budgets_used={},
            )
        return AdaptationResult(
            status="failed",
            reason_code="internal_error",
            budgets_used={},
        )

    # 6. Update state revision and novelty budget counters
    state = await ensure_state(ctx.session, ctx.campaign.id)
    state.revision += 1
    counters = dict(state.budget_counters or {})
    counters["novelty_scene"] = counters.get("novelty_scene", 0) + admission.novelty_cost
    counters["novelty_session"] = counters.get("novelty_session", 0) + admission.novelty_cost
    state.budget_counters = counters
    await ctx.session.flush()

    # Determine created IDs from bindings and operations
    created_ids: list[str] = list(group_res.bindings.values())
    for op_item in proposal.operations:
        if op_item.kind == "upsert_thread" and op_item.thread.id not in created_ids:
            created_ids.append(op_item.thread.id)

    # Snapshot updated facts if any
    changed_facts: list[FactState] = []
    for op_item in proposal.operations:
        if op_item.kind in ("add_campaign_fact", "revise_draft_fact", "reveal_fact"):
            f_state = getattr(op_item, "fact", None)
            if f_state:
                changed_facts.append(f_state)

    if changed_facts:
        await write_fact_snapshots(ctx, tuple(changed_facts))

    plot_ver = ctx.world.plot.get("version", 1) if isinstance(ctx.world.plot, dict) else 1
    new_versions = VersionSet(
        world_revision=ctx.world.revision,
        plan_version=plot_ver,
        narrative_revision=state.revision,
        policy_version=policy.version,
        operation_schema_version=1,
    )

    result = AdaptationResult(
        status="applied",
        reason_code="ok",
        event_ids=tuple(dict.fromkeys(group_res.event_ids)),
        created_ids=tuple(dict.fromkeys(created_ids)),
        versions=new_versions,
        budgets_used={
            "novelty": admission.novelty_cost,
            "operations": len(proposal.operations),
        },
    )

    # 7. Record durable receipt
    key = narrative_key(proposal.source)
    orig_call_key, orig_first_event = ctx.call_key, ctx._first_event
    ctx.call_key, ctx._first_event = key, None
    receipt_ev = await ctx.record(
        "adapt_story",
        hidden=True,
        payload={
            "schema_version": 1,
            "fingerprint": hashlib.sha256(proposal.model_dump_json().encode("utf-8")).hexdigest(),
            "source": proposal.source.model_dump(),
            "proposal_id": proposal.proposal_id,
            "adaptation": result.model_dump(),
        },
    )
    ctx.call_key, ctx._first_event = orig_call_key, orig_first_event

    all_event_ids = tuple(dict.fromkeys(list(result.event_ids) + [receipt_ev.id]))
    result = result.model_copy(update={"event_ids": all_event_ids})
    receipt_ev.payload["adaptation"] = result.model_dump()

    return result


class ContextNarrativeApplier:
    """NarrativeApplier port adapter operating within an active ToolContext."""

    def __init__(self, ctx: ToolContext, *, policy: NarrativePolicy) -> None:
        self._ctx = ctx
        self._policy = policy

    async def apply(self, proposal: AdaptationProposal) -> AdaptationResult:
        return await apply_in_context(self._ctx, proposal, policy=self._policy)


class DbNarrativeApplier:
    """NarrativeApplier port adapter operating with a database sessionmaker."""

    def __init__(
        self,
        maker: async_sessionmaker,
        *,
        policy_provider: Callable[[], NarrativePolicy],
    ) -> None:
        self._maker = maker
        self._policy_provider = policy_provider

    async def apply(self, proposal: AdaptationProposal) -> AdaptationResult:
        async with self._maker() as session:
            campaign = await session.get(Campaign, proposal.source.campaign_id)
            if campaign is None:
                return AdaptationResult(status="failed", reason_code="campaign_not_found")
            ctx = await open_context(session, campaign, Dice(), turn_id=None, seat_id=None)
            res = await apply_in_context(ctx, proposal, policy=self._policy_provider())
            await session.commit()
            return res
