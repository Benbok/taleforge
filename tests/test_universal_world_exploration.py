import asyncio

import pytest
from sqlalchemy import func, select

from app.agents.master.service import MasterService
from app.core.chat import next_seq
from app.core.universal.clock import clock_view
from app.core.universal.world_generation import entity_id
from app.db.models import Campaign, Character, Entity, Event, MasterTurn, Message, WorldGenerationState
from app.rules.dice import FixedDice
from tests.test_universal_master import Bus, Provider
from tests.test_universal_world_generation import scene_plan, world_setup


def travel(destination=None, scope="between_locations"):
    return dict(
        schema_version=2,
        source="mundane",
        player_request="ordinary",
        resolution="automatic",
        effects=[dict(kind="move", destination_id=destination, travel_scope=scope)],
    )


async def source(maker, text="иду в туннель"):
    async with maker() as s:
        (await s.get(Message, "source")).content = text
        await s.commit()


def entry():
    return scene_plan(objects=[{"ref": "cart", "kind": "object", "name": "Обломок повозки", "template": "wood_source"}])


def tunnel():
    return scene_plan(
        description="Герой видит кристалл под низким сводом.",
        objects=[{"ref": "crystal", "kind": "object", "name": "Кристалл", "description": "Мутный камень."}],
        passages=[],
    )


def test_walk_prepares_destination_moves_once_and_return_reuses_both_rooms(tmp_path):
    async def run():
        engine, maker = await world_setup(tmp_path)
        await source(maker)
        destination = entity_id("c", "gorge", "place:tunnel")
        provider = Provider(
            [
                entry(),
                {"verdict": "pass"},
                travel(destination),
                {"verdict": "pass"},
                tunnel(),
                {"verdict": "pass"},
                "Под низким сводом поблёскивает кристалл.",
                {"verdict": "pass"},
            ]
        )
        service = MasterService(maker, Bus(), provider, dice_factory=lambda: FixedDice([]))
        tid = await service.run_turn("c")
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "done", turn.trace
            assert (await s.get(Character, "hero")).location_id == destination
            assert (await clock_view(s, "c"))["step_index"] == "1"
            assert await s.scalar(select(func.count()).select_from(WorldGenerationState)) == 2
            assert (await s.get(Entity, destination)).state["universal_scene"]["ready"]
            receipt = await s.scalar(select(Event).where(Event.idempotency_key == "source"))
            assert any(c["kind"] == "location_changed" for c in receipt.payload["outcome"]["changes"])
            s.add(
                Message(
                    id="return",
                    campaign_id="c",
                    session_id="game",
                    seat_id="seat",
                    author_user_id="u",
                    seq=await next_seq(s, "c"),
                    kind="action",
                    content="Возвращаюсь к повозкам.",
                )
            )
            await s.commit()
        back = Provider(
            [travel("gorge"), {"verdict": "pass"}, "Впереди знакомые обломки повозки.", {"verdict": "pass"}]
        )
        second = await MasterService(maker, Bus(), back, dice_factory=lambda: FixedDice([])).run_turn("c")
        async with maker() as s:
            assert (await s.get(MasterTurn, second)).status == "done"
            assert (await s.get(Character, "hero")).location_id == "gorge"
            assert (await clock_view(s, "c"))["step_index"] == "2"
            assert await s.scalar(select(func.count()).select_from(WorldGenerationState)) == 2
        assert len(back.prompts) == 4
        await engine.dispose()

    asyncio.run(run())


def test_new_session_prepares_entry_once_but_existing_intro_does_not_generate(tmp_path):
    from app.agents.master.universal_lifecycle import open_universal_session

    async def run():
        engine, maker = await world_setup(tmp_path)
        async with maker() as s:
            c = await s.get(Campaign, "c")
            c.settings = {**c.settings, "studio_entry_location_id": "gorge"}
            await s.commit()
        provider = Provider([entry(), {"verdict": "pass"}, "Добро пожаловать."])
        service = MasterService(maker, Bus(), provider)
        assert await open_universal_session(service, "c", "game")
        assert await open_universal_session(service, "c", "game")
        async with maker() as s:
            c = await s.get(Campaign, "c")
            message = await s.get(Message, c.settings["universal_intro_message_id"])
            assert "следы колёс" in message.content
            assert await s.scalar(select(func.count()).select_from(WorldGenerationState)) == 1
            assert await s.scalar(select(func.count()).select_from(Event)) == 0
        assert len(provider.prompts) == 3  # entry preparation, its review, the greeting
        await engine.dispose()

    asyncio.run(run())


def test_pending_and_blocked_destination_cannot_be_executed_directly(tmp_path):
    from app.agents.master.world import prepare_scene
    from app.core.universal.resolution import ResolutionContext
    from app.core.universal.travel import destination_view

    async def run():
        engine, maker = await world_setup(tmp_path)
        async with maker() as s:
            campaign = await s.get(Campaign, "c")
        await prepare_scene(
            MasterService(maker, Bus(), Provider([entry(), {"verdict": "pass"}])), campaign, None, "gorge"
        )
        target = entity_id("c", "gorge", "place:tunnel")
        async with maker() as s:
            ctx = ResolutionContext(s, "c", user_id="u", seat_id="seat", actor_id="hero", dice=FixedDice([]))
            with pytest.raises(ValueError, match="не подготовлено"):
                await destination_view(ctx, target)
            await destination_view(ctx, target, allow_unprepared=True)
            origin = await s.get(Entity, "gorge")
            origin.state = {**origin.state, "links": [{**p, "state": "blocked"} for p in origin.state["links"]]}
            with pytest.raises(ValueError, match="открытого пути"):
                await destination_view(ctx, target, allow_unprepared=True)
            assert (await s.get(Character, "hero")).location_id == "gorge"
        await engine.dispose()

    asyncio.run(run())


def test_destination_provider_failure_keeps_hero_and_time_then_recovers_same_action(tmp_path):
    async def run():
        engine, maker = await world_setup(tmp_path)
        await source(maker)
        destination = entity_id("c", "gorge", "place:tunnel")
        failed = Provider(
            [entry(), {"verdict": "pass"}, travel(destination), {"verdict": "pass"}, RuntimeError("offline")]
        )
        tid = await MasterService(maker, Bus(), failed, dice_factory=lambda: FixedDice([])).run_turn("c")
        async with maker() as s:
            assert (await s.get(MasterTurn, tid)).status == "failed"
            assert (await s.get(Character, "hero")).location_id == "gorge"
            assert (await clock_view(s, "c"))["step_index"] == "0"
            assert await s.scalar(select(func.count()).select_from(Event)) == 0
        retry = Provider([tunnel(), {"verdict": "pass"}, "Под сводом поблёскивает кристалл.", {"verdict": "pass"}])
        assert await MasterService(maker, Bus(), retry, dice_factory=lambda: FixedDice([])).run_turn("c") == tid
        async with maker() as s:
            assert (await s.get(MasterTurn, tid)).status == "done"
            assert (await s.get(Character, "hero")).location_id == destination
            assert (await clock_view(s, "c"))["step_index"] == "1"
            assert await s.scalar(select(func.count()).select_from(Event)) == 1
        await engine.dispose()

    asyncio.run(run())


def test_unresolved_crossing_does_not_fall_back_to_a_successful_free_note(tmp_path):
    async def run():
        from app.agents.master.world import prepare_scene

        engine, maker = await world_setup(tmp_path)
        await source(maker)
        async with maker() as s:
            campaign = await s.get(Campaign, "c")
        await prepare_scene(
            MasterService(maker, Bus(), Provider([entry(), {"verdict": "pass"}])), campaign, None, "gorge"
        )
        unresolved = travel(None, None)
        provider = Provider(
            [
                unresolved,
                unresolved,
                "Герой остаётся у повозок: направление перехода не определено.",
                {"verdict": "pass"},
            ]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "done", turn.trace
            outcome = turn.trace["outcomes"]["source"]
            assert outcome["failure"]["code"] == "travel_destination_required"
            assert (await s.get(Character, "hero")).location_id == "gorge"
            assert (await clock_view(s, "c"))["step_index"] == "0"
            assert await s.scalar(select(func.count()).select_from(Event)) == 0
        await engine.dispose()

    asyncio.run(run())
