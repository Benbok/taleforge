"""Exact scheduled damage on the shared game clock, before expiry and rescue rolls."""

from sqlalchemy import select

from app.core.universal.profiles import load_actor, save_actor
from app.core.universal.vitality import enter_zero_hp
from app.db.models import UniversalEffect
from app.rules.universal.contracts import UniversalSheet
from app.rules.universal.exploration import EffectChange
from app.rules.universal.profiles import ProfileSpec, damage_amount


async def advance_periodic(session, campaign_id, start, end, sequence, dice):
    changes = []
    for effect in await session.scalars(
        select(UniversalEffect).where(UniversalEffect.campaign_id == campaign_id, UniversalEffect.status == "active")
    ):
        if effect.definition["kind"] != "damage_over_time":
            continue
        begins, ends = int(effect.starts_seconds), int(effect.ends_seconds)
        first = max(0, (start - begins) // 6)
        last = max(0, (min(end, ends) - begins) // 6)
        if last <= first:
            continue
        if dice is None:
            raise ValueError("Периодическому урону нужен серверный источник кубиков")
        context = effect.definition.get("context", {})
        source_sheet = (
            UniversalSheet.model_validate(context["source_sheet"])
            if context.get("source_sheet")
            else (await load_actor(session, campaign_id, effect.source_actor_id))[0]
        )
        profile = ProfileSpec(
            id="periodic",
            kind="damage",
            attribute=context.get("attribute", "wis"),
            intensity=context.get("intensity", "normal"),
        )
        for _ in range(last - first):
            from app.core.universal.resolution import _RecordingDice

            recorded = _RecordingDice(dice)
            sheet, resources = await load_actor(session, campaign_id, effect.target_id)
            amount = damage_amount(recorded, source_sheet, profile)
            before = resources.hp
            resources.hp = max(0, before - amount)
            await save_actor(session, campaign_id, effect.target_id, sheet, resources)
            await enter_zero_hp(session, campaign_id, effect.target_id, effect.id, sequence)
            if before == 0 and amount > 0:
                from app.core.universal.vitality import harm_unconscious

                await harm_unconscious(session, campaign_id, effect.target_id, effect.id, sequence)
            changes.append(
                EffectChange(
                    kind="periodic_damage",
                    subject_id=effect.target_id,
                    description=f"Периодический эффект наносит {before - resources.hp} HP урона.",
                    data=dict(
                        amount=str(before - resources.hp),
                        effect_id=effect.id,
                        draws=[draw.model_dump(mode="json") for draw in recorded.draws],
                    ),
                )
            )
    return changes
