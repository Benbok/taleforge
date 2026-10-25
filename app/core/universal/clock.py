"""One exact, receipt-safe clock for exploration and future combat exchanges."""

from sqlalchemy import select, update

from app.core.campaigns import Conflict, NotFound
from app.db.models import Campaign, UniversalClock, UniversalStep


async def lock_campaign(session, campaign_id):
    result = await session.execute(
        update(Campaign).where(Campaign.id == campaign_id).values(world_revision=Campaign.world_revision)
    )
    if not result.rowcount:
        raise NotFound("Campaign not found")


async def clock_view(session, campaign_id):
    clock = await session.get(UniversalClock, campaign_id, populate_existing=True)
    return dict(game_seconds=clock.game_seconds if clock else "0", step_index=clock.step_index if clock else "0")


async def complete_step(session, campaign_id, source_key, elapsed_seconds, *, dice=None):
    async with session.begin_nested():
        return await _complete_step(session, campaign_id, source_key, elapsed_seconds, dice=dice)


async def _complete_step(session, campaign_id, source_key, elapsed_seconds, *, dice=None):
    if type(elapsed_seconds) is not int or elapsed_seconds < 0 or not source_key or len(source_key) > 128:
        raise ValueError("Invalid game step")
    await lock_campaign(session, campaign_id)
    previous = await session.scalar(
        select(UniversalStep).where(UniversalStep.campaign_id == campaign_id, UniversalStep.source_key == source_key)
    )
    if previous is not None:
        if int(previous.elapsed_seconds) != elapsed_seconds:
            raise Conflict("Saved game step cannot change its elapsed time")
        return previous
    clock = await session.get(UniversalClock, campaign_id, populate_existing=True)
    if clock is None:
        clock = UniversalClock(campaign_id=campaign_id, game_seconds="0", step_index="0")
        session.add(clock)
    start, sequence = int(clock.game_seconds), int(clock.step_index) + 1
    end = start + elapsed_seconds
    clock.game_seconds, clock.step_index = str(end), str(sequence)
    from app.core.universal.effects import expire_effects
    from app.core.universal.periodic import advance_periodic
    from app.core.universal.vitality import advance_vitality

    changes = await advance_periodic(session, campaign_id, start, end, sequence, dice)
    changes.extend(await advance_vitality(session, campaign_id, sequence, dice))
    changes.extend(await expire_effects(session, campaign_id, end))
    from app.core.universal.regeneration import regenerate_energy

    await regenerate_energy(session, campaign_id, elapsed_seconds)
    step = UniversalStep(
        campaign_id=campaign_id,
        source_key=source_key,
        sequence=str(sequence),
        started_seconds=str(start),
        ended_seconds=str(end),
        elapsed_seconds=str(elapsed_seconds),
        changes=[change.model_dump(mode="json") for change in changes],
    )
    session.add(step)
    await session.flush()
    return step
