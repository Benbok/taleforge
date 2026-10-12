"""Registered execution tools for narrative adaptation operations."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.narrative.contracts import FutureSituationPatch
from app.core.narrative.plan_patch import patch_future_plan
from app.db.models import NarrativeFact, NarrativeThread
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


@tool("apply_narrative_fact", "Persist narrative fact adaptation", ApplyNarrativeFactArgs)
async def apply_narrative_fact(ctx: ToolContext, args: ApplyNarrativeFactArgs) -> dict[str, Any]:
    stmt = select(NarrativeFact).where(
        NarrativeFact.campaign_id == args.campaign_id,
        NarrativeFact.namespace == args.namespace,
        NarrativeFact.subject_id == args.subject_id,
        NarrativeFact.key == args.key,
    )
    res = await ctx.session.execute(stmt)
    existing = res.scalar_one_or_none()

    if existing is None:
        f = NarrativeFact(
            campaign_id=args.campaign_id,
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
    else:
        existing.value = args.value
        existing.version += 1
        existing.freedom = args.freedom
        existing.audience = args.audience
        existing.depends_on = args.depends_on
        if ctx.call_key and ctx.call_key not in (existing.source_refs or []):
            existing.source_refs = [*existing.source_refs, ctx.call_key]

    ev = await ctx.record(
        "apply_narrative_fact",
        hidden=True,
        payload={
            "campaign_id": args.campaign_id,
            "namespace": args.namespace,
            "subject_id": args.subject_id,
            "key": args.key,
            "value": args.value,
        },
    )
    return {"ok": True, "fact_address": f"{args.namespace}:{args.subject_id}:{args.key}", "event_id": ev.id}


class ApplyNarrativeThreadArgs(BaseModel):
    campaign_id: str
    thread: dict[str, Any] | None = None
    thread_id: str | None = None
    target_status: str | None = None


@tool("apply_narrative_thread", "Persist narrative thread changes", ApplyNarrativeThreadArgs)
async def apply_narrative_thread(ctx: ToolContext, args: ApplyNarrativeThreadArgs) -> dict[str, Any]:
    tid = (args.thread or {}).get("id") or args.thread_id
    if not tid:
        raise ToolError("missing thread identifier", code="invalid_args")

    stmt = select(NarrativeThread).where(
        NarrativeThread.campaign_id == args.campaign_id,
        NarrativeThread.thread_id == tid,
    )
    res = await ctx.session.execute(stmt)
    existing = res.scalar_one_or_none()

    if args.thread is not None:
        th_data = args.thread
        if existing is None:
            new_th = NarrativeThread(
                campaign_id=args.campaign_id,
                thread_id=tid,
                version=th_data.get("version", 1),
                status=th_data.get("status", "offered"),
                audience=th_data.get("audience", []),
                subject_refs=th_data.get("subject_refs", []),
                plan_refs=th_data.get("plan_refs", []),
                parent_id=th_data.get("parent_id"),
                source_refs=th_data.get("source_refs", [ctx.call_key] if ctx.call_key else []),
            )
            ctx.session.add(new_th)
        else:
            existing.version += 1
            existing.status = th_data.get("status", existing.status)
            existing.audience = th_data.get("audience", existing.audience)
            existing.subject_refs = th_data.get("subject_refs", existing.subject_refs)
            existing.plan_refs = th_data.get("plan_refs", existing.plan_refs)
            if ctx.call_key and ctx.call_key not in (existing.source_refs or []):
                existing.source_refs = [*existing.source_refs, ctx.call_key]
    elif args.target_status:
        if existing is None:
            raise ToolError(f"thread not found: {tid}", code="thread_not_found")
        existing.status = args.target_status
        existing.version += 1
        if ctx.call_key and ctx.call_key not in (existing.source_refs or []):
            existing.source_refs = [*existing.source_refs, ctx.call_key]

    ev = await ctx.record(
        "apply_narrative_thread",
        hidden=True,
        payload={
            "campaign_id": args.campaign_id,
            "thread_id": tid,
            "status": (args.thread or {}).get("status") or args.target_status,
        },
    )
    return {"ok": True, "thread_id": tid, "event_id": ev.id}


class ApplyFutureSituationArgs(BaseModel):
    campaign_id: str
    patch: dict[str, Any]


@tool("apply_future_situation", "Apply patch to open future campaign situations", ApplyFutureSituationArgs)
async def apply_future_situation(ctx: ToolContext, args: ApplyFutureSituationArgs) -> dict[str, Any]:
    patch_obj = FutureSituationPatch.model_validate(args.patch)
    plan = dict(ctx.campaign.settings.get("plan") or {})
    facts = await load_subject_facts(ctx.session, args.campaign_id, subject_ids=(), limit=100)
    res = patch_future_plan(plan, patch_obj, facts)
    if res.violations:
        raise ToolError(f"plan patch failed: {res.violations[0]}", code="plan_patch_violation")

    ctx.campaign.settings = {**ctx.campaign.settings, "plan": res.plan}
    ctx.changed.add("plan")

    ev = await ctx.record(
        "apply_future_situation",
        hidden=True,
        payload={
            "campaign_id": args.campaign_id,
            "changed_refs": list(res.changed_refs),
        },
    )
    return {"ok": True, "changed_refs": list(res.changed_refs), "event_id": ev.id}


class ApplyFrontIntentArgs(BaseModel):
    campaign_id: str
    front_ref: dict[str, Any]
    new_intent: str
    status: str | None = None


@tool("apply_existing_front_intent", "Update antagonist front intent", ApplyFrontIntentArgs)
async def apply_existing_front_intent(ctx: ToolContext, args: ApplyFrontIntentArgs) -> dict[str, Any]:
    plan = dict(ctx.campaign.settings.get("plan") or {})
    antagonists = list(plan.get("antagonists") or [])
    src_id = args.front_ref.get("source_id")
    found = False
    for ant in antagonists:
        if isinstance(ant, dict) and ant.get("id") == src_id:
            ant["goal"] = args.new_intent
            if args.status:
                ant["status"] = args.status
            found = True
            break
    if found:
        plan["antagonists"] = antagonists
        ctx.campaign.settings = {**ctx.campaign.settings, "plan": plan}
        ctx.changed.add("plan")

    ev = await ctx.record(
        "apply_existing_front_intent",
        hidden=True,
        payload={
            "campaign_id": args.campaign_id,
            "front_id": src_id,
            "new_intent": args.new_intent,
        },
    )
    return {"ok": True, "front_id": src_id, "new_intent": args.new_intent, "event_id": ev.id}
