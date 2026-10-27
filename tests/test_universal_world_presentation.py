import asyncio
import json
from copy import deepcopy

from app.agents.master.service import MasterService
from app.agents.master.world import prepare_scene
from app.core.universal.orientation_generation import ensure_map
from app.core.universal.world_generation import entity_id
from app.db.models import Campaign, Character, Entity, MasterTurn, Message, Seat
from app.rules.dice import FixedDice
from tests.test_universal_master import Bus, Provider
from tests.test_universal_world_exploration import entry, source, travel, tunnel
from tests.test_universal_world_generation import scene_plan, world_setup


def test_prepared_props_refresh_markers_without_replacing_saved_geometry(tmp_path):
    async def run():
        engine, maker = await world_setup(tmp_path)
        async with maker() as s:
            c = await s.get(Campaign, "c")
            await ensure_map(s, "c", "gorge")
            before = deepcopy((await s.get(Entity, "gorge")).state["sketch"])
            await s.commit()
        await prepare_scene(MasterService(maker, Bus(), Provider([scene_plan(), {"verdict": "pass"}])), c, None, "gorge")
        async with maker() as s:
            after = (await s.get(Entity, "gorge")).state["sketch"]
            assert {k: v for k, v in before.items() if k != "features"} == {
                k: v for k, v in after.items() if k != "features"
            }
            assert any(f.get("entity_id") == entity_id("c", "gorge", "object:cart") for f in after["features"])
            assert "PRIVATE" not in str(after)
        await engine.dispose()

    asyncio.run(run())


def test_narration_never_adds_a_new_destination_bystander_to_original_audience(tmp_path):
    from app.agents.master.public_context import scene_audience

    async def run():
        engine, maker = await world_setup(tmp_path)
        async with maker() as s:
            s.add(Seat(id="second", campaign_id="c", role="player", position=2, user_id="u", occupant_type="human"))
            await s.flush()
            other = await s.get(Character, "target")
            other.seat_id, other.location_id = "second", "gorge"
            scene = {"location": {"id": "gorge"}}
            assert await scene_audience(s, "c", ["seat"], scene) == ["seat"]
            assert await scene_audience(s, "c", ["absent"], scene) == []
        await engine.dispose()

    asyncio.run(run())


def test_traveller_receives_new_scene_but_bystanders_do_not(tmp_path):
    async def run():
        engine, maker = await world_setup(tmp_path)
        await source(maker)
        target = entity_id("c", "gorge", "place:tunnel")
        async with maker() as s:
            s.add(Seat(id="second", campaign_id="c", role="player", position=2, user_id="u", occupant_type="human"))
            await s.flush()
            other = await s.get(Character, "target")
            other.seat_id, other.location_id = "second", "gorge"
            await s.commit()
        provider = Provider([
            entry(), {"verdict": "pass"}, travel(target), {"verdict": "pass"},
            tunnel(), {"verdict": "pass"}, "Под сводом сверкает кристалл.", {"verdict": "pass"},
        ])
        tid = await MasterService(maker, Bus(), provider, dice_factory=lambda: FixedDice([])).run_turn("c")
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "done", turn.trace
            assert turn.trace["audience"] is None
            assert turn.trace["narration_audience"] == ["seat"]
            assert turn.trace["public_context"]["scene"]["location"]["id"] == target
            assert "Кристалл" in str(turn.trace["public_context"])
            m = await s.get(Message, turn.narration_message_id)
            assert m.visible_to == ["seat"]
            assert (await s.get(Character, "target")).location_id == "gorge"
            assert "Кристалл" in json.dumps(provider.prompts[-2], ensure_ascii=False)
        await engine.dispose()

    asyncio.run(run())
