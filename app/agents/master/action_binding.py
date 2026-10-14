"""Verifiable matching of tools and player action parts before world mutation."""

from typing import Literal

from app.core.resolution.contracts import ActionRef, ToolActionBinding
from app.db.models import Message
from app.tools.registry import REGISTRY, ToolContext, ToolError

AUXILIARY_TOOLS = frozenset(
    {
        "spawn_entity",
        "update_entity",
        "set_scene_mode",
        "record_deed",
        "time_advance",
        "advance_time",
        "narrate",
        "whisper",
        "suggest",
        "request_reaction",
        "roll_initiative",
    }
)

TOOL_ROLES: dict[str, Literal["prepare", "check", "consequence", "finish"]] = {
    "roll_check": "check",
    "cast_spell": "finish",
    "resolve_attack": "finish",
    "use_item": "finish",
    "move_character": "finish",
    "pass_item": "finish",
    "give_item": "finish",
    "pick_up_item": "finish",
    "drop_item": "finish",
    "adjudicate_action": "finish",
    "edit_sketch": "consequence",
    "place_item": "consequence",
    "learn_fact": "consequence",
    "reveal_knowledge": "consequence",
}


def extract_actor(args: dict) -> str | None:
    return (
        args.get("character_id")
        or args.get("caster_id")
        or args.get("attacker_id")
        or args.get("from_character_id")
        or (args.get("character_ids") or [None])[0]
    )


def is_action_compatible(name: str, args: dict, act: dict) -> bool:
    verb = act.get("verb")
    if verb == "custom":
        return True

    action_target = act.get("target_id")
    action_targets = set(act.get("target_ids") or [])
    if action_target:
        action_targets.add(action_target)

    call_target = args.get("target_id")
    call_targets = set(args.get("target_ids") or [])
    if call_target:
        call_targets.add(call_target)

    if name in {"cancel_action", "adjudicate_action"}:
        return True

    if name == "auto_success":
        return verb in {"interact", "search", "inspect", "pick_up", "drop", "use_item"}

    if name == "roll_check":
        check_verbs = {
            "search",
            "inspect",
            "interact",
            "talk",
            "persuade",
            "deceive",
            "intimidate",
            "hide",
            "help",
        }
        if verb not in check_verbs and act.get("skill") not in (args.get("skill"), args.get("stat")):
            return False
        if action_targets and call_targets and not (action_targets & call_targets):
            return False
        return True

    if name == "cast_spell":
        if verb != "cast":
            return False
        if act.get("spell_id") and args.get("spell_id") and act["spell_id"] != args["spell_id"]:
            return False
        if action_targets and call_targets and not (action_targets & call_targets):
            return False
        return True

    if name in {"resolve_attack", "resolve_shove", "resolve_grapple", "escape_grapple"}:
        if verb not in {"attack", "shove", "grapple", "escape_grapple"}:
            return False
        if action_targets and call_targets and not (action_targets & call_targets):
            return False
        return True

    if name == "use_item":
        if verb not in {"use_item", "interact"}:
            return False
        if act.get("instrument_id") and args.get("item_id") and act["instrument_id"] != args["item_id"]:
            return False
        return True

    if name in {"move_character", "move", "enter_room", "cross_threshold", "traverse_passage"}:
        return verb in {"move", "dash", "disengage"}

    if name in {"give_item", "pass_item"}:
        return verb == "give"

    if name in {"pick_up_item", "take_item"}:
        return verb == "pick_up"

    if name in {"drop_item"}:
        return verb == "drop"

    if name in {"open_container", "inspect_container"}:
        return verb in {"interact", "inspect", "search"}

    if name in {"store_object", "retrieve_object", "equip_item"}:
        return verb in {"use_item", "interact", "pick_up"}

    if name in {"edit_sketch", "place_item", "learn_fact", "reveal_knowledge"}:
        return True

    return False


async def bind_tool_action(
    ctx: ToolContext,
    name: str,
    args: dict,
    explicit: ActionRef | None = None,
) -> ToolActionBinding | None:
    if name in AUXILIARY_TOOLS or name.startswith("audio_"):
        return None

    role = TOOL_ROLES.get(
        name,
        "finish"
        if REGISTRY.get(name, None) and REGISTRY[name].closes_actions
        else "consequence",
    )

    if explicit is None and name == "adjudicate_action":
        proposal = args.get("proposal") or {}
        ref_data = proposal.get("ref")
        if ref_data:
            explicit = ActionRef.model_validate(ref_data)

    if explicit is not None:
        if explicit.campaign_id != ctx.campaign.id:
            raise ToolError("чужая заявка", code="invalid_source", category="rule_denial")
        if explicit.actor_id not in ctx.world.characters:
            raise ToolError("неизвестный персонаж", code="invalid_source", category="rule_denial")
        if ctx.required_actions and explicit not in ctx.required_actions:
            raise ToolError("заявка не найдена в текущем ходе", code="invalid_source", category="rule_denial")

        call_actor = extract_actor(args)
        if call_actor and call_actor != explicit.actor_id:
            raise ToolError("персонаж вызова не совпадает с заявкой", code="actor_mismatch", category="rule_denial")

        if explicit.source_kind == "message":
            message = await ctx.session.get(Message, explicit.source_id)
            if not message:
                raise ToolError("сообщение не найдено", code="invalid_source", category="rule_denial")
            bound = (message.data or {}).get("resolution_actions") or []
            if explicit.part >= len(bound):
                raise ToolError("часть заявки не найдена", code="invalid_source", category="rule_denial")
            act = bound[explicit.part]["action"]
            if not is_action_compatible(name, args, act):
                raise ToolError(
                    f"действие {name} несовместимо с частью заявки {act.get('verb')}",
                    code="verb_mismatch",
                    category="rule_denial",
                )

        return ToolActionBinding(ref=explicit, role=role)

    if not ctx.required_actions:
        return None

    call_actor = extract_actor(args)
    if not call_actor:
        return None

    actor_refs = [r for r in ctx.required_actions if r.actor_id == call_actor]
    if not actor_refs:
        return None

    matching_refs: list[ActionRef] = []
    for r in actor_refs:
        if r.source_kind == "message":
            message = await ctx.session.get(Message, r.source_id)
            if not message:
                continue
            bound = (message.data or {}).get("resolution_actions") or []
            if r.part < len(bound):
                act = bound[r.part]["action"]
                if is_action_compatible(name, args, act):
                    matching_refs.append(r)
        elif r.source_kind == "standing_response":
            if name == "adjudicate_action":
                matching_refs.append(r)

    if not matching_refs:
        if REGISTRY.get(name) and (
            REGISTRY[name].closes_actions or name in {"cast_spell", "resolve_attack", "roll_check", "use_item"}
        ):
            raise ToolError(
                f"нет подходящей заявки для вызова {name}",
                code="no_matching_action",
                category="rule_denial",
            )
        return None

    if len(matching_refs) > 1:
        candidates = [r.model_dump() for r in matching_refs]
        raise ToolError(
            f"Неоднозначный вызов {name}: несколько подходящих заявок. Укажите action_ref из кандидатов: {candidates}",
            code="ambiguous_action",
            category="invalid_arguments",
        )

    return ToolActionBinding(ref=matching_refs[0], role=role)
