"""Authored worlds grow independently during play; library originals remain unchanged."""

import asyncio
from copy import deepcopy

from sqlalchemy import select

from app.agents.master.service import MasterService
from app.core.chat import active_session, next_seq
from app.core.universal.clock import clock_view
from app.db.models import Character, Entity, MasterTurn, Message, WorldGenerationState
from app.rules.dice import FixedDice
from tests.test_universal_first_adventure import first_adventure_scenario
from tests.test_universal_master import Bus, Provider
from tests.test_universal_world_exploration import travel


def test_authored_game_develops_place_enters_returns_and_preserves_other_game_and_library(
    client, root, settings, monkeypatch
):
    cid, other_cid, hero_id, library = first_adventure_scenario(client, root, settings, monkeypatch)
    maker = client.app.state.sessionmaker

    async def run():
        async with maker() as s:
            hero = await s.get(Character, hero_id)
            origin = hero.location_id
            entry = await s.get(Entity, origin)
            assert len(entry.state["links"]) == 1
            destination = entry.state["links"][0]["to"]
            assert not (await s.get(Entity, destination)).state["universal_scene"]["ready"]
            here = list(await s.scalars(select(Entity).where(Entity.campaign_id == cid, Entity.location_id == origin)))
            assert any(e.kind == "creature" and e.name == "Смотритель причала" for e in here)
            assert any(e.name == "Обломок повозки" for e in here)
            other_before = [
                (e.id, deepcopy(e.state), e.description)
                for e in await s.scalars(select(Entity).where(Entity.campaign_id == other_cid).order_by(Entity.id))
            ]
            before_clock = await clock_view(s, cid)
            game = await active_session(s, cid)
            s.add(
                Message(
                    id="go-quay",
                    campaign_id=cid,
                    session_id=game.id,
                    seat_id=hero.seat_id,
                    author_user_id=hero.owner_user_id,
                    seq=await next_seq(s, cid),
                    kind="action",
                    content="Иду на причал.",
                )
            )
            await s.commit()
        provider = Provider(
            [
                travel(destination),
                {"verdict": "pass"},
                dict(
                    name="Причал",
                    description="Вода тихо плещется под досками причала.",
                    objects=[dict(ref="bollard", kind="object", name="Швартовный столб")],
                    passages=[],
                ),
                {"verdict": "pass"},
                "Под ногами скрипят доски, из-под них слышен плеск воды.",
                {"verdict": "pass"},
            ]
        )
        tid = await MasterService(maker, Bus(), provider, dice_factory=lambda: FixedDice([])).run_turn(cid)
        async with maker() as s:
            assert (await s.get(MasterTurn, tid)).status == "done"
            hero = await s.get(Character, hero_id)
            assert hero.location_id == destination
            assert int((await clock_view(s, cid))["step_index"]) == int(before_clock["step_index"]) + 1
            s.add(
                Message(
                    id="go-back",
                    campaign_id=cid,
                    session_id=game.id,
                    seat_id=hero.seat_id,
                    author_user_id=hero.owner_user_id,
                    seq=await next_seq(s, cid),
                    kind="action",
                    content="Возвращаюсь к воротам.",
                )
            )
            await s.commit()
        back = Provider([travel(origin), {"verdict": "pass"}, "Впереди знакомые ворота гавани.", {"verdict": "pass"}])
        await MasterService(maker, Bus(), back, dice_factory=lambda: FixedDice([])).run_turn(cid)
        assert len(back.prompts) == 4  # No second generation of either saved place.
        async with maker() as s:
            assert (await s.get(Character, hero_id)).location_id == origin
            rows = list(await s.scalars(select(WorldGenerationState).where(WorldGenerationState.campaign_id == cid)))
            assert len(rows) == 2 and all(row.status == "ready" for row in rows)
            assert not list(
                await s.scalars(select(WorldGenerationState).where(WorldGenerationState.campaign_id == other_cid))
            )
            assert [
                (e.id, e.state, e.description)
                for e in await s.scalars(select(Entity).where(Entity.campaign_id == other_cid).order_by(Entity.id))
            ] == other_before

    asyncio.run(run())
    assert client.get("/api/me/characters", headers=root).json() == library
