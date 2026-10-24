"""Discovery records only completely realized, admitted abilities.

Composite policy: every intended numeric component on every intended target must
actually realize. A hit resisted in part remains a paid hit, but teaches nothing.
"""

from sqlalchemy import select

from app.core.campaigns import AccessDenied
from app.core.universal.profiles import get_profile
from app.db.models import Character, Event, HeroAbility


async def learned_abilities(session, character_id):
    rows = (
        await session.scalars(
            select(HeroAbility)
            .where(HeroAbility.character_id == character_id)
            .order_by(HeroAbility.created_at, HeroAbility.id)
        )
    ).all()
    return [
        dict(
            id=r.id,
            name=r.name,
            profile_ref=r.profile_ref,
            profile_revision=str(r.profile_revision),
            profile=r.definition,
            source_event_id=r.source_event_id,
        )
        for r in rows
    ]


async def record_realized_ability(session, character_id, proposal, outcome, event_id):
    profile = proposal.profile
    if (
        outcome.status != "applied"
        or not outcome.success
        or profile.kind == "narrative"
        or profile.use_kind != "ability"
        or profile.kind == "check"
        and profile.resource_key is None
    ):
        return None
    required = {e.id for e in profile.effects if e.kind != "narrative"}
    if profile.kind in {"damage", "heal", "check"}:
        required.add("primary")
    actual = {(e.target_id, e.effect_id): e.applied for e in outcome.effect_outcomes}
    targets = proposal.targets or [character_id]
    if any(not actual.get((target, effect), False) for target in targets for effect in required):
        return None
    hero = await session.get(Character, character_id)
    if hero is None or proposal.actor_id != character_id:
        raise AccessDenied("discovery actor mismatch")
    admitted = await get_profile(session, hero.campaign_id, profile.id, profile.revision)
    event = await session.get(Event, event_id)
    if (
        admitted != profile
        or event is None
        or event.actor_id != character_id
        or event.campaign_id != hero.campaign_id
        or event.tool != "universal_action"
    ):
        raise AccessDenied("discovery requires a saved admitted outcome")
    if event.payload.get("outcome") != outcome.model_dump(mode="json") or event.payload.get(
        "proposal"
    ) != proposal.model_dump(mode="json"):
        raise AccessDenied("discovery outcome does not match saved receipt")
    existing = await session.scalar(
        select(HeroAbility).where(HeroAbility.character_id == character_id, HeroAbility.profile_ref == profile.id)
    )
    if existing:
        return existing
    ability = HeroAbility(
        character_id=character_id,
        campaign_id=hero.campaign_id,
        profile_ref=profile.id,
        profile_revision=profile.revision,
        name=(proposal.reason.strip() or profile.id)[:128],
        definition=profile.model_dump(mode="json"),
        source_event_id=event_id,
    )
    session.add(ability)
    await session.flush()
    hero.resources = {**hero.resources, "learned_abilities": await learned_abilities(session, character_id)}
    return ability
