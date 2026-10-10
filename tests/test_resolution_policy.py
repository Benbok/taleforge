from dataclasses import replace

import pytest

from app.core.resolution.contracts import ActionContext, ActionRef, CapabilitySpec, FailureInfo
from app.core.resolution.policy import admit


def context(**changes):
    base = ActionContext(
        ActionRef(campaign_id="c", source_kind="message", source_id="m", actor_id="ch", part=0),
        ("interact",),
        (),
        "place",
        True,
        False,
        False,
        (),
        True,
        False,
    )
    return replace(base, **changes)


def capability():
    return CapabilitySpec(
        "noncombat.interaction",
        "noncombat",
        frozenset({"interact", "talk"}),
        frozenset({"time", "fact"}),
        True,
        True,
        True,
    )


@pytest.mark.parametrize(
    "category,rolled_back,route",
    [
        ("invalid_arguments", False, "repair"),
        ("rule_denial", True, "deny"),
        ("unknown", True, "deny"),
        ("unsupported", True, "fallback"),
        ("technical_safe", False, "deny"),
        ("technical_safe", True, "fallback"),
    ],
)
def test_failure_category_admission(category, rolled_back, route):
    failure = FailureInfo(code="code", category=category, rolled_back=rolled_back, attempt_id="a")
    assert admit(context(), capability(), failure).route == route


@pytest.mark.parametrize(
    "changes",
    [
        {"combat_related": True, "verbs": ("attack",)},
        {"combat_related": True, "verbs": ("talk", "attack")},
        {"affected_in_combat": True},
        {"verbs": ("custom",)},
        {"parsed": False},
        {"module_data_known": False},
        {"canonical_denial": True},
    ],
)
def test_unsafe_context_denied(changes):
    failure = FailureInfo(code="unsupported", category="unsupported", rolled_back=True, attempt_id="a")
    assert admit(context(**changes), capability(), failure).route == "deny"


def test_separate_noncombat_group_allowed():
    assert admit(context(affected_in_combat=False), capability(), None).route == "ordinary"
