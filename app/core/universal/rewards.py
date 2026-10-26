"""Reward only saved, realized achievements, once per subject and campaign."""

from sqlalchemy import select

from app.core.universal.progression import award_xp, party_level, receipt_key
from app.core.universal.visibility import visible_entity
from app.db.models import Character, Entity, Event
from app.rules.universal.exploration import EffectChange
from app.rules.universal.progression import RewardIntent

AWARD_BASE = {"easy": 75, "medium": 150, "hard": 300, "epic": 600}


async def award_achievements(ctx, action, outcome, *, reward_level=None):
    if not outcome.success:
        return []
    s = ctx.session
    reward_level = reward_level if reward_level is not None else await party_level(s, ctx.campaign_id)
    hero = await s.get(Character, action.actor_id)
    event = await s.scalar(
        select(Event).where(Event.campaign_id == ctx.campaign_id, Event.idempotency_key == action.source_message_id)
    )
    if event is None or event.tool != "universal_action" or event.actor_id != hero.id:
        return []
    proposals = [action.reward] if action.reward else []
    if not proposals:
        # UI weapon attacks also complete victories; no extra model call is required.
        for change in outcome.changes:
            if change.kind == "damage":
                proposals.append(
                    RewardIntent(category="victory", subject_id=change.subject_id, reason="Победа над противником")
                )
    changes = []
    for reward in proposals:
        subject = await s.get(Entity, reward.subject_id)
        if (
            subject is None
            or subject.campaign_id != ctx.campaign_id
            or not await visible_entity(s, ctx.campaign_id, hero.id, subject)
        ):
            continue
        if subject.location_id != hero.location_id and subject.id != hero.location_id:
            continue
        saved = event.payload.get("outcome", {})
        facts = saved.get("changes", [])
        if reward.category == "victory":
            valid = (
                subject.kind == "creature"
                and subject.state.get("hostile")
                and int(subject.state.get("resources", {}).get("hp", "1")) == 0
                and any(
                    c["kind"] == "damage"
                    and c["subject_id"] == subject.id
                    and int(c.get("data", {}).get("amount", "0")) > 0
                    for c in facts
                )
            )
        elif reward.category == "exploration":
            valid = subject.kind == "location" and any(
                c["kind"] == "observation" and c["subject_id"] == subject.id for c in facts
            )
        else:
            valid = (
                subject.kind == "quest"
                and subject.state.get("completed") is True
                and any(c["subject_id"] == subject.id for c in facts)
            )
        if not valid:
            continue
        source = f"achievement:{reward.category}:{subject.id}"
        previous = await s.scalar(
            select(Event.id).where(
                Event.campaign_id == ctx.campaign_id, Event.idempotency_key == receipt_key("xp", source)
            )
        )
        if previous:
            continue
        recipients = [
            row.id
            for row in await s.scalars(
                select(Character).where(
                    Character.campaign_id == ctx.campaign_id,
                    Character.location_id == hero.location_id,
                    Character.status.in_(["active", "approved"]),
                    Character.seat_id.is_not(None),
                )
            )
        ]
        recipients = [aid for aid in recipients if not (await s.get(Character, aid)).resources.get("admission_pending")]
        if not recipients:
            continue
        amount = AWARD_BASE[reward.difficulty] * reward_level
        await award_xp(s, ctx.campaign_id, source, recipients, amount, reason=reward.reason)
        changes.append(
            EffectChange(
                kind="xp_awarded",
                subject_id=hero.id,
                description=f"{reward.reason}: каждый участник получает {amount} XP.",
                data=dict(amount=str(amount), actor_ids=recipients, category=reward.category),
            )
        )
    return changes


async def award_periodic_victories(ctx, exchange, *, reward_level=None):
    """Clock damage has independent saved evidence, even when the current action failed."""
    import hashlib

    from app.db.models import UniversalEffect, UniversalStep

    source_keys = [
        exchange.source_key,
        *["world-" + hashlib.sha256(f"{exchange.source_key}:{index}".encode()).hexdigest()[:40] for index in range(6)],
    ]
    s = ctx.session
    reward_level = reward_level if reward_level is not None else await party_level(s, ctx.campaign_id)
    observer = await s.get(Character, ctx.actor_id)
    changes = []
    steps = await s.scalars(
        select(UniversalStep).where(
            UniversalStep.campaign_id == ctx.campaign_id, UniversalStep.source_key.in_(source_keys)
        )
    )
    for step in steps:
        for fact in step.changes:
            if fact["kind"] != "periodic_damage" or int(fact.get("data", {}).get("amount", "0")) < 1:
                continue
            effect = await s.get(UniversalEffect, fact["data"].get("effect_id"))
            if effect is None or effect.campaign_id != ctx.campaign_id or effect.target_id != fact["subject_id"]:
                continue
            source = await s.get(Character, effect.source_actor_id)
            foe = await s.get(Entity, effect.target_id)
            if (
                source is None
                or source.campaign_id != ctx.campaign_id
                or source.resources.get("admission_pending")
                or source.status not in {"active", "approved"}
            ):
                continue
            if (
                foe is None
                or foe.campaign_id != ctx.campaign_id
                or not foe.state.get("hostile")
                or int(foe.state.get("resources", {}).get("hp", "1")) > 0
            ):
                continue
            key = f"achievement:victory:{foe.id}"
            if await s.scalar(
                select(Event.id).where(
                    Event.campaign_id == ctx.campaign_id, Event.idempotency_key == receipt_key("xp", key)
                )
            ):
                continue
            candidates = list(
                await s.scalars(
                    select(Character).where(
                        Character.campaign_id == ctx.campaign_id,
                        Character.status.in_(["active", "approved"]),
                        Character.seat_id.is_not(None),
                    )
                )
            )
            recipients = [
                hero.id
                for hero in candidates
                if not hero.resources.get("admission_pending")
                and (hero.location_id == foe.location_id or hero.id == source.id)
            ]
            if not recipients:
                continue
            amount = AWARD_BASE["medium"] * reward_level
            await award_xp(s, ctx.campaign_id, key, recipients, amount, reason="Победа над противником")
            visible = observer.location_id == foe.location_id and await visible_entity(
                s, ctx.campaign_id, observer.id, foe
            )
            changes.append(
                EffectChange(
                    kind="xp_awarded",
                    subject_id=source.id,
                    private=not visible,
                    description=f"Победа над противником: каждый участник получает {amount} XP.",
                    data=dict(amount=str(amount), actor_ids=recipients, category="victory", step_id=step.id),
                )
            )
    return changes
