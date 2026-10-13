"""Bounded narrative snapshot builder."""

from __future__ import annotations

import secrets
from typing import Any

from sqlalchemy import select

from app.core.modules import parse_narrative_permissions
from app.core.narrative.contracts import (
    EvidenceRecord,
    FrontRef,
    FrontView,
    NarrativePermissions,
    NarrativePolicy,
    NarrativeSnapshot,
    ReadRef,
    SituationView,
    SnapshotRequest,
    ThreadState,
    VersionSet,
)
from app.core.narrative.operations import ACTIVE_OPERATION_KINDS
from app.core.narrative.plan_patch import CLOSED_STATUSES
from app.db.models import Event, Message, NarrativeThread
from app.db.narrative import ensure_state, load_subject_facts
from app.tools.narrative.evidence import action_message_id, verified_player_action
from app.tools.registry import ToolContext


async def load_snapshot(
    ctx: ToolContext,
    request: SnapshotRequest,
    *,
    policy: NarrativePolicy,
) -> NarrativeSnapshot:
    """Build a verified bounded narrative snapshot from tool context."""
    cid = ctx.campaign.id
    proposal_id = f"prop_{secrets.token_hex(8)}"

    st = await ensure_state(ctx.session, cid)
    plot_data = ctx.world.plot or {}
    plan_ver = plot_data.get("version", 1) if isinstance(plot_data, dict) else 1

    base = VersionSet(
        world_revision=ctx.world.revision,
        plan_version=plan_ver,
        narrative_revision=st.revision,
        policy_version=policy.version,
        operation_schema_version=1,
    )

    # 1. Evidence. Resolve durable rows in two bounded queries. The old loop
    # issued one query per reference and made a large history scale with the
    # number of supplied grounds.
    evidence_records: list[EvidenceRecord] = []
    evidence_refs = tuple(ref for ref in request.evidence_refs if ref.campaign_id == cid)[: policy.max_snapshot_grounds]
    if evidence_refs:
        scene_state = ctx.world.scene.state if isinstance(ctx.world.scene.state, dict) else {}
        event_ids = tuple(ref.source_id for ref in evidence_refs if ref.kind == "event")
        message_ids = tuple(ref.source_id for ref in evidence_refs if ref.kind == "message")
        event_rows = {}
        message_rows = {}
        if event_ids:
            event_rows = {
                row.id: row
                for row in (
                    await ctx.session.scalars(select(Event).where(Event.campaign_id == cid, Event.id.in_(event_ids)))
                ).all()
            }
        # At most one extra source message per cited event; still one batched query.
        message_ids = tuple(
            dict.fromkeys((*message_ids, *(mid for row in event_rows.values() if (mid := action_message_id(row)))))
        )
        if message_ids:
            message_rows = {
                row.id: row
                for row in (
                    await ctx.session.scalars(
                        select(Message).where(Message.campaign_id == cid, Message.id.in_(message_ids))
                    )
                ).all()
            }

        for ev_ref in evidence_refs:
            if ev_ref.kind == "event":
                ev_row = event_rows.get(ev_ref.source_id)
                if not ev_row:
                    continue
                if ev_row.tool in ("adapt_story", "narrative_fact_snapshot") or (
                    ev_row.tool and ev_row.tool.startswith("apply_narrative_")
                ):
                    continue

                if ev_row.hidden:
                    payload = ev_row.payload if isinstance(ev_row.payload, dict) else {}
                    aud = payload.get("audience")
                    if isinstance(aud, (list, tuple)):
                        audience = tuple(aud)
                    elif isinstance(aud, str):
                        audience = (aud,)
                    elif ev_row.actor_id:
                        audience = (ev_row.actor_id,)
                    else:
                        audience = ()
                else:
                    audience = ("party",)

                player_source, player_targets = verified_player_action(ctx, ev_row, message_rows)
                evidence_records.append(
                    EvidenceRecord(
                        ref=ev_ref,
                        status="applied",
                        subject_refs=(ev_row.actor_id,) if ev_row.actor_id else (),
                        audience=audience,
                        game_time=ev_row.game_time,
                        applied_result=ev_row.tool,
                        player_action_source=player_source,
                        player_action_targets=player_targets,
                    )
                )

            elif ev_ref.kind == "message":
                msg = message_rows.get(ev_ref.source_id)
                if not msg:
                    continue

                if msg.visible_to is not None:
                    audience = tuple(msg.visible_to)
                else:
                    audience = ("party",)

                content_str = (msg.content or "").strip()
                intent_dict = msg.intent if isinstance(msg.intent, dict) else {}
                if content_str.endswith("?") or intent_dict.get("kind") == "question_to_master":
                    status = "question"
                else:
                    status = "stated"

                subject_refs = (msg.author_user_id,) if msg.author_user_id else ()
                evidence_records.append(
                    EvidenceRecord(
                        ref=ev_ref,
                        status=status,
                        subject_refs=subject_refs,
                        audience=audience,
                        game_time=0,
                        utterance_text=msg.content,
                    )
                )

            elif ev_ref.kind == "standing_response":
                standing = scene_state.get("standing") if isinstance(scene_state, dict) else {}
                responses = standing.get("responses", []) if isinstance(standing, dict) else []
                matched_resp = None
                for r in responses:
                    if isinstance(r, dict) and r.get("id") == ev_ref.source_id:
                        matched_resp = r
                        break

                if matched_resp and matched_resp.get("state") == "ready":
                    participants = matched_resp.get("participants") or matched_resp.get("actor_ids") or ()
                    if isinstance(participants, (list, tuple)):
                        sub_refs = tuple(participants)
                    elif isinstance(participants, str):
                        sub_refs = (participants,)
                    else:
                        sub_refs = ()

                    aud = matched_resp.get("audience")
                    if isinstance(aud, (list, tuple)):
                        audience = tuple(aud)
                    elif isinstance(aud, str):
                        audience = (aud,)
                    else:
                        audience = ("party",)

                    evidence_records.append(
                        EvidenceRecord(
                            ref=ev_ref,
                            status="applied",
                            subject_refs=sub_refs,
                            audience=audience,
                        )
                    )

            elif ev_ref.kind == "time_interval":
                found_interval = False
                antagonists = plot_data.get("antagonists", []) if isinstance(plot_data, dict) else []
                fronts = plot_data.get("fronts", []) if isinstance(plot_data, dict) else []
                timers = plot_data.get("timers", {}) if isinstance(plot_data, dict) else {}
                scene_timers = scene_state.get("timers", {}) if isinstance(scene_state, dict) else {}

                for ant in antagonists:
                    if isinstance(ant, dict) and ant.get("id") == ev_ref.source_id:
                        found_interval = True
                        break
                if not found_interval:
                    for fr in fronts:
                        if isinstance(fr, dict) and fr.get("id") == ev_ref.source_id:
                            found_interval = True
                            break
                if not found_interval:
                    if ev_ref.source_id in timers or ev_ref.source_id in scene_timers:
                        found_interval = True

                if found_interval:
                    evidence_records.append(
                        EvidenceRecord(
                            ref=ev_ref,
                            status="elapsed",
                            audience=("party",),
                        )
                    )

    # 2. Facts
    subject_ids: list[str] = []
    subject_seen: set[str] = set()

    def add_subject(subject_id: str) -> None:
        if subject_id and subject_id not in subject_seen:
            subject_seen.add(subject_id)
            subject_ids.append(subject_id)

    for subject_id in request.mutable_subject_refs:
        add_subject(subject_id)
    for ent_id, ent in ctx.world.entities.items():
        add_subject(ent_id)
        slot = (ent.state or {}).get("actor_slot")
        if slot:
            add_subject(slot)
    for ch_id in ctx.world.characters:
        add_subject(ch_id)
    counters = st.budget_counters or {}
    for slot in counters.get("spent_actor_slots", []):
        add_subject(slot)

    max_records = max(0, policy.max_snapshot_records)
    actor_candidates = tuple(subject_ids)
    actor_limit = min(len(actor_candidates), max_records // 4)
    actors = actor_candidates[:actor_limit]

    fact_subject_ids = tuple(subject_ids[:max_records])
    fact_limit = max(0, max_records - len(actors))
    facts = await load_subject_facts(ctx.session, cid, fact_subject_ids, limit=fact_limit)

    # 3. Actors. A single shared record budget covers facts, actors, and fronts.
    # Keeping a deterministic actor slice preserves useful request references
    # while preventing large world registries from entering every prompt.

    # 4. Fronts
    front_candidates: list[FrontView] = []
    front_ids: set[str] = set()
    antagonists = plot_data.get("antagonists", []) if isinstance(plot_data, dict) else []
    explicit_fronts = plot_data.get("fronts", []) if isinstance(plot_data, dict) else []
    for source_kind, candidates in (("antagonist", antagonists), ("front", explicit_fronts)):
        for ant in candidates:
            if not isinstance(ant, dict) or "id" not in ant or ant["id"] in front_ids:
                continue
            front_ids.add(ant["id"])
            f_ref = FrontRef(campaign_id=cid, source_kind=source_kind, source_id=ant["id"])
            front_candidates.append(
                FrontView(
                    ref=f_ref,
                    owner_ref=ant["id"],
                    goal=ant.get("goal") or ant.get("name") or "",
                    progress=int(ant.get("progress") or ant.get("threat_step") or 0),
                    maximum=int(ant.get("maximum") or len(ant.get("threat") or ()) or 6),
                    status=(
                        "stopped"
                        if ant.get("stopped")
                        else str(ant.get("status") or "active")
                        if str(ant.get("status") or "active") in {"active", "paused", "completed"}
                        else "active"
                    ),
                    clock_at=int(ant.get("clock_at") or 0),
                    period=int(ant.get("period") or 86400),
                    milestones=tuple(str(step) for step in (ant.get("threat") or ant.get("milestones") or ())),
                )
            )

    front_limit = min(len(front_candidates), max(0, max_records - len(actors) - len(facts)))
    fronts_list = front_candidates[:front_limit]

    # 5. Threads
    stmt = (
        select(NarrativeThread)
        .where(NarrativeThread.campaign_id == cid)
        .order_by(NarrativeThread.last_developed_at.desc())
        .limit(policy.max_snapshot_threads)
    )
    th_res = await ctx.session.execute(stmt)
    th_rows = th_res.scalars().all()
    threads_list = tuple(
        ThreadState(
            id=r.thread_id,
            version=r.version,
            status=r.status,  # type: ignore[arg-type]
            audience=tuple(r.audience or ()),
            subject_refs=tuple(r.subject_refs or ()),
            plan_refs=tuple(r.plan_refs or ()),
            parent_id=r.parent_id,
            source_refs=tuple(r.source_refs or ()),
        )
        for r in th_rows
    )

    # 6. ReadSet
    read_set: list[ReadRef] = []
    for a in actors:
        read_set.append(ReadRef(kind="entity", id=a))
    for f in facts:
        read_set.append(
            ReadRef(kind="fact", id=f"{f.ref.namespace}:{f.ref.subject_id}:{f.ref.key}", version=f.ref.version)
        )
    for fr in fronts_list:
        read_set.append(ReadRef(kind="front", id=fr.ref.source_id))
    for th in threads_list:
        read_set.append(ReadRef(kind="thread", id=th.id, version=th.version))

    # 7. Budgets
    counters = st.budget_counters or {}
    scene_ref = getattr(ctx.world.scene, "boundary_id", None) or f"scene:{ctx.world.scene.location_id or 'default'}"
    session_ref = ctx.game_session_id or f"session:{ctx.campaign.id}:default"

    scene_spent_map = counters.get("scene_spent") or {}
    session_spent_map = counters.get("session_spent") or {}

    if scene_ref in scene_spent_map:
        used_scene = scene_spent_map[scene_ref]
    elif not scene_spent_map and "novelty_scene" in counters:
        used_scene = counters.get("novelty_scene", 0)
    else:
        used_scene = 0

    if session_ref in session_spent_map:
        used_session = session_spent_map[session_ref]
    elif not session_spent_map and "novelty_session" in counters:
        used_session = counters.get("novelty_session", 0)
    else:
        used_session = 0

    budgets = {
        "novelty_scene": max(0, policy.max_novelty_scene - used_scene),
        "novelty_session": max(0, policy.max_novelty_session - used_session),
        "operations": policy.max_operations,
        "combat_active": 1 if (ctx.world.scene.mode == "combat" or ctx.world.in_fight()) else 0,
    }

    # 8. Permissions
    mod_perms = None
    adventure_rec = None
    if hasattr(ctx.world, "catalog") and hasattr(ctx.world.catalog, "all"):
        try:
            advs = ctx.world.catalog.all("adventure")
            if advs:
                adventure_rec = advs[0].data
        except Exception:
            pass

    if adventure_rec is None and isinstance(ctx.campaign.settings, dict):
        if "narrative_permissions" in ctx.campaign.settings:
            adventure_rec = ctx.campaign.settings
        elif "adventure" in ctx.campaign.settings and isinstance(ctx.campaign.settings["adventure"], dict):
            adventure_rec = ctx.campaign.settings["adventure"]

    if adventure_rec is None and isinstance(plot_data, dict) and "narrative_permissions" in plot_data:
        adventure_rec = plot_data

    raw_np = None
    if adventure_rec:
        raw_np = adventure_rec.get("narrative_permissions")
        if raw_np is None:
            raw_np = adventure_rec.get("permissions")
        if raw_np is not None and isinstance(raw_np, dict):
            try:
                mod_perms = parse_narrative_permissions(adventure_rec)
            except Exception:
                mod_perms = None

    if mod_perms is not None:
        anchors = mod_perms.anchors
        mutable_fact_addresses = mod_perms.mutable_fact_addresses
        if raw_np and "operation_kinds" in raw_np:
            op_kinds = tuple(
                sorted(
                    set(ACTIVE_OPERATION_KINDS) & set(policy.allowed_operation_kinds) & set(mod_perms.operation_kinds)
                )
            )
        else:
            op_kinds = tuple(sorted(set(ACTIVE_OPERATION_KINDS) & set(policy.allowed_operation_kinds)))

        if raw_np and "supplement_scopes" in raw_np:
            sup_scopes = tuple(sorted(set(policy.allowed_scopes) & set(mod_perms.supplement_scopes)))
        else:
            sup_scopes = tuple(policy.allowed_scopes)
    else:
        anchors = ()
        mutable_fact_addresses = ()
        op_kinds = tuple(sorted(set(ACTIVE_OPERATION_KINDS) & set(policy.allowed_operation_kinds)))
        sup_scopes = tuple(policy.allowed_scopes)

    permissions = NarrativePermissions(
        anchors=anchors,
        mutable_fact_addresses=mutable_fact_addresses,
        operation_kinds=op_kinds,
        supplement_scopes=sup_scopes,
    )

    content_chain = ()
    if hasattr(ctx.world.catalog, "chain"):
        content_chain = tuple(ctx.world.catalog.chain)

    situations = open_situations(plot_data, limit=policy.max_snapshot_threads)

    return NarrativeSnapshot(
        source=request.source,
        proposal_id=proposal_id,
        base=base,
        evidence=tuple(evidence_records),
        facts=facts,
        actors=actors,
        fronts=tuple(fronts_list),
        threads=threads_list,
        situations=situations,
        read_set=tuple(read_set),
        permissions=permissions,
        budgets=budgets,
        content_chain=content_chain,
        feedback=request.feedback,
        author_attempt=0,
    )


def open_situations(plot_data: Any, *, limit: int) -> tuple[SituationView, ...]:
    """Открытые узлы незакрытых актов — то, что режиссёр вправе пересматривать (plan_patch).

    Текущий акт идёт первым: его ближайшие ситуации важнее дальних; объём ограничен."""
    if not isinstance(plot_data, dict):
        return ()
    out: list[SituationView] = []
    for act in plot_data.get("acts") or []:
        if not isinstance(act, dict) or act.get("status") in ("done", "closed", "retired") or not act.get("id"):
            continue
        for node in act.get("nodes") or []:
            if not isinstance(node, dict) or not node.get("id"):
                continue
            if node.get("status") in CLOSED_STATUSES or node.get("outcome") is not None:
                continue
            out.append(
                SituationView(
                    act_id=str(act["id"]),
                    act_title=str(act.get("title") or ""),
                    act_status=str(act.get("status") or ""),
                    node_id=str(node["id"]),
                    title=str(node.get("title") or ""),
                    summary=str(node.get("summary") or "")[:300],
                )
            )
            if len(out) >= limit:
                return tuple(out)
    return tuple(out)
