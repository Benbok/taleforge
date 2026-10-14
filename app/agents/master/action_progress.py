"""Action progress lifecycle and verified completion of multipart player actions."""

from __future__ import annotations

from app.core.resolution.contracts import (
    ActionProgress,
    ActionRef,
    FailureInfo,
    ResolutionResult,
    ToolActionBinding,
)
from app.db.models import MasterTurn, Message
from app.tools.registry import ToolContext
from app.tools.resolution.requests import (
    action_key,
    action_tool_key,
    mark_resolved,
    set_action_progress,
)

SEARCH_STATS = frozenset({"perception", "investigation", "search"})


async def apply_tool_progress(
    ctx: ToolContext,
    binding: ToolActionBinding | None,
    raw: dict,
) -> None:
    """Update action part progress following a tool execution."""
    if binding is None:
        return

    ref = binding.ref
    role = binding.role
    ok = bool(raw.get("ok"))
    event_id = raw.get("event_id")
    event_ids = [event_id] if event_id else []

    current_prog = ctx.action_progress.get(action_key(ref))
    if current_prog and current_prog.status in {"completed", "denied", "blocked"}:
        return

    if role == "finish":
        if ok:
            if (raw.get("result") or {}).get("cancelled") or raw.get("cancelled") or raw.get("tool") == "cancel_action":
                res = ResolutionResult(execution="denied", event_ids=event_ids)
                prog = ActionProgress(status="denied", result=res)
                await set_action_progress(ctx, ref, prog)
                mark_resolved(ctx, ref)
            else:
                execution = "repeated" if raw.get("repeated") else "applied"
                res = ResolutionResult(execution=execution, game_outcome="success", event_ids=event_ids)
                prog = ActionProgress(status="completed", result=res)
                await set_action_progress(ctx, ref, prog)
                mark_resolved(ctx, ref)
        else:
            failure = raw.get("failure") or {}
            attempt_entry = {
                "ref": ref.model_dump(),
                "capability_id": "noncombat.interaction",
                "result": {
                    "execution": "denied",
                    "failure": failure,
                },
            }
            ctx.turn_diagnostics.setdefault("resolution_attempts", []).append(attempt_entry)
            if ctx.turn_id:
                turn = await ctx.session.get(MasterTurn, ctx.turn_id)
                if turn:
                    turn.trace = {
                        **(turn.trace or {}),
                        "resolution_attempts": [
                            *(turn.trace or {}).get("resolution_attempts", []),
                            attempt_entry,
                        ],
                    }
            # item_use_unsupported and invalid_arguments are not terminal
            if failure.get("code") != "item_use_unsupported" and failure.get("category") != "invalid_arguments":
                fail_info = FailureInfo.model_validate(failure) if failure else None
                res = ResolutionResult(execution="denied", failure=fail_info)
                prog = ActionProgress(status="denied", failure=fail_info, result=res)
                await set_action_progress(ctx, ref, prog)
                mark_resolved(ctx, ref)

    elif role == "check":
        if ok:
            res_dict = raw.get("result") or {}
            success = res_dict.get("success")
            stat = res_dict.get("stat")
            if success is False:
                # Gaming failure is terminal: completed without reroll
                res = ResolutionResult(execution="applied", game_outcome="failure", event_ids=event_ids)
                prog = ActionProgress(status="completed", result=res)
                await set_action_progress(ctx, ref, prog)
                mark_resolved(ctx, ref)
            elif success is True:
                if stat in SEARCH_STATS:
                    # Intermediate: successful search waits for discovery
                    ctx.turn_diagnostics.setdefault("search_checks", {})[action_key(ref)] = event_id
                else:
                    turn = await ctx.session.get(MasterTurn, ctx.turn_id) if ctx.turn_id else None
                    trace = (turn.trace or {}) if turn is not None else ctx.turn_diagnostics
                    attempts = [
                        a
                        for a in (trace.get("resolution_attempts") or [])
                        if action_key(ActionRef.model_validate(a["ref"])) == action_key(ref)
                    ]
                    has_unsupported_use = any(
                        (a.get("result", {}).get("failure") or {}).get("code") == "item_use_unsupported"
                        for a in attempts
                    )
                    if has_unsupported_use:
                        # Alternative path (e.g. lever check) waits for consequence (unlock)
                        ctx.turn_diagnostics.setdefault("lever_checks", {})[action_key(ref)] = event_id
                    else:
                        res = ResolutionResult(execution="applied", game_outcome="success", event_ids=event_ids)
                        prog = ActionProgress(status="completed", result=res)
                        await set_action_progress(ctx, ref, prog)
                        mark_resolved(ctx, ref)

    elif role == "consequence":
        tool_name = raw.get("tool")
        if not tool_name:
            for ev in reversed(ctx.events):
                if ev.id == event_id:
                    tool_name = ev.tool
                    break

        if ok and tool_name == "place_item":
            discovery_check_id = raw.get("result", {}).get("discovery_check_event_id")
            if discovery_check_id is None:
                for ev in reversed(ctx.events):
                    if ev.id == event_id:
                        discovery_check_id = ev.payload.get("discovery_check_event_id")
                        break
            if discovery_check_id:
                # Match against search checks of current actions
                for r in ctx.required_actions:
                    k = action_key(r)
                    if ctx.turn_diagnostics.get("search_checks", {}).get(k) == discovery_check_id:
                        check_ev_ids = [discovery_check_id, *event_ids]
                        res = ResolutionResult(execution="applied", game_outcome="success", event_ids=check_ev_ids)
                        prog = ActionProgress(status="completed", result=res)
                        await set_action_progress(ctx, r, prog)
                        mark_resolved(ctx, r)

        elif ok and tool_name in {"learn_fact", "reveal_knowledge"}:
            k = action_key(ref)
            check_ev_id = ctx.turn_diagnostics.get("search_checks", {}).get(k)
            check_ev_ids = [check_ev_id, *event_ids] if check_ev_id else event_ids
            res = ResolutionResult(execution="applied", game_outcome="success", event_ids=check_ev_ids)
            prog = ActionProgress(status="completed", result=res)
            await set_action_progress(ctx, ref, prog)
            mark_resolved(ctx, ref)

        elif ok and tool_name == "edit_sketch":
            action_type = raw.get("action") or raw.get("result", {}).get("action")
            if not action_type:
                for ev in reversed(ctx.events):
                    if ev.id == event_id:
                        action_type = ev.payload.get("action")
                        break
            if action_type == "unlock":
                sketch_target = raw.get("target") or raw.get("result", {}).get("passage")
                if not sketch_target:
                    for ev in reversed(ctx.events):
                        if ev.id == event_id:
                            sketch_target = ev.payload.get("target")
                            break
                # Check if this matches ref's target and had a successful check
                k = action_key(ref)
                lever_check_id = ctx.turn_diagnostics.get("lever_checks", {}).get(k)
                if lever_check_id and ref.source_kind == "message":
                    msg = await ctx.session.get(Message, ref.source_id)
                    actions = (msg.intent or {}).get("actions") or []
                    if ref.part < len(actions):
                        act = actions[ref.part]
                        if act.get("target_id") == sketch_target:
                            check_ev_ids = [lever_check_id, *event_ids]
                            res = ResolutionResult(execution="applied", game_outcome="success", event_ids=check_ev_ids)
                            prog = ActionProgress(status="completed", result=res)
                            await set_action_progress(ctx, ref, prog)
                            mark_resolved(ctx, ref)


def unresolved_searches(ctx: ToolContext) -> list[ActionRef] | list[str]:
    """Find search actions whose successful checks have not yet been confirmed by a discovery."""
    if not ctx.required_actions:
        from app.agents.master.searches import legacy_unresolved_searches as legacy_searches

        return legacy_searches(ctx)

    unresolved: list[ActionRef] = []
    for ref in ctx.required_actions:
        prog = ctx.action_progress.get(action_key(ref))
        if prog and prog.status == "completed":
            continue

        check_event_id = ctx.turn_diagnostics.get("search_checks", {}).get(action_key(ref))
        if not check_event_id:
            # Look in ctx.events for a successful search check
            for ev in ctx.events:
                if (
                    ev.tool == "roll_check"
                    and ev.actor_id == ref.actor_id
                    and ev.payload.get("kind") == "check"
                    and ev.payload.get("stat") in SEARCH_STATS
                    and ev.payload.get("success") is True
                ):
                    k = action_tool_key(ref, "roll_check", "primary_check")
                    if ev.idempotency_key == k or ev.idempotency_key == f"primary_check:{action_key(ref)}":
                        check_event_id = ev.id
                        break

        if check_event_id:
            # Check if confirmed
            confirmed = False
            for ev in ctx.events:
                if ev.tool == "place_item" and ev.payload.get("discovery_check_event_id") == check_event_id:
                    confirmed = True
                    break
                if ev.tool in {"learn_fact", "reveal_knowledge"} and ev.actor_id == ref.actor_id:
                    confirmed = True
                    break
            if not confirmed:
                unresolved.append(ref)

    return unresolved


async def finalize_action_parts(ctx: ToolContext) -> list[tuple[ActionRef, ActionProgress]]:
    """Finalize any non-terminal action parts at the end of the decision phase."""
    unresolved_keys = {
        action_key(r) if isinstance(r, ActionRef) else str(r)
        for r in unresolved_searches(ctx)
    }
    finalized: list[tuple[ActionRef, ActionProgress]] = []

    for ref in ctx.required_actions:
        key = action_key(ref)
        prog = ctx.action_progress.get(key)
        if prog and prog.status in {"completed", "denied", "blocked"}:
            continue

        if key in unresolved_keys:
            new_prog = ActionProgress(status="unhandled", reason_code="unconfirmed_search")
        else:
            turn = await ctx.session.get(MasterTurn, ctx.turn_id) if ctx.turn_id else None
            trace = (turn.trace or {}) if turn is not None else ctx.turn_diagnostics
            attempts = [
                a
                for a in (trace.get("resolution_attempts") or [])
                if action_key(ActionRef.model_validate(a["ref"])) == key
            ]
            if attempts:
                last_attempt = attempts[-1]
                res = last_attempt.get("result", {})
                fail = res.get("failure") or {}
                if fail.get("code") == "item_use_unsupported":
                    new_prog = ActionProgress(status="unhandled", reason_code="unsupported_mechanic")
                elif res.get("execution") == "denied":
                    fail_info = FailureInfo.model_validate(fail) if fail else None
                    new_prog = ActionProgress(status="denied", failure=fail_info)
                else:
                    new_prog = ActionProgress(status="unhandled")
            else:
                new_prog = ActionProgress(status="unhandled")

        await set_action_progress(ctx, ref, new_prog)
        finalized.append((ref, new_prog))

    return finalized


def public_action_notice(ctx: ToolContext, ref: ActionRef, progress: ActionProgress) -> str | None:
    """Format a public notice for uncompleted action parts."""
    if progress.status == "completed":
        return None
    if progress.status == "unhandled":
        if progress.reason_code == "unconfirmed_search":
            return "Осмотр не обработан: находка не зафиксирована"
        if progress.reason_code == "unsupported_mechanic":
            return "Действие с предметом не поддерживается правилами"
        return "Действие не обработано"
    if progress.status == "denied":
        return "Действие отклонено правилами"
    if progress.status == "blocked":
        return "Действие заблокировано"
    return None
