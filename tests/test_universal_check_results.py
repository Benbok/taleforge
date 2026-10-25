import asyncio

import pytest
from sqlalchemy import select

from app.agents.master.service import MasterService
from app.core.campaigns import Viewer
from app.core.inspect import entity_card
from app.db.models import Campaign, Event, MasterTurn, Message, User
from app.rules.dice import FixedDice
from tests.test_universal_location_knowledge import place
from tests.test_universal_master import Bus, Provider, prepare, seed_legacy
from tests.test_universal_resolution import setup

CONSEQUENCES = {
    "success": "Из тёмного тоннеля впереди различим сухой костяной стук приближающихся шагов.",
    "failure": "Среди шорохов не удаётся разобрать источник звука.",
    "critical_success": "Стук шагов из тоннеля впереди различим особенно отчётливо, даже сквозь окружающий шум.",
    "critical_failure": "Шорохи отвлекают внимание: не удаётся определить ни направление, ни источник стука.",
}


@pytest.mark.parametrize("roll, branch", [(15, "success"), (5, "failure")])
def test_check_saves_selected_consequence_and_shows_it_even_if_narrator_repeats_intent(tmp_path, roll, branch):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await place(maker)
        proposal = dict(
            kind="ordinary_check",
            attribute="wis",
            difficulty=11,
            public_reason="Герой прислушивается к звукам.",
            check_outcomes=CONSEQUENCES,
        )
        await seed_legacy(maker, proposal)
        provider = Provider(["Герой прислушивается к звукам."])
        tid = await MasterService(maker, Bus(), provider, dice_factory=lambda: FixedDice([roll])).run_turn("c")
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "done", turn.trace
            event = await s.scalar(select(Event).where(Event.idempotency_key == "source"))
            assert event.payload["outcome"]["description"] == CONSEQUENCES[branch]
            assert event.payload["proposal"]["check_outcomes"] == CONSEQUENCES
            card = await s.scalar(select(Message).where(Message.kind == "roll"))
            assert card.data["universal_proof"]["description"] == CONSEQUENCES[branch]
            campaign = await s.get(Campaign, "c")
            viewer = Viewer(await s.get(User, "u"), campaign, next(x for x in campaign.seats if x.id == "seat"))
            assert CONSEQUENCES[branch] in (await entity_card(s, viewer, "gorge"))["heard"]
        assert CONSEQUENCES[branch] in provider.prompts[-1][-1]["content"]
        assert CONSEQUENCES["failure" if branch == "success" else "success"] not in provider.prompts[-1][-1]["content"]
        await engine.dispose()

    asyncio.run(run())


def test_missing_concrete_result_is_repaired_before_rolling(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        provider = Provider(
            [
                dict(
                    schema_version=2,
                    source="mundane",
                    player_request="ordinary",
                    resolution="check",
                    effects=[dict(kind="observe")],
                ),
                dict(
                    schema_version=2,
                    source="mundane",
                    player_request="ordinary",
                    resolution="check",
                    effects=[dict(kind="observe")],
                    check_outcomes=CONSEQUENCES,
                ),
                "Вы различаете шаги.",
                dict(verdict="pass"),
            ]
        )
        tid = await MasterService(maker, Bus(), provider, dice_factory=lambda: FixedDice([15])).run_turn("c")
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "done"
            assert turn.trace["proposal_attempts"]["source"] == 2
            assert len(list(await s.scalars(select(Event)))) == 1
        await engine.dispose()

    asyncio.run(run())


def test_narrator_restart_keeps_the_same_concrete_result_without_another_roll(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await seed_legacy(maker, dict(kind="ordinary_check", check_outcomes=CONSEQUENCES))
        first = Provider([RuntimeError("offline")])
        tid = await MasterService(maker, Bus(), first, dice_factory=lambda: FixedDice([15])).run_turn("c")
        await MasterService(maker, Bus(), Provider(["Вы слышите шаги."]), dice_factory=lambda: FixedDice([])).run_turn(
            "c"
        )
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "done"
            assert turn.trace["outcomes"]["source"]["description"] == CONSEQUENCES["success"]
            assert len(list(await s.scalars(select(Event)))) == 1
            assert len(list(await s.scalars(select(Message).where(Message.kind == "roll")))) == 1
        await engine.dispose()

    asyncio.run(run())


def test_check_result_links_are_limited_to_public_scene_references(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await place(maker)
        provider = Provider(
            [
                dict(
                    kind="ordinary_check",
                    check_outcomes={
                        "success": "В Серой Глотке слышен [[private-place|стук]].",
                        "failure": "Звук неразличим.",
                        "critical_success": "В Серой Глотке стук различим особенно отчётливо.",
                        "critical_failure": "Шум сбивает внимание: не удаётся определить направление звука.",
                    },
                ),
                "Вы слышите стук.",
            ]
        )
        await seed_legacy(maker, provider.replies.pop(0))
        await MasterService(maker, Bus(), provider, dice_factory=lambda: FixedDice([15])).run_turn("c")
        async with maker() as s:
            event = await s.scalar(select(Event))
            result = event.payload["outcome"]["description"]
            assert "private-place" not in result
            assert "[[gorge|Серой Глотке]]" in result
            campaign = await s.get(Campaign, "c")
            viewer = Viewer(await s.get(User, "u"), campaign, next(x for x in campaign.seats if x.id == "seat"))
            heard = (await entity_card(s, viewer, "gorge"))["heard"]
            assert "В Серой Глотке слышен стук." in heard
        await engine.dispose()

    asyncio.run(run())
