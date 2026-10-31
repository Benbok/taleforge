"""Серверный бюджет и ограниченные профили находок в сцене."""

import hashlib
from dataclasses import dataclass
from typing import Literal

from app.rules.universal.items import ItemProfile

LOOT_COUNTS = {"easy": (20, 50, 30), "normal": (30, 60, 10), "hard": (60, 40, 0), "deadly": (100, 0, 0)}
FALLBACK_NAMES = {"consumable": "Фляга с настойкой", "weapon": "Потёртый нож", "armor": "Кожаная куртка"}


@dataclass(frozen=True)
class LootSlot:
    ref: str
    kind: Literal["consumable", "weapon", "armor"]


def loot_slots(campaign, location_id: str) -> list[LootSlot]:
    if (campaign.settings or {}).get("loot_enabled") is False:
        return []
    digest = hashlib.sha256(f"loot:{campaign.id}:{location_id}".encode()).digest()
    zero, one, _ = LOOT_COUNTS.get(campaign.difficulty, LOOT_COUNTS["normal"])
    roll = int.from_bytes(digest[:8]) % 100
    count = 0 if roll < zero else 1 if roll < zero + one else 2
    result = []
    for i in range(count):
        kind_roll = digest[8 + i]
        kind = "consumable" if kind_roll < 128 else "weapon" if kind_roll < 192 else "armor"
        result.append(LootSlot(f"loot_{i + 1}", kind))
    return result


def loot_profile(slot: LootSlot, name: str, description: str, attribute: str = "str") -> ItemProfile:
    if attribute not in {"str", "dex"}:
        raise ValueError("Оружию нужна сила или ловкость")
    return ItemProfile(
        name=name,
        description=description,
        kind=slot.kind,
        status="common",
        attribute=attribute if slot.kind == "weapon" else "str",
        base_dice="1d4" if slot.kind == "weapon" and attribute == "dex" else "1d6",
        defense_bonus=1 if slot.kind == "armor" else 0,
        restore_pool="hp" if slot.kind == "consumable" else None,
        restore_amount=6,
    )


def available_loot(row, actor) -> None:
    if (
        row.campaign_id != actor.campaign_id
        or row.kind != "object"
        or row.location_id != actor.location_id
        or row.state.get("taken_by")
        or row.state.get("hidden")
        or row.state.get("secret")
        or row.state.get("visibility") in {"hidden", "private"}
    ):
        raise ValueError("Предмет уже взят или лежит в другом месте")


def loot_view(row) -> dict:
    return dict(
        id=row.id,
        name=row.name,
        description=row.description,
        location_id=row.location_id,
        template="loot",
        loot_kind=ItemProfile.model_validate(row.state["loot"]).kind,
    )


def item_id_of(campaign_id, actor_id, loot_id):
    """The id ``create_item`` gives the hero's copy of a find (it is derived, so it is known before it exists)."""
    return "en_" + hashlib.sha256(f"{campaign_id}:{actor_id}:loot:{loot_id}".encode()).hexdigest()[:24]


async def item_ref(session, campaign_id, actor_id, ref):
    """What an operation of this action means by ``ref``: a find this hero has taken is their own item by now."""
    if not ref:
        return ref
    from app.db.models import Entity

    row = await session.get(Entity, ref)
    if row is not None and "loot" in row.state and row.state.get("taken_by") == actor_id:
        return item_id_of(campaign_id, actor_id, ref)
    return ref


async def take_finds_first(ctx, action, source_event):
    """Finds named by a ``take`` are the hero's before anything else of the action runs, so that "take it and put
    it on" finds the item when the second part is carried out."""
    from app.db.models import Entity

    changes = []
    for index, op in enumerate(action.operations):
        if op.kind != "take" or not op.object_id:
            continue
        row = await ctx.session.get(Entity, op.object_id)
        if row is not None and "loot" in row.state and not row.state.get("taken_by"):
            changes.append(await pick_up(ctx, row, source_event, index))
    return changes


async def pick_up(ctx, row, source_event, index):
    from app.core.universal.inventory import create_item
    from app.db.models import Character
    from app.rules.universal.exploration import EffectChange

    actor = await ctx.session.get(Character, ctx.actor_id)
    available_loot(row, actor)
    item = await create_item(
        ctx.session,
        ctx.campaign_id,
        ctx.actor_id,
        ItemProfile.model_validate(row.state["loot"]),
        f"loot:{row.id}",
    )
    row.location_id = None
    row.state = {**row.state, "taken_by": ctx.actor_id}
    return EffectChange(kind="item_taken", subject_id=item.id, description=f"«{item.name}» теперь у героя.")
