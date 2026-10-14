"""Action ordering, dependency tracking, and readiness for multipart player actions."""

from __future__ import annotations

from app.core.resolution.contracts import ActionDependency, ActionRef
from app.db.models import Message
from app.tools.registry import ToolContext
from app.tools.resolution.requests import action_key


def _get_dependencies(ctx: ToolContext, ref: ActionRef) -> list[ActionDependency]:
    k = action_key(ref)
    if hasattr(ctx, "action_dependencies") and k in ctx.action_dependencies:
        return ctx.action_dependencies[k]

    # Look up message in session identity map or session
    msg = None
    if ref.source_kind == "message":
        # Check session identity map (synchronous)
        for obj in ctx.session.identity_map.values():
            if isinstance(obj, Message) and obj.id == ref.source_id:
                msg = obj
                break

    if msg is not None:
        bound = (msg.data or {}).get("resolution_actions") or []
        if ref.part < len(bound):
            act = bound[ref.part].get("action") or {}
            deps_raw = act.get("depends_on") or []
            deps = [ActionDependency.model_validate(d) for d in deps_raw]
            if hasattr(ctx, "action_dependencies"):
                ctx.action_dependencies[k] = deps
            return deps

        actions = (msg.intent or {}).get("actions") or []
        if ref.part < len(actions):
            act = actions[ref.part] or {}
            deps_raw = act.get("depends_on") or []
            deps = [ActionDependency.model_validate(d) for d in deps_raw]
            if hasattr(ctx, "action_dependencies"):
                ctx.action_dependencies[k] = deps
            return deps

    return []


def blocked_dependencies(ctx: ToolContext, ref: ActionRef) -> list[int]:
    """Return part indices of dependencies that are not satisfied."""
    deps = _get_dependencies(ctx, ref)
    if not deps:
        return []

    blocked: list[int] = []
    for dep in deps:
        dep_ref = ActionRef(
            campaign_id=ref.campaign_id,
            source_kind=ref.source_kind,
            source_id=ref.source_id,
            actor_id=ref.actor_id,
            part=dep.part,
        )
        prog = ctx.action_progress.get(action_key(dep_ref))
        if prog is None or prog.status != "completed":
            blocked.append(dep.part)
            continue

        if dep.requires == "success":
            if not (prog.result and prog.result.game_outcome == "success"):
                blocked.append(dep.part)

    return blocked


def ready_action_refs(ctx: ToolContext) -> list[ActionRef]:
    """Return actions that have not been finalized and have all dependencies satisfied."""
    ready: list[ActionRef] = []
    for ref in ctx.required_actions:
        prog = ctx.action_progress.get(action_key(ref))
        if prog and prog.status in {"completed", "denied", "blocked"}:
            continue

        if blocked_dependencies(ctx, ref):
            continue

        ready.append(ref)

    return ready
