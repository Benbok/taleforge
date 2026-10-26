import asyncio
import json

from sqlalchemy import select

from app.agents.master.service import MasterService
from app.core.universal.exploration_resolution import resolve_exploration
from app.core.universal.resolution import ResolutionContext
from app.db.models import UniversalJournal
from app.rules.dice import FixedDice
from tests.test_exploration_creatures import free_effect, puppet
from tests.test_exploration_master import bridge
from tests.test_exploration_resolution import build
from tests.test_universal_master import Bus, Provider, prepare
from tests.test_universal_resolution import setup


async def entries(s):
    return [(j.kind, j.source_key) for j in await s.scalars(select(UniversalJournal).order_by(UniversalJournal.kind))]


def test_free_effects_and_created_beings_are_journaled_once_with_the_players_words(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            effect, _ = await build(ctx, s, free_effect())
            await build(ctx, s, puppet(), "m2", 2)
            assert await entries(s) == [("creature", "m2"), ("free_effect", "m")]
            row = await s.scalar(select(UniversalJournal).where(UniversalJournal.kind == "free_effect"))
            assert row.source_text == "Строю" and row.detail["label"] == "Скелеты в тоннеле остановлены"
            await resolve_exploration(ctx, effect, "m")  # a replay writes nothing new
            assert len(await entries(s)) == 2
        await engine.dispose()

    asyncio.run(run())


def test_forbidden_requests_are_journaled_so_the_worlds_limits_can_be_seen(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Provider(
            [
                bridge("large"),
                {"verdict": "forbidden", "message": "Так в этом мире не бывает."},
                "Нет.",
                {"verdict": "pass"},
            ]
        )
        await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            kinds = [kind for kind, _ in await entries(s)]
            assert kinds == ["forbidden"]
            row = await s.scalar(select(UniversalJournal))
            assert "не бывает" in json.dumps(row.detail, ensure_ascii=False)
        await engine.dispose()

    asyncio.run(run())
