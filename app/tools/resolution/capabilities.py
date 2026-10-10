"""Closed capabilities. Missing data is never interpreted as creative freedom."""

from app.core.resolution.contracts import ActionRef, CapabilitySpec, FailureInfo
from app.tools.registry import ToolContext, ToolError
from app.tools.resolution.requests import load_action_context

OPERATIONS = frozenset(
    {
        "time",
        "remove_item",
        "drop_item",
        "move",
        "enter_room",
        "reposition",
        "hazard",
        "effect",
        "entity_update",
        "fact",
        "deed",
    }
)
CAPABILITIES = {
    "noncombat.interaction": CapabilitySpec(
        "noncombat.interaction",
        "noncombat",
        frozenset({"interact", "talk", "inspect", "search", "persuade", "deceive", "intimidate", "help", "hide"}),
        OPERATIONS,
        True,
        True,
        True,
    ),
    "creative.neutral_npc": CapabilitySpec(
        "creative.neutral_npc",
        "noncombat",
        frozenset({"interact", "talk", "inspect", "search"}),
        frozenset({"neutral_npc", "fact", "story_hook", "deed", "time"}),
        True,
        False,
        False,
    ),
    "standing.response": CapabilitySpec(
        "standing.response",
        "noncombat",
        frozenset({"standing_response"}),
        OPERATIONS | {"response"},
        True,
        False,
        False,
    ),
}


async def assess_support(ctx: ToolContext, ref: ActionRef, capability_id: str) -> FailureInfo | None:
    if capability_id not in CAPABILITIES:
        raise ToolError("неизвестная способность", code="unknown_capability", category="rule_denial")
    await load_action_context(ctx, ref)
    # No general inference of unsupported mechanics. Concrete adapters may add
    # a narrowly verified case; absence of an adapter is not a fallback grant.
    return None
