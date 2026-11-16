import asyncio

from sqlalchemy import func, select

from app.core.universal.attempts import approach_closed, close_approach, closed_approaches
from app.db.models import AttemptLock
from tests.test_universal_master import prepare
from tests.test_universal_resolution import setup


def run(tmp_path, scenario):
    async def go():
        engine, maker = await setup(tmp_path)
        try:
            await prepare(maker)
            async with maker() as s:
                await scenario(s)
        finally:
            await engine.dispose()

    asyncio.run(go())


def test_a_closed_approach_is_remembered(tmp_path):
    async def scenario(s):
        assert not await approach_closed(s, "c", "door", "dex")
        await close_approach(s, "c", "door", "dex", "hero", "ev1")
        assert await approach_closed(s, "c", "door", "dex")
        assert not await approach_closed(s, "c", "door", "str")

    run(tmp_path, scenario)


def test_close_approach_is_idempotent(tmp_path):
    async def scenario(s):
        await close_approach(s, "c", "door", "dex", "hero", "ev1")
        await close_approach(s, "c", "door", "dex", "hero", "ev1")
        await s.commit()
        assert await s.scalar(select(func.count()).select_from(AttemptLock)) == 1

    run(tmp_path, scenario)


def test_closed_approaches_lists_only_the_asked_targets(tmp_path):
    async def scenario(s):
        await close_approach(s, "c", "door", "dex", "hero", "ev1")
        await close_approach(s, "c", "guard", "cha", "hero", "ev2")
        await close_approach(s, "c", "elsewhere", "str", "hero", "ev3")
        assert await closed_approaches(s, "c", ["door", "guard"]) == [
            {"target_id": "door", "attribute": "dex"},
            {"target_id": "guard", "attribute": "cha"},
        ]

    run(tmp_path, scenario)
