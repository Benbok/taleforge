"""Server-authoritative execution of a narrow, deterministic natural-language action plan.

Auto-executes clear, ordered declarations: approach a specific target then
strike with a weapon or cast a targeted spell. Creative or ambiguous actions
remain with the AI master. Do not infer bonuses from roleplay prose.
"""

from __future__ import annotations

from typing import Any

from app.core import combat, steps
from app.tools.movement import hero_step
from app.tools.registry import ToolContext, ToolError, execute


def approach_attack(intent: dict[str, Any] | None) -> dict[str, str] | None:
    """Structured move -> attack intent (never silently reorder actions)."""
    if not intent or intent.get("confidence", 0) < 0.8:
        return None
    actions = intent.get("actions") or []
    if len(actions) != 2 or [a.get("verb") for a in actions] != ["move", "attack"]:
        return None
    move, attack = actions
    target_id = attack.get("target_id")
    weapon_id = attack.get("instrument_id")
    hero_id = intent.get("character_id")
    if (
        not isinstance(hero_id, str)
        or not isinstance(target_id, str)
        or not isinstance(weapon_id, str)
        or attack.get("missing_item")
        or move.get("zone") not in (None, "melee")
        or move.get("target_id") not in (None, target_id)
        or (move.get("zone") != "melee" and move.get("target_id") != target_id)
    ):
        return None
    return {"attacker_id": hero_id, "target_id": target_id, "attack": weapon_id}


def hostile_target(ctx: ToolContext, plan: dict[str, str]) -> bool:
    """An actual living hostile in the same place, not just text in a story."""
    w = ctx.world
    hero_id, target_id = plan["attacker_id"], plan["target_id"]
    target = w.entities.get(target_id)
    return bool(
        hero_id in w.characters
        and target is not None
        and target.kind == "creature"
        and not (target.state or {}).get("dead")
        and not (target.state or {}).get("fled")
        and (target.state or {}).get("attitude", "hostile") == "hostile"
        and w.actor_place(hero_id) == w.actor_place(target_id)
    )


async def execute_approach_attack(ctx: ToolContext, plan: dict[str, str], key: str) -> dict[str, Any]:
    """Move on the battle grid, then resolve exactly one weapon attack.

    Never auto-confirm Dash or opportunity attacks. On a denied move/attack,
    retain the hero's turn and report the real reason, not a fictional miss.
    """
    hero_id, target_id = plan["attacker_id"], plan["target_id"]
    if not combat.in_combat(ctx) or combat.current_id(ctx) != hero_id:
        return {"completed": False, "notes": ["Нельзя действовать вне своего хода инициативы"]}
    if combat.state(ctx).get("actor") != hero_id:
        return {"completed": False, "notes": ["Боевой ход героя ещё не подготовлен"]}
    if not hostile_target(ctx, plan):
        return {
            "completed": False,
            "notes": ["Цель недоступна: она отсутствует, выведена из боя или находится в другом месте"],
        }

    name = ctx.world.characters[hero_id].name
    target_name = ctx.world.entities[target_id].name
    try:
        move = await hero_step(ctx, hero_id, None, near=[steps.cell_of(ctx.world, target_id)])
    except ToolError as exc:
        return {"completed": False, "notes": [f"{name}: сближение с {target_name} не выполнено: {exc}"]}

    if move.get("confirm_needed"):
        warnings = "; ".join(move.get("warnings") or [])
        return {
            "completed": False,
            "notes": [f"{name}: движение требует подтверждения: {warnings}. Удар ещё не выполнялся."],
        }
    if not ctx.world.actor(hero_id).alive or ctx.world.actor(hero_id).hp.current <= 0:
        return {"completed": False, "notes": [f"{name} не может атаковать после перемещения"]}

    result = await execute(ctx, "resolve_attack", plan, key=key)
    if not result.get("ok"):
        return {
            "completed": False,
            "notes": [f"{name}: перемещение учтено, но атака не выполнена: {result.get('error')}"],
            "movement": move,
        }
    return {
        "completed": True,
        "notes": [
            f"{name} сближается с {target_name} ({move.get('moved_ft', 0)} фт)",
            combat._attack_note(name, target_name, result["result"]),
        ],
        "movement": move,
        "attack_result": result["result"],
    }


def approach_cast(ctx: ToolContext, intent: dict[str, Any] | None) -> dict[str, Any] | None:
    """High-confidence approach followed by one targeted, combat-time spell.

    No rituals, reaction spells, area-selection guesses or missing targets.
    The original order and explicit target are required before auto-routing.
    """
    from app.agents.master.common import _routable_cast
    from app.core.spells import spell_catalog
    from app.rules.dnd5e import spells as rules

    if not intent or intent.get("confidence", 0) < 0.8:
        return None
    actions = intent.get("actions") or []
    if len(actions) != 2 or [a.get("verb") for a in actions] != ["move", "cast"]:
        return None
    move, cast = actions
    args = _routable_cast(ctx, {"character_id": intent.get("character_id"), "confidence": intent["confidence"],
                                "actions": [cast]})
    if not args or args.get("ritual") or len(args.get("target_ids") or []) != 1:
        return None
    target_id = args["target_ids"][0]
    if (
        move.get("zone") not in (None, "melee")
        or move.get("target_id") not in (None, target_id)
        or (move.get("zone") != "melee" and move.get("target_id") != target_id)
    ):
        return None
    spell = spell_catalog(ctx.world.catalog).spells.get(args["spell_id"])
    if not spell or spell.get("casting_time") not in ("1 action", "1 bonus action"):
        return None
    if rules.target_kind(spell) == "area":
        return None
    if args["caster_id"] not in ctx.world.characters:
        return None
    if target_id not in ctx.world.characters and target_id not in ctx.world.entities:
        return None
    return {"kind": "cast", "caster_id": args["caster_id"], "target_id": target_id, "cast": args}


def hostile_cast_plan(ctx: ToolContext, plan: dict[str, Any]) -> bool:
    """Initiative trigger only for explicitly hostile damaging spell plans."""
    from app.core.spells import spell_catalog

    if plan.get("kind") != "cast":
        return False
    spell = spell_catalog(ctx.world.catalog).spells.get(plan["cast"]["spell_id"])
    return bool(
        spell
        and any(spell.get(k) for k in ("attack", "save", "damage", "auto_hit"))
        and hostile_target(ctx, {"attacker_id": plan["caster_id"], "target_id": plan["target_id"]})
    )


async def execute_approach_cast(ctx: ToolContext, plan: dict[str, Any], key: str) -> dict[str, Any]:
    """Actually move before casting; preserve slots and action on blocked movement."""
    hero_id, target_id = plan["caster_id"], plan["target_id"]
    if not combat.in_combat(ctx) or combat.current_id(ctx) != hero_id:
        return {"completed": False, "notes": ["Нельзя творить заклинание вне своего хода инициативы"]}
    if combat.state(ctx).get("actor") != hero_id:
        return {"completed": False, "notes": ["Боевой ход заклинателя ещё не подготовлен"]}
    w = ctx.world
    if w.actor_place(hero_id) != w.actor_place(target_id) or not w.actor(target_id).alive:
        return {"completed": False, "notes": ["Цель недоступна или находится в другом месте"]}
    name = w.characters[hero_id].name
    target_name = w.actor(target_id).name
    try:
        movement = await hero_step(ctx, hero_id, None, near=[steps.cell_of(w, target_id)])
    except ToolError as exc:
        return {"completed": False, "notes": [f"{name}: сближение с {target_name} не выполнено: {exc}"]}
    if movement.get("confirm_needed"):
        details = "; ".join(movement.get("warnings") or [])
        return {"completed": False, "notes": [f"{name}: движение требует подтверждения: {details}. "
                                               "Заклинание не сотворено."]}
    if not w.actor(hero_id).alive or w.actor(hero_id).hp.current <= 0:
        return {"completed": False, "notes": [f"{name} не может колдовать после перемещения"]}

    result = await execute(ctx, "cast_spell", plan["cast"], key=key)
    if not result.get("ok"):
        return {
            "completed": False,
            "notes": [f"{name}: перемещение выполнено, но заклинание не сотворено: {result.get('error')}"],
            "movement": movement,
        }
    return {
        "completed": True,
        "notes": [f"{name} сближается с {target_name} ({movement.get('moved_ft', 0)} фт)",
                  f"{name} творит заклинание: результат записан в журнал"],
        "movement": movement,
        "spell_result": result["result"],
    }


async def execute_action_plan(ctx: ToolContext, plan: dict[str, Any], key: str) -> dict[str, Any]:
    """Dispatch a persisted ordered plan; legacy weapon plans remain supported."""
    if plan.get("kind") == "cast":
        return await execute_approach_cast(ctx, plan, key)
    return await execute_approach_attack(ctx, plan, key)
