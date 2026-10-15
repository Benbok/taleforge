"""Read-only proof that every declared part and mandatory obligation is settled."""

from dataclasses import dataclass

from app.agents.master.helpers import _unsettled_fails
from app.agents.master.searches import legacy_unresolved_searches, unresolved_searches
from app.tools.registry import ToolContext
from app.tools.resolution.requests import action_key

PENDING_KEYS = frozenset({"transition", "spawn", "reaction", "world_response", "plot"})


@dataclass(frozen=True)
class CompletionCheck:
    can_finish: bool
    reasons: tuple[str, ...]


def check_decision_completion(
    ctx: ToolContext,
    *,
    trace_calls: list[dict],
    required_actors: set[str],
    opening_actors: set[str],
    pending: dict[str, bool],
) -> CompletionCheck:
    reasons = []
    refs = ctx.required_actions
    if not required_actors or not refs:
        reasons.append("unbound_or_social_request")
    if not required_actors.issubset({ref.actor_id for ref in refs}):
        reasons.append("unbound_actor")
    # Opening initiative is not evidence that the queued action actually happened.
    for ref in refs:
        progress = ctx.action_progress.get(action_key(ref))
        if progress is None or progress.status not in {"completed", "denied", "blocked"}:
            reasons.append("nonterminal_part")
            break
    if set(pending) != PENDING_KEYS or any(type(value) is not bool for value in pending.values()):
        reasons.append("unknown_obligation")
    reasons.extend(f"pending_{key}" for key in sorted(PENDING_KEYS) if pending.get(key) is True)
    if unresolved_searches(ctx) or legacy_unresolved_searches(ctx):
        reasons.append("unconfirmed_search")
    if _unsettled_fails(ctx, trace_calls):
        reasons.append("critical_consequence")
    return CompletionCheck(not reasons, tuple(reasons))
