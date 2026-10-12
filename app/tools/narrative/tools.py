"""Registered execution tools for narrative adaptation operations."""

from __future__ import annotations

import copy
from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.narrative.contracts import FutureSituationPatch
from app.core.narrative.plan_patch import patch_future_plan
from app.db.models import CampaignSecret, Message, NarrativeFact, NarrativeThread
from app.db.narrative import load_subject_facts
from app.tools.registry import ToolContext, ToolError, tool


class ApplyNarrativeFactArgs(BaseModel):
    campaign_id: str
    namespace: str
    subject_id: str
    key: str
    value: str
    kind: str = "truth"
    temporal_semantics: str = "current_state"
    freedom: str = "draft"
    audience: list[str] = Field(default_factory=list)
    depends_on: list[dict[str, Any]] = Field(default_factory=list)
    snapshot_ref: dict[str, Any] = Field(default_factory=dict)


@tool("apply_narrative_fact", "Persist narrative fact adaptation", ApplyNarrativeFactArgs, internal=True)
async def apply_narrative_fact(ctx: ToolContext, args: ApplyNarrativeFactArgs) -> dict[str, Any]:
    if args.campaign_id != ctx.campaign.id:
        raise ToolError(
            "граница кампании нарушена",
            code="campaign_boundary_violation",
            category="rule_denial",
        )
    for dep in args.depends_on:
        if isinstance(dep, dict) and dep.get("campaign_id") and dep["campaign_id"] != ctx.campaign.id:
            raise ToolError(
                "граница кампании нарушена в зависимости факта",
                code="campaign_boundary_violation",
                category="rule_denial",
            )
    if (
        isinstance(args.snapshot_ref, dict)
        and args.snapshot_ref.get("campaign_id")
        and args.snapshot_ref["campaign_id"] != ctx.campaign.id
    ):
        raise ToolError(
            "граница кампании нарушена в snapshot_ref факта",
            code="campaign_boundary_violation",
            category="rule_denial",
        )

    stmt = select(NarrativeFact).where(
        NarrativeFact.campaign_id == ctx.campaign.id,
        NarrativeFact.namespace == args.namespace,
        NarrativeFact.subject_id == args.subject_id,
        NarrativeFact.key == args.key,
    )
    res = await ctx.session.execute(stmt)
    existing = res.scalar_one_or_none()

    before_value = None
    prev_version = None
    inverse_payload = None

    if existing is None:
        f = NarrativeFact(
            campaign_id=ctx.campaign.id,
            namespace=args.namespace,
            subject_id=args.subject_id,
            key=args.key,
            version=1,
            kind=args.kind,
            temporal_semantics=args.temporal_semantics,
            freedom=args.freedom,
            value=args.value,
            audience=args.audience,
            depends_on=args.depends_on,
            source_refs=[ctx.call_key] if ctx.call_key else [],
            snapshot_ref=args.snapshot_ref,
        )
        ctx.session.add(f)
        current_version = 1
    else:
        if existing.freedom == "committed" and existing.temporal_semantics == "historical":
            raise ToolError(
                "нельзя изменить исторический закреплённый факт",
                code="historical_fact_immutable",
                category="rule_denial",
            )
        if existing.freedom == "committed" and args.freedom == "draft":
            raise ToolError(
                "нельзя понизить статус закреплённого факта в черновик",
                code="cannot_demote_committed_fact",
                category="rule_denial",
            )
        if existing.temporal_semantics != args.temporal_semantics or existing.kind != args.kind:
            raise ToolError(
                "нельзя изменять семантику существующего факта",
                code="cannot_change_fact_semantics",
                category="rule_denial",
            )

        before_value = existing.value
        prev_version = existing.version
        inverse_payload = {
            "value": existing.value,
            "version": existing.version,
            "freedom": existing.freedom,
            "audience": copy.deepcopy(existing.audience),
        }

        existing.value = args.value
        existing.version += 1
        existing.freedom = args.freedom
        existing.audience = args.audience
        existing.depends_on = args.depends_on
        if ctx.call_key and ctx.call_key not in (existing.source_refs or []):
            existing.source_refs = [*existing.source_refs, ctx.call_key]
        current_version = existing.version

    ev = await ctx.record(
        "apply_narrative_fact",
        hidden=True,
        payload={
            "campaign_id": ctx.campaign.id,
            "namespace": args.namespace,
            "subject_id": args.subject_id,
            "key": args.key,
            "value": args.value,
            "version": current_version,
            "before": before_value,
            "after": args.value,
            "previous_version": prev_version,
            "inverse": inverse_payload,
        },
    )
    return {"ok": True, "fact_address": f"{args.namespace}:{args.subject_id}:{args.key}", "event_id": ev.id}


class ApplyNarrativeThreadArgs(BaseModel):
    campaign_id: str
    thread: dict[str, Any] | None = None
    thread_id: str | None = None
    target_status: str | None = None


@tool("apply_narrative_thread", "Persist narrative thread changes", ApplyNarrativeThreadArgs, internal=True)
async def apply_narrative_thread(ctx: ToolContext, args: ApplyNarrativeThreadArgs) -> dict[str, Any]:
    if args.campaign_id != ctx.campaign.id:
        raise ToolError(
            "граница кампании нарушена",
            code="campaign_boundary_violation",
            category="rule_denial",
        )
    tid = (args.thread or {}).get("id") or args.thread_id
    if not tid:
        raise ToolError("missing thread identifier", code="invalid_args")

    stmt = select(NarrativeThread).where(
        NarrativeThread.campaign_id == ctx.campaign.id,
        NarrativeThread.thread_id == tid,
    )
    res = await ctx.session.execute(stmt)
    existing = res.scalar_one_or_none()

    from app.core.narrative.threads import _VALID_TRANSITIONS

    before_status = existing.status if existing is not None else None
    before_version = existing.version if existing is not None else None
    inverse_payload: dict[str, Any] = (
        {
            "status": existing.status,
            "version": existing.version,
            "audience": copy.deepcopy(existing.audience),
            "subject_refs": copy.deepcopy(existing.subject_refs),
            "plan_refs": copy.deepcopy(existing.plan_refs),
        }
        if existing is not None
        else {"delete": True, "thread_id": tid}
    )

    if args.thread is not None:
        th_data = args.thread
        new_status = th_data.get("status", "offered")
        if existing is None:
            if new_status != "offered":
                raise ToolError(
                    "новая нить должна создаваться со статусом offered",
                    code="player_choice_required",
                    category="rule_denial",
                )
            new_th = NarrativeThread(
                campaign_id=ctx.campaign.id,
                thread_id=tid,
                version=th_data.get("version", 1),
                status="offered",
                audience=th_data.get("audience", []),
                subject_refs=th_data.get("subject_refs", []),
                plan_refs=th_data.get("plan_refs", []),
                parent_id=th_data.get("parent_id"),
                source_refs=th_data.get("source_refs", [ctx.call_key] if ctx.call_key else []),
            )
            ctx.session.add(new_th)
            final_status = "offered"
            final_version = 1
        else:
            if existing.status == "resolved" and new_status != "resolved":
                raise ToolError(
                    "нить уже завершена и не может быть реактивирована",
                    code="resolved_terminal",
                    category="rule_denial",
                )
            if new_status != existing.status and (existing.status, new_status) not in _VALID_TRANSITIONS:
                raise ToolError(
                    f"недопустимый переход нити из {existing.status} в {new_status}",
                    code="invalid_transition",
                    category="rule_denial",
                )
            existing.version += 1
            existing.status = new_status
            existing.audience = th_data.get("audience", existing.audience)
            existing.subject_refs = th_data.get("subject_refs", existing.subject_refs)
            existing.plan_refs = th_data.get("plan_refs", existing.plan_refs)
            if ctx.call_key and ctx.call_key not in (existing.source_refs or []):
                existing.source_refs = [*existing.source_refs, ctx.call_key]
            final_status = existing.status
            final_version = existing.version
    elif args.target_status:
        if existing is None:
            raise ToolError(f"thread not found: {tid}", code="thread_not_found")
        if existing.status == "resolved" and args.target_status != "resolved":
            raise ToolError(
                "нить уже завершена и не может быть реактивирована",
                code="resolved_terminal",
                category="rule_denial",
            )
        if args.target_status != existing.status and (existing.status, args.target_status) not in _VALID_TRANSITIONS:
            raise ToolError(
                f"недопустимый переход нити из {existing.status} в {args.target_status}",
                code="invalid_transition",
                category="rule_denial",
            )
        existing.status = args.target_status
        existing.version += 1
        if ctx.call_key and ctx.call_key not in (existing.source_refs or []):
            existing.source_refs = [*existing.source_refs, ctx.call_key]
        final_status = existing.status
        final_version = existing.version
    else:
        final_status = existing.status if existing else "offered"
        final_version = existing.version if existing else 1

    ev = await ctx.record(
        "apply_narrative_thread",
        hidden=True,
        payload={
            "campaign_id": ctx.campaign.id,
            "thread_id": tid,
            "status": final_status,
            "before": before_status,
            "after": final_status,
            "version": final_version,
            "previous_version": before_version,
            "inverse": inverse_payload,
        },
    )
    return {"ok": True, "thread_id": tid, "event_id": ev.id}


class ApplyFutureSituationArgs(BaseModel):
    campaign_id: str
    patch: dict[str, Any]


@tool(
    "apply_future_situation",
    "Apply patch to open future campaign situations",
    ApplyFutureSituationArgs,
    internal=True,
)
async def apply_future_situation(ctx: ToolContext, args: ApplyFutureSituationArgs) -> dict[str, Any]:
    if args.campaign_id != ctx.campaign.id:
        raise ToolError(
            "граница кампании нарушена",
            code="campaign_boundary_violation",
            category="rule_denial",
        )
    patch_obj = FutureSituationPatch.model_validate(args.patch)
    secret = await ctx.session.get(CampaignSecret, ctx.campaign.id)
    plan = copy.deepcopy(secret.plot) if (secret and secret.plot) else dict(ctx.campaign.settings.get("plan") or {})
    facts = await load_subject_facts(ctx.session, ctx.campaign.id, subject_ids=(), limit=100)
    res = patch_future_plan(plan, patch_obj, facts)
    if res.violations:
        raise ToolError(f"plan patch failed: {res.violations[0]}", code="plan_patch_violation")

    if secret is not None:
        secret.plot = copy.deepcopy(res.plan)
    if hasattr(ctx.world, "plot"):
        ctx.world.plot = copy.deepcopy(res.plan)
    ctx.campaign.settings = {**ctx.campaign.settings, "plan": res.plan}
    ctx.changed.add("plan")

    ev = await ctx.record(
        "apply_future_situation",
        hidden=True,
        payload={
            "campaign_id": ctx.campaign.id,
            "changed_refs": list(res.changed_refs),
        },
    )
    return {"ok": True, "changed_refs": list(res.changed_refs), "event_id": ev.id}


class ApplyFrontIntentArgs(BaseModel):
    campaign_id: str
    front_ref: dict[str, Any]
    new_intent: str
    status: str | None = None


@tool("apply_existing_front_intent", "Update antagonist front intent", ApplyFrontIntentArgs, internal=True)
async def apply_existing_front_intent(ctx: ToolContext, args: ApplyFrontIntentArgs) -> dict[str, Any]:
    if args.campaign_id != ctx.campaign.id:
        raise ToolError(
            "граница кампании нарушена",
            code="campaign_boundary_violation",
            category="rule_denial",
        )
    if (
        isinstance(args.front_ref, dict)
        and args.front_ref.get("campaign_id")
        and args.front_ref["campaign_id"] != ctx.campaign.id
    ):
        raise ToolError(
            "граница кампании нарушена в front_ref",
            code="campaign_boundary_violation",
            category="rule_denial",
        )
    secret = await ctx.session.get(CampaignSecret, ctx.campaign.id)
    plan = copy.deepcopy(secret.plot) if (secret and secret.plot) else dict(ctx.campaign.settings.get("plan") or {})
    antagonists = list(plan.get("antagonists") or [])
    src_id = args.front_ref.get("source_id") or args.front_ref.get("id")
    found = False
    for ant in antagonists:
        if isinstance(ant, dict) and ant.get("id") == src_id:
            ant["goal"] = args.new_intent
            if args.status:
                ant["status"] = args.status
                if args.status == "stopped":
                    ant["stopped"] = True
            found = True
            break
    for fr in plan.get("fronts") or []:
        if isinstance(fr, dict) and fr.get("id") == src_id:
            fr["goal"] = args.new_intent
            if args.status:
                fr["status"] = args.status
            found = True
            break
    if found:
        plan["antagonists"] = antagonists
        if secret is not None:
            secret.plot = copy.deepcopy(plan)
        if hasattr(ctx.world, "plot"):
            ctx.world.plot = copy.deepcopy(plan)
        ctx.campaign.settings = {**ctx.campaign.settings, "plan": plan}
        ctx.changed.add("plan")

    ev = await ctx.record(
        "apply_existing_front_intent",
        hidden=True,
        payload={
            "campaign_id": ctx.campaign.id,
            "front_id": src_id,
            "new_intent": args.new_intent,
            "status": args.status,
        },
    )
    return {"ok": True, "front_id": src_id, "new_intent": args.new_intent, "event_id": ev.id}


class ApplyAdvanceFrontArgs(BaseModel):
    campaign_id: str
    front_ref: dict[str, Any]
    steps: int = 1
    ground_ref: str | None = None


@tool("apply_advance_front", "Advance antagonist or campaign front", ApplyAdvanceFrontArgs, internal=True)
async def apply_advance_front(ctx: ToolContext, args: ApplyAdvanceFrontArgs) -> dict[str, Any]:
    if args.campaign_id != ctx.campaign.id:
        raise ToolError(
            "граница кампании нарушена",
            code="campaign_boundary_violation",
            category="rule_denial",
        )
    if (
        isinstance(args.front_ref, dict)
        and args.front_ref.get("campaign_id")
        and args.front_ref["campaign_id"] != ctx.campaign.id
    ):
        raise ToolError(
            "граница кампании нарушена в front_ref",
            code="campaign_boundary_violation",
            category="rule_denial",
        )
    secret = await ctx.session.get(CampaignSecret, ctx.campaign.id)
    plan = copy.deepcopy(secret.plot) if (secret and secret.plot) else dict(ctx.campaign.settings.get("plan") or {})
    src_id = args.front_ref.get("source_id") or args.front_ref.get("id")
    found = False
    for ant in plan.get("antagonists") or []:
        if isinstance(ant, dict) and ant.get("id") == src_id:
            steps = ant.get("threat") or []
            cur = int(ant.get("threat_step") or 0)
            ant["threat_step"] = min(len(steps), cur + args.steps)
            found = True
            break
    for fr in plan.get("fronts") or []:
        if isinstance(fr, dict) and fr.get("id") == src_id:
            cur = int(fr.get("progress") or 0)
            max_v = int(fr.get("maximum") or 6)
            fr["progress"] = min(max_v, cur + args.steps)
            found = True
            break
    if found:
        if secret is not None:
            secret.plot = copy.deepcopy(plan)
        if hasattr(ctx.world, "plot"):
            ctx.world.plot = copy.deepcopy(plan)
        ctx.campaign.settings = {**ctx.campaign.settings, "plan": plan}
        ctx.changed.add("plan")

    ev = await ctx.record(
        "apply_advance_front",
        hidden=True,
        payload={
            "campaign_id": ctx.campaign.id,
            "front_id": src_id,
            "steps": args.steps,
        },
    )
    return {"ok": True, "front_id": src_id, "steps": args.steps, "event_id": ev.id}


class ApplyNarrativeActorSketchArgs(BaseModel):
    campaign_id: str
    actor_slot: str
    template_id: str
    place_ref: str
    attitude: str = "neutral"
    public_description: str


@tool(
    "apply_narrative_actor_sketch",
    "Persist narrative actor sketch without spawning in scene",
    ApplyNarrativeActorSketchArgs,
    internal=True,
)
async def apply_narrative_actor_sketch(ctx: ToolContext, args: ApplyNarrativeActorSketchArgs) -> dict[str, Any]:
    if args.campaign_id != ctx.campaign.id:
        raise ToolError(
            "граница кампании нарушена",
            code="campaign_boundary_violation",
            category="rule_denial",
        )
    plan = copy.deepcopy(
        ctx.world.plot if isinstance(ctx.world.plot, dict) else (ctx.campaign.settings or {}).get("plan") or {}
    )
    npcs = list(plan.get("npcs") or [])

    existing_idx = next((i for i, n in enumerate(npcs) if n.get("id") == args.actor_slot), None)
    sketch_entry = {
        "id": args.actor_slot,
        "name": args.public_description,
        "location_id": args.place_ref,
        "template_id": args.template_id,
        "attitude": args.attitude,
        "status": "sketch",
        "description": args.public_description,
    }
    if existing_idx is not None:
        npcs[existing_idx] = {**npcs[existing_idx], **sketch_entry}
    else:
        npcs.append(sketch_entry)

    plan["npcs"] = npcs
    if hasattr(ctx.world, "plot"):
        ctx.world.plot = plan
    ctx.campaign.settings = {**(ctx.campaign.settings or {}), "plan": plan}
    ctx.changed.add("plan")

    ev = await ctx.record(
        "apply_narrative_actor_sketch",
        hidden=True,
        payload={
            "campaign_id": ctx.campaign.id,
            "actor_slot": args.actor_slot,
            "template_id": args.template_id,
            "place_ref": args.place_ref,
            "attitude": args.attitude,
        },
    )
    return {"ok": True, "actor_slot": args.actor_slot, "status": "sketch", "event_id": ev.id}


class AdaptStoryArgs(BaseModel):
    slot_ref: int = Field(ge=0, le=2, description="Номер слота адаптации текущего хода (0, 1 или 2)")
    grounds: list[dict[str, Any]] = Field(default_factory=list, description="Основания адаптации")
    summary: str = Field(description="Краткое объяснение адаптации")
    operations: list[dict[str, Any]] = Field(default_factory=list, description="Типизированные операции")


CURRENT_MESSAGE = "current"  # source_id реплики игрока текущего хода: сервер подставит её настоящий id


@tool("adapt_story", "Apply narrative adaptation in scene", AdaptStoryArgs)
async def adapt_story(ctx: ToolContext, args: AdaptStoryArgs) -> dict[str, Any]:
    import secrets

    from pydantic import TypeAdapter

    from app.core.narrative.contracts import (
        AdaptationProposal,
        Ground,
        NarrativePolicy,
        Operation,
        VersionSet,
    )
    from app.db.narrative import ensure_state
    from app.tools.narrative.executor import apply_in_context
    from app.tools.narrative.sources import bind_scene_sources

    slots = await bind_scene_sources(ctx)
    if args.slot_ref < 0 or args.slot_ref >= len(slots):
        raise ToolError("неверный номер слота адаптации", code="invalid_slot")

    source = slots[args.slot_ref]
    state = await ensure_state(ctx.session, ctx.campaign.id)
    if state.mode != "adaptive":
        raise ToolError("адаптивный режим выключен", code="policy_strict_mode")

    policy = NarrativePolicy(mode="adaptive")
    op_adapter = TypeAdapter(Operation)

    try:
        # Normalize missing campaign_id in evidence_refs and resolve turn message if needed
        turn_msg = None
        if ctx.turn_id:
            turn_msg = await ctx.session.scalar(
                select(Message)
                .where(Message.campaign_id == ctx.campaign.id, Message.turn_id == ctx.turn_id)
                .order_by(Message.seq.desc())
            )

        normalized_grounds = []
        for g in args.grounds:
            g_dict = dict(g)
            ev_refs = []
            for ev in g_dict.get("evidence_refs", []):
                ev_dict = dict(ev)
                if not ev_dict.get("campaign_id"):
                    ev_dict["campaign_id"] = ctx.campaign.id
                # только явный маркер реплики этого хода; выдуманный id не подменяется и будет отклонён допуском
                if ev_dict.get("kind") == "message" and ev_dict.get("source_id") in (None, "", CURRENT_MESSAGE):
                    if turn_msg is None:
                        raise ToolError("в этом ходе нет реплики игрока для основания", code="evidence_not_found")
                    ev_dict["source_id"] = turn_msg.id
                ev_refs.append(ev_dict)
            g_dict["evidence_refs"] = ev_refs
            normalized_grounds.append(Ground.model_validate(g_dict))

        grounds = tuple(normalized_grounds)
        operations = tuple(op_adapter.validate_python(o) for o in args.operations)
    except Exception as e:
        raise ToolError(f"неверный формат аргументов адаптации: {e}", code="invalid_args") from e

    plot_ver = ctx.world.plot.get("version", 1) if isinstance(ctx.world.plot, dict) else 1
    base = VersionSet(
        world_revision=ctx.world.revision,
        plan_version=plot_ver,
        narrative_revision=state.revision,
        policy_version=policy.version,
        operation_schema_version=1,
    )
    proposal_id = f"prop_{secrets.token_hex(8)}"
    proposal = AdaptationProposal(
        schema_version=1,
        proposal_id=proposal_id,
        source=source,
        base=base,
        grounds=grounds,
        summary=args.summary,
        operations=operations,
    )

    result = await apply_in_context(ctx, proposal, policy=policy)
    if result.status in ("denied", "failed", "stale", "deferred"):
        raise ToolError(f"адаптация не принята: {result.reason_code}", code=result.reason_code)

    return {
        "ok": True,
        "status": result.status,
        "reason_code": result.reason_code,
        "event_ids": list(result.event_ids),
        "created_ids": list(result.created_ids),
        "budgets_used": result.budgets_used,
    }
