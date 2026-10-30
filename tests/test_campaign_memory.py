import asyncio

from app.agents import memory
from app.agents.master.prompting.context import build_decide_context
from app.agents.master.prompting.modules import compose_system
from app.agents.master.service import MasterService
from app.db.models import Campaign, Character, Seat, Summary
from tests.test_universal_master import Bus, Provider
from tests.test_universal_resolution import setup

CONTENT = {
    "quests": ["Найти пропавшего сына мельника"],
    "events": [f"Событие {i}: " + "x" * 80 for i in range(30)],
    "npcs": [{"name": f"Житель {i}", "relation": "торговец", "note": "y" * 150} for i in range(30)],
    "threads": ["Кто поджёг мельницу"],
    "promises": ["Герой обещал вернуть долг трактирщику"],
    "recap": "Герои пришли в деревню.",
}


def test_render_for_model_fits_the_budget_and_keeps_what_happened_first():
    text = memory.render_for_model(CONTENT, 1500)
    assert len(text) <= 1500
    assert text.startswith("Что было")
    assert "Событие 29" in text  # the newest events survive, the oldest are what gets cut


def test_render_for_model_of_nothing_is_empty():
    assert memory.render_for_model(None, 1500) == ""
    assert memory.render_for_model({}, 1500) == ""


def test_decision_context_carries_the_campaign_summary_only_when_there_is_one(tmp_path, monkeypatch):
    async def history(session, campaign, upto_seq, audience, scene):
        return []

    monkeypatch.setattr("app.agents.master.prompting.context.recent_history", history)

    async def build(session):
        return await build_decide_context(
            session,
            await session.get(Campaign, "c"),
            await session.get(Character, "hero"),
            await session.get(Seat, "seat"),
            "иду",
        )

    async def run():
        engine, maker = await setup(tmp_path)
        try:
            async with maker() as session:
                assert "campaign_memory" not in await build(session)
                session.add(Summary(campaign_id="c", kind="rolling", version=1, upto_seq=1, content=CONTENT))
                await session.commit()
                context = await build(session)
            assert "Найти пропавшего сына мельника" in context["campaign_memory"]
            assert len(context["campaign_memory"]) <= memory.MODEL_MEMORY_LIMIT
        finally:
            await engine.dispose()

    asyncio.run(run())


def test_the_prompt_says_where_old_events_come_from_and_where_quotes_do_not():
    system = compose_system({"campaign_memory": "x"})
    assert "campaign_memory" in system
    assert "не цитируй" in system.split("campaign_memory", 1)[1][:300]


def test_a_finished_turn_asks_for_a_rolling_summary(tmp_path, monkeypatch):
    async def turn(service, cid, place=None):
        return "turn-id"

    monkeypatch.setattr("app.agents.master.universal.run_universal_turn", turn)

    async def run():
        engine, maker = await setup(tmp_path)
        try:
            service = MasterService(maker, Bus(), Provider([]))
            asked = []
            service.schedule_summary = lambda cid, kind="rolling", session_id=None: asked.append((cid, kind))
            assert await service._run_turn("c") == "turn-id"
            assert asked == [("c", "rolling")]
        finally:
            await engine.dispose()

    asyncio.run(run())
