"""Fronts, clock thresholds, and dramatic campaign pacing (Task 19)."""

from __future__ import annotations

import copy
from typing import Any

from app.core.narrative.contracts import (
    FrontRef,
    FrontTickResult,
    FrontTransition,
    FrontView,
    Ground,
    ReadyIntent,
)
from app.core.plot import DAY, THREAT_DAYS


def iter_fronts(plan: dict[str, Any]) -> tuple[FrontView, ...]:
    """Extract consistent FrontViews from antagonists and explicit fronts in campaign plan."""
    if not isinstance(plan, dict):
        return ()

    views: list[FrontView] = []
    seen_ids: set[str] = set()
    cid = str(plan.get("campaign_id") or "")
    global_clock = int(plan.get("clock_at") or 0)

    # 1. Adapt antagonists
    for a in plan.get("antagonists") or []:
        if not isinstance(a, dict) or not a.get("id"):
            continue
        aid = str(a["id"])
        steps = tuple(str(s) for s in (a.get("threat") or ()))
        step_idx = int(a.get("threat_step") or 0)
        is_stopped = bool(a.get("stopped"))
        status = "stopped" if is_stopped else ("completed" if step_idx >= len(steps) and len(steps) > 0 else "active")
        views.append(
            FrontView(
                ref=FrontRef(campaign_id=cid, source_kind="antagonist", source_id=aid),
                owner_ref=aid,
                goal=str(a.get("goal") or ""),
                resource_refs=tuple(str(r) for r in (a.get("resources") or ())),
                progress=step_idx,
                maximum=len(steps) or 6,
                status=status,
                known_fact_refs=(),
                clock_at=global_clock,
                period=86400 * int(THREAT_DAYS.get(plan.get("length", "short"), 3)),
                milestones=steps,
            )
        )
        seen_ids.add(aid)

    # 2. Adapt explicit fronts
    for f in plan.get("fronts") or []:
        if not isinstance(f, dict) or not f.get("id"):
            continue
        fid = str(f["id"])
        if fid in seen_ids:
            continue
        milestones = tuple(str(m) for m in (f.get("milestones") or ()))
        prog = int(f.get("progress") or 0)
        max_val = int(f.get("maximum") or 6)
        status = str(f.get("status") or ("completed" if prog >= max_val else "active"))
        views.append(
            FrontView(
                ref=FrontRef(campaign_id=cid, source_kind="front", source_id=fid),
                owner_ref=str(f.get("owner_ref") or fid),
                goal=str(f.get("goal") or ""),
                resource_refs=tuple(str(r) for r in (f.get("resource_refs") or ())),
                progress=prog,
                maximum=max_val,
                status=status,
                known_fact_refs=(),
                clock_at=int(f.get("clock_at") or global_clock),
                period=int(f.get("period") or 86400),
                milestones=milestones,
            )
        )
        seen_ids.add(fid)

    return tuple(views)


def tick_fronts(
    plan: dict[str, Any],
    game_time: int,
    *,
    length: str = "short",
    mode: str = "strict",
) -> FrontTickResult:
    """Advance campaign fronts and antagonist threat clocks according to game time intervals."""
    if not isinstance(plan, dict):
        return FrontTickResult(next_plan={}, progress_events=(), ready_intents=())

    next_plan = copy.deepcopy(plan)
    game_time = int(game_time)
    days = THREAT_DAYS.get(length, 3)
    period_sec = days * DAY

    if "clock_at" not in next_plan:
        next_plan["clock_at"] = game_time
        return FrontTickResult(next_plan=next_plan, progress_events=(), ready_intents=())

    last_clock = int(next_plan.get("clock_at") or 0)
    elapsed = game_time - last_clock
    if elapsed < period_sec:
        return FrontTickResult(next_plan=next_plan, progress_events=(), ready_intents=())

    periods = max(0, elapsed // period_sec)
    next_plan["clock_at"] = last_clock + periods * period_sec

    events: list[dict[str, Any]] = []
    intents: list[ReadyIntent] = []
    cid = str(next_plan.get("campaign_id") or "")

    for a in next_plan.get("antagonists") or []:
        if a.get("stopped"):
            continue
        steps = a.get("threat") or []
        for _ in range(periods):
            step_idx = int(a.get("threat_step") or 0)
            if step_idx >= len(steps):
                break
            step_text = str(steps[step_idx])
            a["threat_step"] = step_idx + 1
            a.setdefault("threat_log", []).append({
                "step": step_text,
                "reason": f"прошло {days} дн. игрового времени",
            })
            events.append({"antagonist_id": a["id"], "step": step_text})

            if mode == "adaptive":
                # Intent threshold check
                if a["threat_step"] >= 2 or a["threat_step"] >= len(steps) - 1:
                    intent = ReadyIntent(
                        id=f"intent:{a['id']}:{a['threat_step']}",
                        front_ref=FrontRef(campaign_id=cid, source_kind="antagonist", source_id=a["id"]),
                        kind="front_threshold_reached",
                        description=f"Антагонист {a.get('name')} готов к шагу: {step_text}",
                        target_refs=(a["id"],),
                    )
                    intents.append(intent)

    for f in next_plan.get("fronts") or []:
        if f.get("status") in ("stopped", "completed"):
            continue
        for _ in range(periods):
            prog = int(f.get("progress") or 0)
            max_v = int(f.get("maximum") or 6)
            if prog >= max_v:
                break
            f["progress"] = prog + 1
            events.append({"front_id": f["id"], "progress": f["progress"]})

            if mode == "adaptive" and f["progress"] >= max_v - 1:
                intent = ReadyIntent(
                    id=f"intent:{f['id']}:{f['progress']}",
                    front_ref=FrontRef(campaign_id=cid, source_kind="front", source_id=f["id"]),
                    kind="front_threshold_reached",
                    description=f"Фронт {f.get('goal', '')} достиг порога готовности",
                    target_refs=(f["id"],),
                )
                intents.append(intent)

    return FrontTickResult(
        next_plan=next_plan,
        progress_events=tuple(events),
        ready_intents=tuple(intents),
    )


def advance_front(
    front: FrontView,
    ground: Ground,
    *,
    transition_key: str,
    processed_keys: set[str] | None = None,
    stop: bool = False,
) -> FrontTransition:
    """Attempt an atomic state or progress transition on a campaign front."""
    if processed_keys is not None and transition_key in processed_keys:
        return FrontTransition(
            front_ref=front.ref,
            previous_progress=front.progress,
            new_progress=front.progress,
            previous_status=front.status,
            new_status=front.status,
            transition_key=transition_key,
            violation="duplicate_transition_key",
        )

    if stop:
        return FrontTransition(
            front_ref=front.ref,
            previous_progress=front.progress,
            new_progress=front.progress,
            previous_status=front.status,
            new_status="stopped",
            transition_key=transition_key,
            violation=None,
        )

    if front.status in ("stopped", "completed"):
        return FrontTransition(
            front_ref=front.ref,
            previous_progress=front.progress,
            new_progress=front.progress,
            previous_status=front.status,
            new_status=front.status,
            transition_key=transition_key,
            violation="front_already_finished",
        )

    new_progress = min(front.maximum, front.progress + 1)
    new_status = "completed" if new_progress >= front.maximum else front.status
    ready_intent = None

    if new_progress >= front.maximum:
        ready_intent = ReadyIntent(
            id=f"ready:{front.ref.id}:{transition_key}",
            front_ref=front.ref,
            kind="front_threshold_reached",
            description=f"Фронт {front.goal} достиг максимального шага",
            target_refs=(front.ref.id,),
        )

    return FrontTransition(
        front_ref=front.ref,
        previous_progress=front.progress,
        new_progress=new_progress,
        previous_status=front.status,
        new_status=new_status,
        transition_key=transition_key,
        violation=None,
        ready_intent=ready_intent,
    )
