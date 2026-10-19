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
    "search_container": "finish",
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
        # «помогаю ему подняться и идти» вне боя: просто жест, исход не бросается
        return verb in {"interact", "search", "inspect", "use_item", "help"}

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
        act_skill = act.get("skill")
        call_skills = {s for s in (args.get("skill"), args.get("stat")) if s}
        if verb not in check_verbs and (not act_skill or act_skill not in call_skills):
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
        if verb == "give":
            # «даю ягоду раненому» — накормить получателя тем же предметом; применить на себя — не «отдать»
            return (
                bool(call_target)
                and call_target == action_target
                and act.get("instrument_id")
                in (
                    None,
                    args.get("inventory_id"),
                )
            )
        if verb not in {"use_item", "interact"}:
            return False
        if act.get("instrument_id") and args.get("inventory_id") and act["instrument_id"] != args["inventory_id"]:
            return False
        return True

    if name in {"move_character", "move", "travel_route", "enter_room", "cross_threshold", "traverse_passage"}:
        return verb in {"move", "dash", "disengage"}

    if name in {"give_item", "pass_item"}:
        # give_item выдаёт находку или награду из шаблона: игрок заявляет её как «беру», «ищу», «осматриваю»
        return verb == "give" or (name == "give_item" and verb in {"pick_up", "search", "interact", "inspect"})

    if name in {"pick_up_item", "take_item"}:
        return verb == "pick_up"

    if name in {"drop_item"}:
        return verb == "drop"

    if name in {"open_container", "inspect_container"}:
        return verb in {"interact", "inspect", "search"}

    if name == "search_container":
        return verb == "search" and (not action_target or action_target == args.get("container_id"))

    if name in {"store_object", "retrieve_object", "equip_item"}:
        return verb in {"use_item", "interact", "pick_up"}

    if name == "update_entity" and args.get("name"):
        # NPC назвался игроку: имя — ответ на реплику, а не отдельная механика
        return verb in {"talk", "persuade", "deceive", "intimidate", "inspect", "interact", "search", "help"}
    # Творческий путь: находка, которой в мире ещё не было, заводится инструментом, а не пересказом.
    if name in {"keep_found_item", "invent_item"} and verb in {"pick_up", "search", "interact", "inspect"}:
        return True
    if name == "place_item" and verb == "pick_up":
        return True  # «беру бумаги из тайника»: сначала предмет кладётся в сцену, затем герой его подбирает
    if name in {"create_container", "add_landmark"}:
        return verb in {"search", "inspect", "interact"}

    if name in {"edit_sketch", "place_item", "learn_fact", "reveal_knowledge"}:
        if name == "edit_sketch" and args.get("action") == "unlock":
            if action_target and args.get("target") and action_target != args["target"]:
                return False
        return verb in {"search", "inspect", "interact", "use_item", "custom"}

    return False


async def bind_tool_action(
    ctx: ToolContext,
    name: str,
    args: dict,
    explicit: ActionRef | None = None,
) -> ToolActionBinding | None:
    tool = REGISTRY.get(name)
    if tool is not None and not tool.mutating:
        return None
    if explicit is None and (name in AUXILIARY_TOOLS or name.startswith("audio_")):
        return None

    role = TOOL_ROLES.get(
        name,
        "finish" if REGISTRY.get(name, None) and REGISTRY[name].closes_actions else "consequence",
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

        from app.tools.resolution.requests import load_action_context

        await load_action_context(ctx, explicit)

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

        if name != "cancel_action":
            from app.agents.master.action_order import blocked_dependencies

            if blocked_dependencies(ctx, explicit):
                raise ToolError(
                    "предшествующее действие не выполнено",
                    code="dependency_pending",
                    category="invalid_arguments",
                )
        return ToolActionBinding(ref=explicit, role=role)

    if not ctx.required_actions:
        return None

    call_actor = extract_actor(args)
    if not call_actor and name in {"place_item", "edit_sketch"} and ctx.required_actions:
        distinct_actors = {r.actor_id for r in ctx.required_actions}
        if len(distinct_actors) == 1:
            call_actor = next(iter(distinct_actors))
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

    return await bind_tool_action(ctx, name, args, explicit=matching_refs[0])
