"""Public factual outcomes and deterministic failure rendering."""

from app.rules.universal.failures import ActionFailure
from app.rules.universal.profiles import ActionOutcome


def prepared_outcome(prepared):
    if prepared.failure:
        return failed_outcome(prepared.failure)
    return dict(status="narrative", success=True, reason=prepared.public_reason)


def failed_outcome(failure):
    return {**ActionOutcome(status="denied", failure=failure).model_dump(mode="json"), "reason": failure.message}


def public_outcome(result, reason):
    if result.failure:
        return failed_outcome(result.failure)
    outcome = {**result.model_dump(mode="json", exclude={"private_effects", "checks", "draws"}), "reason": reason}
    if not result.success:
        outcome["failure"] = ActionFailure(
            category="roll_failed",
            code="critical_roll_failed" if result.critical_failure else "roll_failed",
            message="Критический провал проверки." if result.critical_failure else "Проверка не удалась.",
        ).model_dump()
    return outcome


def narration_parts(outcomes):
    story, notices = {}, []
    for source, outcome in outcomes.items():
        failure = outcome.get("failure")
        if failure and failure["category"] != "roll_failed":
            notices.append(failure["message"])
        else:
            story[source] = outcome
    return story, notices


def mark_source(source, outcome):
    data = dict(source.data or {})
    if outcome.get("failure"):
        data["action_failure"] = outcome["failure"]
    else:
        data.pop("action_failure", None)
    source.data = data
