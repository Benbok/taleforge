"""Fail-closed policy over server-verified facts, not narrative claims."""

from app.core.resolution.contracts import ActionContext, Admission, CapabilitySpec, FailureInfo

COMBAT_VERBS = frozenset({"attack", "cast", "grapple", "shove", "dodge", "dash", "disengage"})


def admit(context: ActionContext, capability: CapabilitySpec, failure: FailureInfo | None) -> Admission:
    if capability.action_class != "noncombat" or context.combat_related or context.affected_in_combat:
        return Admission("deny", "combat_rules_required")
    if set(context.verbs) & COMBAT_VERBS:
        return Admission("deny", "combat_rules_required")
    if not context.parsed or not context.verbs or not set(context.verbs) <= capability.verbs:
        return Admission("deny", "unsupported_source")
    if context.canonical_denial or not context.module_data_known:
        return Admission("deny", "unverified_canon")
    if failure is None:
        return Admission("ordinary", "supported_action")
    if failure.category == "invalid_arguments":
        return Admission("repair", "correct_arguments")
    if failure.category == "unsupported" and capability.allow_unsupported:
        return Admission("fallback", "unsupported_mechanic")
    if failure.category == "technical_safe" and failure.rolled_back and capability.allow_safe_failure:
        return Admission("fallback", "safe_technical_failure")
    return Admission("deny", "failure_not_eligible")
