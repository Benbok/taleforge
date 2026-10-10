"""Server-authoritative execution of a narrow, deterministic natural-language action plan.

This first stage only auto-executes a clear sequence: approach a particular
hostile creature, then strike it with a specific weapon. Creative or ambiguous
actions remain with the AI master. Do not infer bonuses from roleplay prose.
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
