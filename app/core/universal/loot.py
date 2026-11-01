"""Серверный бюджет и ограниченные профили находок в сцене."""

import hashlib
from dataclasses import dataclass
from typing import Literal

from app.rules.universal.items import BONUS_BUDGET, PRICE, TAKE_DIFFICULTY, ItemProfile

LOOT_COUNTS = {"easy": (20, 50, 30), "normal": (30, 60, 10), "hard": (60, 40, 0), "deadly": (100, 0, 0)}
FALLBACK_NAMES = {"consumable": "Фляга с настойкой", "weapon": "Потёртый нож", "armor": "Кожаная куртка"}
RARITIES = ("common", "rare", "unique", "epic")
# Share of finds by rarity, in hundredths, and of the stock in a shop, which is better than what lies on the road.
LOOT_RARITY = (70, 22, 7, 1)
SHOP_RARITY = (50, 35, 12, 3)
SHOP_CHANCE = 30  # hundredths of scenes that have a merchant's stall
SHOP_ITEMS = 3
RESTORE = (6, 10, 16, 24)  # what a draught restores, by rarity


@dataclass(frozen=True)
class LootSlot:
    ref: str
    kind: Literal["consumable", "weapon", "armor"]
    rarity: Literal["common", "rare", "unique", "epic"] = "common"


def _rarity(roll: int, weights) -> str:
    """The rarity a hundredths roll falls in; the rarer the kind, the narrower its share."""
    edge = 0
    for name, weight in zip(RARITIES, weights, strict=True):
        edge += weight
        if roll < edge:
            return name
    return RARITIES[0]


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
        rarity = _rarity(int.from_bytes(digest[16 + 2 * i : 18 + 2 * i]) % 100, LOOT_RARITY)
        result.append(LootSlot(f"loot_{i + 1}", kind, rarity))
    return result


def shop_slots(campaign, location_id: str) -> list[LootSlot]:
    """The goods of a merchant, if this place has one: decided by the server, so the stall's worth is not the
    model's to inflate; the model only names and describes them."""
    if (campaign.settings or {}).get("loot_enabled") is False:
        return []
    digest = hashlib.sha256(f"shop:{campaign.id}:{location_id}".encode()).digest()
    chance = (campaign.settings or {}).get("shop_chance", SHOP_CHANCE)  # a world of markets may ask for more stalls
    if int.from_bytes(digest[:4]) % 100 >= chance:
        return []
    result = []
    for i in range(SHOP_ITEMS):
        kind = ("consumable", "weapon", "armor")[(digest[8] + i) % 3]  # a stall shows a bit of everything
        rarity = _rarity(int.from_bytes(digest[16 + 2 * i : 18 + 2 * i]) % 100, SHOP_RARITY)
        result.append(LootSlot(f"shop_{i + 1}", kind, rarity))
    return result


def loot_profile(slot: LootSlot, name: str, description: str, attribute: str = "str") -> ItemProfile:
    if attribute not in {"str", "dex"}:
        raise ValueError("Оружию нужна сила или ловкость")
    tier = BONUS_BUDGET[slot.rarity]  # the bonuses a rarity may carry are the budget the item rules allow
    weapon = slot.kind == "weapon"
    return ItemProfile(
        name=name,
        description=description,
        kind=slot.kind,
        status=slot.rarity,
        attribute=attribute if weapon else "str",
        base_dice="1d4" if weapon and attribute == "dex" else "1d6",
        attack_bonus=tier // 2 if weapon else 0,
        damage_bonus=tier - tier // 2 if weapon else 0,
        defense_bonus=1 + tier if slot.kind == "armor" else 0,
        restore_pool="hp" if slot.kind == "consumable" else None,
        restore_amount=RESTORE[tier],
    )


def loot_state(slot: LootSlot, profile: ItemProfile, *, seller_id: str | None = None) -> dict:
    """What a find or a piece of stock keeps beside its profile: how hard it is to take, or what it costs."""
    if seller_id:
        return dict(loot=profile.model_dump(mode="json"), price=PRICE[slot.rarity], seller_id=seller_id)
    return dict(loot=profile.model_dump(mode="json"), take_difficulty=TAKE_DIFFICULTY[slot.rarity])


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
        rarity=ItemProfile.model_validate(row.state["loot"]).status,
        **({"take_difficulty": row.state["take_difficulty"]} if row.state.get("take_difficulty") else {}),
        **({"price": row.state["price"], "seller_id": row.state["seller_id"]} if row.state.get("price") else {}),
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


def check_purchase(row, actor) -> int:
    """The price of a piece of stock, and a refusal if the hero cannot pay it or the seller is out of the picture."""
    price = int(row.state.get("price") or 0)
    if not price:
        return 0
    from app.core.universal.purse import coins_of
    from app.rules.universal.failures import ActionValidationError

    if coins_of(actor) < price:
        raise ActionValidationError("not_enough_coins")
    return price


async def pick_up(ctx, row, source_event, index):
    from app.core.universal.inventory import create_item
    from app.core.universal.purse import coins_of, set_coins
    from app.db.models import Character, Entity
    from app.rules.universal.exploration import EffectChange

    actor = await ctx.session.get(Character, ctx.actor_id)
    available_loot(row, actor)
    price = check_purchase(row, actor)
    if price:
        seller = await ctx.session.get(Entity, row.state.get("seller_id"))
        if seller is None or seller.location_id != actor.location_id or seller.state.get("hostile"):
            raise ValueError("Торговца нет рядом")
        set_coins(actor, coins_of(actor) - price)
    item = await create_item(
        ctx.session,
        ctx.campaign_id,
        ctx.actor_id,
        ItemProfile.model_validate(row.state["loot"]),
        f"loot:{row.id}",
    )
    row.location_id = None
    row.state = {**row.state, "taken_by": ctx.actor_id}
    bought = f" Куплено за {price} монет." if price else ""
    return EffectChange(kind="item_taken", subject_id=item.id, description=f"«{item.name}» теперь у героя.{bought}")
