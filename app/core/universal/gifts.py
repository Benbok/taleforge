"""Подарки существам и однократный бонус к убеждению."""

from app.core.campaigns import AccessDenied
from app.core.universal.inventory import _owned, state_of, store
from app.db.models import Entity
from app.rules.universal.exploration import EffectChange

GIFT_BONUS = {"common": 2, "rare": 3, "unique": 4, "epic": 4}
GIFT_BONUS_CAP = 4


async def validate_gift(ctx, item_id, recipient_id):
    try:
        actor, row, item = await _owned(ctx.session, ctx.campaign_id, ctx.actor_id, item_id)
    except AccessDenied as exc:
        raise ValueError("Нельзя подарить чужой или недоступный предмет") from exc
    creature = await ctx.session.get(Entity, recipient_id or "", populate_existing=True)
    if (
        creature is None
        or creature.campaign_id != ctx.campaign_id
        or creature.kind != "creature"
        or creature.location_id != actor.location_id
        or creature.state.get("hostile")
        or creature.state.get("hidden")
        or creature.state.get("secret")
        or creature.state.get("visibility") in {"hidden", "private"}
    ):
        raise ValueError("Подарок можно передать только невраждебному существу в той же сцене")
    if item.equipped:
        raise ValueError("Сначала сними предмет, чтобы подарить его")
    return row, creature


async def give_item_to_creature(ctx, item_row, creature_row, source_event, index):
    item_row, creature_row = await validate_gift(ctx, item_row.id, creature_row.id)
    item = state_of(item_row)
    store(item_row, item.model_copy(update={"quantity": 0}))
    creature_row.state = {
        **creature_row.state,
        "gifts": [*creature_row.state.get("gifts", []), item.profile.name],
    }
    return EffectChange(
        kind="item_given",
        subject_id=creature_row.id,
        description=f"«{item.profile.name}» передан: {creature_row.name}.",
    )


async def gift_bonus(ctx, action) -> int:
    if action.resolution != "check" or not any(op.kind == "speak" for op in action.operations):
        return 0
    total = 0
    seen = set()
    for op in action.operations:
        if op.kind != "give" or not op.object_id or op.object_id in seen:
            continue
        seen.add(op.object_id)
        row, _ = await validate_gift(ctx, op.object_id, op.recipient_id)
        total += GIFT_BONUS[state_of(row).profile.status]
    return min(total, GIFT_BONUS_CAP)
