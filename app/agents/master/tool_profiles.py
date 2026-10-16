"""Stable, conservative decision tool subsets; campaign permissions remain authoritative."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError

from app.agents.intent import ROUTE_CONFIDENCE, Intent
from app.agents.master.common import decision_tools
from app.tools.registry import ToolContext, tool

EXPAND_TOOL = "expand_decision_tools"


class ExpandDecisionToolsArgs(BaseModel):
    model_config = ConfigDict(extra="forbid")


@tool(
    EXPAND_TOOL,
    "Расширить инструменты решения до general до конца этого хода.",
    ExpandDecisionToolsArgs,
    mutating=False,
    closes=False,
)
async def expand_decision_tools(ctx: ToolContext, args: ExpandDecisionToolsArgs) -> dict:
    # The orchestrator owns the allowed set. This handler never mutates world state.
    return {"profile": "general"}


_COMBAT_VERBS = frozenset("attack cast dodge dash disengage grapple escape_grapple shove".split())
_EXPLORATION_VERBS = frozenset("move inspect search interact pick_up drop give hide rest use_item".split())
_SOCIAL_VERBS = frozenset("talk persuade deceive intimidate".split())

# Explicit mutation allowlists: newly registered mutations appear only in general.
_COMMON = frozenset("cancel_action roll_check auto_success adjudicate_action whisper".split())
_COMBAT = frozenset(
    "resolve_attack resolve_grapple escape_grapple resolve_shove take_action death_save "
    "apply_hazard apply_effect remove_effect use_item equip_item move reposition "
    "place_area remove_area set_scene_mode cast_spell use_feature grant_inspiration".split()
)
_EXPLORATION = frozenset(
    "move traverse_passage enter_room cross_threshold reveal_area reveal_knowledge "
    "learn_fact advance_time rest use_item give_item keep_found_item take_item "
    "equip_item place_item pick_up_item drop_item pass_item create_container "
    "open_container store_object retrieve_object search_container resolve_location "
    "retry_preparation set_scene_mode apply_hazard".split()
)
_SOCIAL = frozenset(
    "update_entity join_party leave_party reveal_knowledge learn_fact record_deed "
    "expose_deed resolve_response grant_inspiration".split()
)
_PROFILE_MUTATIONS = {"combat": _COMBAT, "exploration": _EXPLORATION, "social": _SOCIAL}

# Read-only tools are deliberately enumerated per route.  The general profile
# remains the complete campaign-allowed set after explicit expansion.
_PROFILE_READS = {
    "combat": frozenset({"get_scene", "get_character", "lookup_template", "get_standing"}),
    "exploration": frozenset(
        {"get_scene", "get_character", "lookup_template", "inspect_container", "preparation_cost", "generation_status"}
    ),
    "social": frozenset({"get_scene", "get_character", "lookup_template", "get_standing"}),
}


def select_tool_profile(ctx: ToolContext, messages: list) -> str:
    """Use validated parser output only; uncertain or mixed requests retain general."""
    profiles = set()
    if not messages:
        return "general"
    for message in messages:
        raw = getattr(message, "intent", None)
        if not isinstance(raw, dict) or not raw:
            return "general"
        try:
            intent = Intent.model_validate(raw)
        except (ValidationError, TypeError, ValueError):
            return "general"
        if intent.confidence < ROUTE_CONFIDENCE or intent.problem != "none":
            return "general"
        if intent.kind == "speech" and not intent.actions:
            profiles.add("social")
        elif intent.kind != "action" or not intent.actions:
            return "general"
        for action in intent.actions:
            verb = action.verb
            if verb in _COMBAT_VERBS:
                profiles.add("combat")
            elif verb in _EXPLORATION_VERBS:
                profiles.add("exploration")
            elif verb in _SOCIAL_VERBS:
                profiles.add("social")
            else:
                return "general"
    # Social/exploration actions in an ongoing battle may require reactions/economy.
    if getattr(ctx.world.scene, "mode", None) == "combat" and profiles != {"combat"}:
        return "general"
    return next(iter(profiles)) if len(profiles) == 1 else "general"


def profile_tool_names(ctx: ToolContext, profile: str) -> list[str]:
    permitted = set(decision_tools(ctx))
    permitted.add(EXPAND_TOOL)
    if profile not in _PROFILE_MUTATIONS:
        return sorted(permitted)
    reads = _PROFILE_READS[profile]
    return sorted(permitted & (_COMMON | _PROFILE_MUTATIONS[profile] | reads | {EXPAND_TOOL}))


def profile_id_context(ctx: ToolContext, names: list[str]) -> dict[str, list[str]]:
    """Move each schema ID namespace once into dynamic context, using the same source."""
    from app.tools.registry import REGISTRY, _enum_values

    keys = {key for name in names if name in REGISTRY for key in REGISTRY[name].id_fields.values()}
    return {key: _enum_values(ctx.world, key) for key in sorted(keys)}
