import asyncio

import pytest

from app.core.universal.profiles import load_actor
from app.core.universal.progression import award_xp
from app.rules.universal.progression import allocate_points, grant_xp, level_for_xp, level_threshold
from tests.test_universal_resolution import setup, sheet


def test_thresholds_huge_exact_budget_and_allocation():
    assert level_threshold(21) == 410000 and level_threshold(100) == 20555000
    level = 10**30
    assert level_for_xp(level_threshold(level)) == level
    grown = grant_xp(sheet(), level_threshold(10))
    assert grown.level == 10 and grown.unspent_points == 18
    allocated = allocate_points(grown, {"wis": 18})
    assert allocated.abilities.wis == 32 and allocated.unspent_points == 0
    with pytest.raises(ValueError):
        allocate_points(allocated, {"wis": 1})
    for bad in [-1, True, 1.5]:
        with pytest.raises(ValueError):
            grant_xp(sheet(), bad)


def test_equal_full_awards_and_replay_binding(tmp_path):
    from app.core.campaigns import Conflict

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ids = await award_xp(s, "c", "achievement", ["hero", "target"], 300)
            assert set(ids) == {"hero", "target"}
            for aid in ids:
                sh, _ = await load_actor(s, "c", aid)
                assert sh.xp == 300 and sh.level == 2 and sh.budget.growth_total == 2
            await award_xp(s, "c", "achievement", ["target", "hero"], 300)
            assert (await load_actor(s, "c", "hero"))[0].xp == 300
            with pytest.raises(Conflict):
                await award_xp(s, "c", "achievement", ["hero"], 300)
            with pytest.raises(ValueError):
                await award_xp(s, "c", "dup", ["hero", "hero"], 300)
        await engine.dispose()

    asyncio.run(run())


def test_award_foreign_recipient_rolls_back_and_concurrent_replay_is_once(tmp_path):
    from app.core.campaigns import AccessDenied

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            with pytest.raises(AccessDenied):
                await award_xp(s, "c", "bad", ["hero", "foreign"], 300)
            assert (await load_actor(s, "c", "hero"))[0].xp == 0
            await s.commit()

        async def invoke():
            async with maker() as s:
                await award_xp(s, "c", "huge", ["hero"], 2**60)
                await s.commit()

        await asyncio.gather(invoke(), invoke())
        async with maker() as s:
            sh, _ = await load_actor(s, "c", "hero")
            assert sh.xp == 2**60 and sh.level > 1000
            assert sh.model_dump(mode="json")["xp"] == str(2**60)
            assert sh.budget.growth_total == 2 * (sh.level - 1)
        await engine.dispose()

    asyncio.run(run())
