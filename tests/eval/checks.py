"""Structural checks only; no claim of measuring literary quality."""

from pydantic import ValidationError

from app.rules.universal.exploration import IntentV2, clean_model_intent
from tests.eval.cases import EvalCase


def check(case: EvalCase, raw_intent: dict) -> list[str]:
    try:
        intent = IntentV2.model_validate(clean_model_intent(raw_intent))
    except (ValidationError, ValueError, TypeError) as exc:
        return [f"schema: {exc}"]
    expected = case.expect
    kinds = {effect.kind for effect in intent.effects}
    issues = [f"нет effect {kind}" for kind in sorted(expected.effect_kinds - kinds)]
    issues.extend(f"запрещён effect {kind}" for kind in sorted(expected.forbid_kinds & kinds))
    if expected.destination and not any(
        effect.kind == "move" and effect.destination_id == expected.destination for effect in intent.effects
    ):
        issues.append(f"destination: expected {expected.destination}")
    resolution = raw_intent.get("resolution", intent.resolution)
    if expected.resolution and resolution != expected.resolution:
        issues.append(f"resolution: expected {expected.resolution}, got {resolution}")
    if expected.recipient and not any(effect.kind == "speak" and effect.recipient_id for effect in intent.effects):
        issues.append("speak needs recipient_id")
    if expected.source and intent.source != expected.source:
        issues.append(f"source: expected {expected.source}, got {intent.source}")
    if expected.forbid_introductions and intent.introductions:
        issues.append("introductions: no visible evidence for a new creature")
    # Always enforced even if an old case disabled quotes_from_source.
    issues.extend(f"quote not in source: {req.id}" for req in intent.requirements if req.quote not in case.source)
    return issues
