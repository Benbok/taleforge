import asyncio

from app.agents.master.prompting.context import build_decide_context
from app.db.models import Campaign, Character, Seat
from tests.test_universal_resolution import setup


def test_build_decide_context_has_the_same_keys_as_before(tmp_path, monkeypatch):
    async def history(session, campaign, upto_seq, audience, scene):
        # PostgreSQL stores Message.seq as int32; an int64 sentinel cannot bind.
        assert upto_seq == 0
        return []

    monkeypatch.setattr("app.agents.master.prompting.context.recent_history", history)

    async def run():
        engine, maker = await setup(tmp_path)
        try:
            async with maker() as session:
                context = await build_decide_context(
                    session,
                    await session.get(Campaign, "c"),
                    await session.get(Character, "hero"),
                    await session.get(Seat, "seat"),
                    "иду",
                )
                assert set(context) == {
                    "world_development",
                    "world",
                    "world_rules",
                    "hero",
                    "resources",
                    "scene",
                    "history",
                    "source",
                    "established_evidence",
                    "objects",
                    "inventory",
                    "known_exits",
                    "constraints",
                    "active_effects",
                    "known_abilities",
                }
                assert context["source"] == "иду"
        finally:
            await engine.dispose()

    asyncio.run(run())
