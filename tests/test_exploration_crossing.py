import asyncio

import pytest
from sqlalchemy import func, select

from app.core.campaigns import AccessDenied
from app.core.universal.effects import start_effect
from app.core.universal.interpretation import compile_exploration
from app.core.universal.objects import object_state, store
from app.core.universal.resolution import ResolutionContext
from app.db.models import Character, Entity, Event
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2, FormBlocked, IntentReview, IntentV2
from app.rules.universal.profiles import CheckNarration
from tests.test_exploration_resolution import build, structure
from tests.test_universal_resolution import setup

OUTCOMES = CheckNarration(
    success="Вы переходите по мосту.",
    failure="Мост дрогнул, и вы вернулись.",
    critical_success="Вы пробегаете по мосту.",
    critical_failure="Мост трещит, и вы едва успеваете отступить.",
)


async def origin(maker):
    async with maker() as s:
        s.add(Entity(id="loc_origin", campaign_id="c", kind="location", name="Провал", state={}))
        for hero in ("hero", "target"):
            (await s.get(Character, hero)).location_id = "loc_origin"
        await s.commit()


def walk(object_id, resolution="automatic"):
    return IntentV2(
        source="mundane",
        player_request="ordinary",
        resolution=resolution,
        check_outcomes=OUTCOMES if resolution == "check" else None,
        effects=[EffectIntentV2(kind="move", object_id=object_id)],
    )


def bridge(**extra):
    return structure("large", leads_to="Дальний край пропасти", leads_view="Тёмный уступ за туманом.", **extra)


async def location_of(s, hero="hero"):
    return (await s.get(Character, hero, populate_existing=True)).location_id


async def the_object(s):
    return await s.scalar(select(Entity).where(Entity.kind == "object"))


def test_crossing_creates_the_far_place_once_and_moves_only_the_walker(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await origin(maker)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            await build(ctx, s, bridge())
            row = await the_object(s)
            _, crossed = await build(ctx, s, walk(row.id), "m2", 2)
            assert crossed.status == "applied" and any(c.kind == "moved" for c in crossed.changes)
            far = await s.scalar(
                select(Entity).where(Entity.kind == "location", Entity.name == "Дальний край пропасти")
            )
            assert far is not None and far.description == "Тёмный уступ за туманом."
            assert {"to": "loc_origin", "label": "Каменный мост"} in far.state["links"]
            near = await s.get(Entity, "loc_origin", populate_existing=True)
            assert any(link["to"] == far.id for link in near.state["links"])
            assert await location_of(s) == far.id and await location_of(s, "target") == "loc_origin"
        await engine.dispose()

    asyncio.run(run())


def test_crossing_back_from_the_far_side_returns_to_the_origin_without_a_second_place(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await origin(maker)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            await build(ctx, s, bridge())
            row = await the_object(s)
            await build(ctx, s, walk(row.id), "m2", 2)
            assert await location_of(s) != "loc_origin"
            await build(ctx, s, walk(row.id), "m3", 3)
            assert await location_of(s) == "loc_origin"
            places = await s.scalar(select(func.count()).select_from(Entity).where(Entity.kind == "location"))
            assert places == 2
        await engine.dispose()

    asyncio.run(run())


def test_an_expired_structure_gives_no_path_and_the_hero_stays(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await origin(maker)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            await build(ctx, s, bridge())
            row = await the_object(s)
            gone = object_state(row)
            gone.expired = True  # the bridge has vanished (a timed one does at the end of its eighteen seconds)
            store(row, gone)
            await s.flush()
            with pytest.raises(AccessDenied):
                await build(ctx, s, walk(row.id), "m2", 2)
            assert await location_of(s) == "loc_origin"
        await engine.dispose()

    asyncio.run(run())


def test_a_failed_check_does_not_move_and_is_told_in_the_models_words(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await origin(maker)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            await build(ctx, s, bridge())
            row = await the_object(s)
            ctx.dice = FixedDice([4])
            _, failed = await build(ctx, s, walk(row.id, "check"), "m2", 2)
            assert not failed.success and failed.description == "Мост дрогнул, и вы вернулись."
            assert await location_of(s) == "loc_origin"
        await engine.dispose()

    asyncio.run(run())


def test_a_structure_that_leads_nowhere_cannot_be_crossed(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await origin(maker)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            await build(ctx, s, structure("large"))
            row = await the_object(s)
            _, result = await build(ctx, s, walk(row.id), "m2", 2)
            assert result.status == "denied" and await location_of(s) == "loc_origin"
            assert await s.scalar(select(func.count()).select_from(Entity).where(Entity.kind == "location")) == 1
        await engine.dispose()

    asyncio.run(run())


def test_crossing_is_blocked_in_bush_form(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await origin(maker)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            await build(ctx, s, bridge())
            row = await the_object(s)
            s.add(Event(id="form", campaign_id="c", actor_id="hero", tool="universal_action", payload={}))
            await s.flush()
            await start_effect(
                s, "c", "hero", "hero", "form", "0", EffectIntentV2(kind="change_form", lifetime="timed"), 0, 18
            )
            with pytest.raises(FormBlocked):
                await compile_exploration(
                    ctx,
                    walk(row.id),
                    IntentReview(verdict="pass"),
                    dict(source_message_id="m9", source_text="иду", evidence=""),
                )
            assert await location_of(s) == "loc_origin"
        await engine.dispose()

    asyncio.run(run())


def test_a_hero_grows_a_bridge_and_walks_to_the_far_side(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await origin(maker)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            _, built = await build(ctx, s, bridge())
            assert built.cost == 24
            row = await the_object(s)
            ctx.dice = FixedDice([15])  # 15 + 2 beats the difficulty of 12
            _, crossed = await build(ctx, s, walk(row.id, "check"), "m2", 2)
            assert crossed.success and crossed.cost == 0
            assert await location_of(s) != "loc_origin"
            # the price once, then only the six seconds of each of the two steps give energy back
            assert (await s.get(Character, "hero")).resources["energies"]["wis"] == "4"
        await engine.dispose()

    asyncio.run(run())
