# ruff: noqa: F811
from sqlalchemy import select

from app.core.authoring.contracts import InstanceOptions
from app.core.authoring.instances import instantiate_adventure
from app.core.geography.travel import travel_route
from app.db.models import Campaign, Character, Entity, Event, GeographyLink
from app.rules.dice import Dice
from app.tools.registry import execute
from app.tools.runtime import open_context
from tests.test_adventure_instances import published
from tests.test_authoring_validation import _prepared
from tests.test_world_generation import _fast_retry  # noqa: F401 — фикстура

OPTIONS = InstanceOptions(name="Игра", players=2, master={"type": "agent"})
ROUTE = "r_port_light"


async def setup_game(s, pid, cid):
    project, version, owner = await published(s, pid)
    receipt = await instantiate_adventure(s, owner, version, OPTIONS, "launch")
    game_id = receipt.campaign_id
    ents = list(await s.scalars(select(Entity).where(Entity.campaign_id == game_id)))
    by_name = {e.name: e for e in ents}
    port, light = by_name["Старый храм"], by_name["Старый маяк"]
    areas = {
        "narthex": port.state["areas"]["narthex"],
        "nave": port.state["areas"]["nave"],
        "road": light.state["areas"]["road"],
    }
    await s.commit()
    return game_id, areas


async def hero(s, game_id, name, area_id):
    ch = Character(campaign_id=game_id, name=name, status="active", location_id=area_id)
    s.add(ch)
    await s.flush()
    return ch.id


async def context(s, game_id):
    return await open_context(s, await s.get(Campaign, game_id), Dice(seed=1), turn_id="t_travel", seat_id=None)


def test_route_travel_moves_atomically_both_ways_without_state_links(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            game, areas = await setup_game(s, pid, cid)
            h1 = await hero(s, game, "Бран", areas["narthex"])
            h2 = await hero(s, game, "Лис", areas["narthex"])
            await s.commit()
            ctx = await context(s, game)
            result = await travel_route(ctx, ROUTE, [h1, h2])
            assert result.failure_code is None and set(result.moved) == {h1, h2}
            assert (result.source_area_id, result.destination_area_id) == (areas["narthex"], areas["road"])
            assert {c.location_id for c in ctx.world.characters.values()} == {areas["road"]}
            event = ctx.events[-1]
            assert event.tool == "travel_route" and event.payload["route_id"] == ROUTE
            assert not any("links" in (e.state or {}) for e in ctx.world.entities.values())  # дорога не дублируется
            again = await travel_route(ctx, ROUTE, [h1, h2])  # возврат по двустороннему маршруту
            assert again.failure_code is None and again.destination_area_id == areas["narthex"]
            repeat = await travel_route(ctx, ROUTE, [h1, h2])  # снова вперёд из исходной точки
            assert repeat.failure_code is None and repeat.destination_area_id == areas["road"]

    _prepared_with(settings, body)


def _prepared_with(settings, body):
    from tests.test_authoring_validation import full_plan

    _prepared(settings, body, full_plan())


def test_wrong_room_split_party_and_unknown_route_do_not_move_anyone(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            game, areas = await setup_game(s, pid, cid)
            h1 = await hero(s, game, "Бран", areas["nave"])  # другая комната: обратная лестница не подходит
            h2 = await hero(s, game, "Лис", areas["narthex"])
            await s.commit()
            ctx = await context(s, game)
            assert (await travel_route(ctx, ROUTE, [h1])).failure_code == "not_at_port"
            assert (await travel_route(ctx, ROUTE, [h1, h2])).failure_code == "split_party_mismatch"
            assert (await travel_route(ctx, "no_such", [h2])).failure_code == "unknown_route"
            assert not ctx.events
            assert ctx.world.characters[h1].location_id == areas["nave"]
            assert ctx.world.characters[h2].location_id == areas["narthex"]

    _prepared_with(settings, body)


def test_one_way_hidden_and_closed_routes(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            game, areas = await setup_game(s, pid, cid)
            h = await hero(s, game, "Бран", areas["road"])
            link = await s.scalar(
                select(GeographyLink).where(GeographyLink.campaign_id == game, GeographyLink.ref == ROUTE)
            )
            link.bidirectional = False
            await s.commit()
            ctx = await context(s, game)
            assert (await travel_route(ctx, ROUTE, [h])).failure_code == "one_way"
            link.bidirectional, link.hidden = True, True
            await s.commit()
            ctx = await context(s, game)
            assert (await travel_route(ctx, ROUTE, [h])).failure_code == "route_hidden"
            link.hidden, link.constraints = False, {"state": "closed"}
            await s.commit()
            ctx = await context(s, game)
            assert (await travel_route(ctx, ROUTE, [h])).failure_code == "route_closed"
            assert ctx.world.characters[h].location_id == areas["road"]

    _prepared_with(settings, body)


def test_tool_path_succeeds_and_failure_is_a_tool_error(settings, _fast_retry):
    async def body(maker, pid, cid):
        async with maker() as s:
            game, areas = await setup_game(s, pid, cid)
            h = await hero(s, game, "Бран", areas["narthex"])
            await s.commit()
            ctx = await context(s, game)
            ok = await execute(ctx, "travel_route", {"route_id": ROUTE, "character_ids": [h]})
            assert ok["ok"] and ok["result"]["destination_area_id"] == areas["road"]
            bad = await execute(ctx, "travel_route", {"route_id": "no_such", "character_ids": [h]})
            assert not bad["ok"]
            events = list(await s.scalars(select(Event).where(Event.campaign_id == game, Event.tool == "travel_route")))
            assert len(events) <= 1

    _prepared_with(settings, body)


def test_prepared_start_is_entered_without_new_generation(settings, _fast_retry):
    async def body(maker, pid, cid):
        from sqlalchemy import func

        from app.agents.prelude import relocate_to_prepared_start
        from app.db.models import LlmCall, WorldGenerationState

        async with maker() as s:
            game, areas = await setup_game(s, pid, cid)
            h = await hero(s, game, "Бран", None)
            before = await s.scalar(
                select(func.count()).select_from(WorldGenerationState).where(WorldGenerationState.campaign_id == game)
            )
            await s.commit()
            ctx = await context(s, game)
            start = next(e for e in ctx.world.entities.values() if e.name == "Старый храм")
            assert await relocate_to_prepared_start(ctx, start)
            assert ctx.world.scene.location_id == start.id
            assert ctx.world.place_of(ctx.world.characters[h]) == start.id
            await s.commit()
            after = await s.scalar(
                select(func.count()).select_from(WorldGenerationState).where(WorldGenerationState.campaign_id == game)
            )
            assert after == before  # вход в исходную карту ничего не генерирует
            assert await s.scalar(select(func.count()).select_from(LlmCall).where(LlmCall.campaign_id == game)) == 0
            assert not await relocate_to_prepared_start(ctx, start)  # повтор ничего не делает

    _prepared_with(settings, body)
