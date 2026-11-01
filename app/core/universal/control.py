"""Control that holds: no timer. The held one tries to break free every turn, on the ability the control was
resisted with; it ends too when the holder falls or is no longer at hand."""

from sqlalchemy import select

from app.core.universal.effects import _end
from app.core.universal.profiles import load_actor
from app.db.models import Character, Entity, UniversalEffect
from app.rules.universal.exploration import EffectChange
from app.rules.universal.profiles import resolve_check

CONTROL_KINDS = frozenset({"cannot_move", "cannot_act", "cannot_target"})
HOLD_SECONDS = 10**9  # a hold does not run out with time: only breaking free, the holder's fall or letting go ends it
INTENSITY_BONUS = {"light": 1, "normal": 2, "strong": 3}


def break_dc(holder_score: int, intensity: str) -> int:
    """10 + the holder's modifier on the ability they held with + the strength of the effect."""
    return 10 + (holder_score - 10) // 2 + INTENSITY_BONUS[intensity]


async def _actor(session, actor_id):
    return await session.get(Character, actor_id) or await session.get(Entity, actor_id)


async def _holder_lost(session, row):
    """The holder is down, dead or somewhere else: nobody holds the held one any more."""
    holder = await _actor(session, row.source_actor_id)
    target = await _actor(session, row.target_id)
    if holder is None or target is None or holder.location_id != target.location_id:
        return True
    try:
        _, resources = await load_actor(session, row.campaign_id, row.source_actor_id)
    except (ValueError, KeyError):
        return False
    from app.core.universal.vitality import public_vitality

    return resources.hp <= 0 or public_vitality(holder) in {"dead", "unconscious", "stable"}


async def advance_control(session, campaign_id, sequence, dice):
    """Run once per saved game step: every hold gets its try (never in the turn it was put on)."""
    changes = []
    rows = list(
        await session.scalars(
            select(UniversalEffect).where(
                UniversalEffect.campaign_id == campaign_id, UniversalEffect.status == "active"
            )
        )
    )
    for row in rows:
        context = row.definition.get("context") or {}
        if row.definition["kind"] not in CONTROL_KINDS or not context.get("held"):
            continue
        if await _holder_lost(session, row):
            changes.extend(await _release(session, row, "released"))
            continue
        if dice is None or sequence <= int(context.get("from_sequence", 0)):
            continue
        sheet, _ = await load_actor(session, campaign_id, row.target_id)
        score = getattr(sheet.abilities, context.get("resist") or "con")
        if resolve_check(dice, score, False, int(context["break_dc"])).success:
            changes.extend(await _release(session, row, "released"))
    return changes


async def _release(session, row, status):
    changes = await _end(session, row, status)
    target = await _actor(session, row.target_id)
    name = target.name if target is not None else "Цель"
    return [
        EffectChange(
            kind="effect_released",
            subject_id=row.target_id,
            description=f"{name} освобождается от контроля.",
            data=dict(effect_id=row.id, effect_kind=row.definition["kind"]),
        ),
        *changes,
    ]
