"""Связь захвата с удерживающим: состояние, автоматическое освобождение и журнал.

Состояние «Схваченный» само по себе не знает, кто именно держит цель.
Связи хранятся в сцене и перепроверяются после перемещений и при смене хода.
"""

from __future__ import annotations

import copy

from app.rules.dnd5e import modifiers as mod
from app.tools import effects as fx
from app.tools.registry import ToolContext

KEY = "grapple_links"


def links(ctx: ToolContext) -> list[dict]:
    return list((ctx.world.scene.state or {}).get(KEY) or [])


def holders(ctx: ToolContext, target_id: str) -> list[str]:
    return [row["holder"] for row in links(ctx) if row["target"] == target_id]


def _snap(ctx: ToolContext) -> dict:
    return {"table": "scenes", "id": ctx.campaign.id, "field": "state", "before": copy.deepcopy(ctx.world.scene.state)}


def _valid(ctx: ToolContext, row: dict) -> bool:
    w = ctx.world
    hid, tid = row.get("holder"), row.get("target")
    if not (hid in w.characters or hid in w.entities):
        return False
    if not (tid in w.characters or tid in w.entities):
        return False
    holder, target = w.actor(hid), w.actor(tid)
    return (
        holder.conscious
        and not mod.can_act(holder.modifiers)
        and target.alive
        and w.actor_place(hid) == w.actor_place(tid)
        and w.distance_ft(holder, target) <= 5
        and (hid not in w.characters or _equipped_hands(ctx, hid) + _held_count(ctx, hid) <= 2)
    )


async def establish(ctx: ToolContext, holder_id: str, target_id: str) -> list[dict]:
    """Зафиксировать успешное противоборство; вернуть обратные изменения."""
    before = _snap(ctx)
    target = ctx.world.actor(target_id)
    existing = any(rec.id == "condition.grappled" for _, rec in target.effects)
    if not existing:
        effect, _ = await fx.add_effect(ctx, target, ctx.world.catalog.condition("grappled"), None)
    else:
        effect = None
    current = links(ctx)
    current.append({"holder": holder_id, "target": target_id, "owns_condition": effect is not None})
    ctx.world.scene.state = {**(ctx.world.scene.state or {}), KEY: current}
    inverse = [before]
    if effect is not None:
        inverse.append({"table": "active_effects", "op": "delete", "id": effect.id})
    return inverse


async def release(ctx: ToolContext, holder_id: str, target_id: str, reason: str) -> bool:
    """Освободить одну связь; оставшиеся удерживающие продолжают захват."""
    current = links(ctx)
    removed = [r for r in current if r["holder"] == holder_id and r["target"] == target_id]
    if not removed:
        return False
    inv = [_snap(ctx)]
    kept = [r for r in current if r not in removed]
    remaining = [r for r in kept if r["target"] == target_id]
    owned = any(r.get("owns_condition") for r in removed)
    if owned and remaining:
        remaining[0]["owns_condition"] = True
    ctx.world.scene.state = {**(ctx.world.scene.state or {}), KEY: kept}
    if owned and not remaining:
        target = ctx.world.actor(target_id)
        effect = next((e for e, rec in target.effects if rec.id == "condition.grappled"), None)
        if effect is not None:
            inv.append(
                {
                    "table": "active_effects",
                    "op": "restore",
                    "row": {
                        "id": effect.id,
                        "effect_template_id": effect.effect_template_id,
                        "stacks": effect.stacks,
                        "expires_at": effect.expires_at,
                        "target_id": effect.target_id,
                    },
                }
            )
            await fx.remove_effect(ctx, target, effect.id)
    await ctx.record(
        "grapple_release",
        actor_id=holder_id,
        target_id=target_id,
        payload={"holder_id": holder_id, "target_id": target_id, "reason": reason},
        inverse=inv,
    )
    return True


async def refresh(ctx: ToolContext) -> list[str]:
    """Снять захваты после оглушения, потери сознания, смерти и разрыва дистанции."""
    messages = []
    for row in links(ctx):
        if not _valid(ctx, row):
            if await release(ctx, row["holder"], row["target"], "условия удержания нарушены"):
                messages.append(f"{row['target']}: захват прекратился")
    return messages


def _held_count(ctx: ToolContext, holder_id: str) -> int:
    return sum(1 for row in links(ctx) if row["holder"] == holder_id)


def _equipped_hands(ctx: ToolContext, character_id: str) -> int:
    hands = 0
    for it in ctx.world.inventory.get(character_id, []):
        if not it.equipped:
            continue
        rec = ctx.world.catalog.find(it.item_template_id)
        item = rec.data if rec else {}
        if item.get("armor_type") == "shield":
            hands += 1
        elif item.get("category") == "weapon":
            props = item.get("properties") or []
            hands += 2 if "two_handed" in props or "two-handed" in props else 1
    return hands


def free_hand(ctx: ToolContext, character_id: str) -> bool:
    """На каждую удерживаемую цель нужна отдельная свободная рука."""
    return _equipped_hands(ctx, character_id) + _held_count(ctx, character_id) < 2
