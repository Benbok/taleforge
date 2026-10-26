import asyncio

import pytest

from app.core.campaigns import AccessDenied
from app.core.universal.objects import (
    apply_object_operation,
    expire_temporary_object,
    introduce_object,
    ordinary_object_view,
    visible_objects,
)
from app.core.universal.resolution import ResolutionContext
from app.db.models import Character, Entity, Event
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2, IntroductionV2
from tests.test_universal_resolution import setup


async def world(tmp_path):
    engine, maker = await setup(tmp_path)
    return engine, maker


def test_real_cup_fill_transfer_place_and_replay(tmp_path):
    async def run():
        engine, maker = await world(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            event = Event(id="cup-event", campaign_id="c", actor_id="hero", tool="universal_action", payload={})
            s.add(event)
            await s.flush()
            water = await introduce_object(
                s,
                "c",
                IntroductionV2(
                    ref="water", template="water_source", name="Ручей", evidence_quote="Рядом течёт ручей", amount=1000
                ),
                "Рядом течёт ручей",
                actor_id="hero",
            )
            op = EffectIntentV2(kind="create_object", label="Кружка", lifetime="timed")
            result = await apply_object_operation(ctx, op, event, component="0")
            cup_id = result.subject_id
            assert (await apply_object_operation(ctx, op, event, component="0")).subject_id == cup_id
            cup = await s.get(Entity, cup_id)
            assert ordinary_object_view(cup)["capacity_ml"] == "300"
            await apply_object_operation(
                ctx, EffectIntentV2(kind="fill", object_id=cup_id, source_id=water.id, amount=200), event
            )
            assert ordinary_object_view(cup)["contents_ml"] == "200"
            assert ordinary_object_view(water)["amount"] == "800"
            second = await apply_object_operation(ctx, op, event, component="second")
            await apply_object_operation(
                ctx, EffectIntentV2(kind="pour", object_id=cup_id, target_id=second.subject_id, amount=50), event
            )
            assert ordinary_object_view(cup)["contents_ml"] == "150"
            await apply_object_operation(ctx, EffectIntentV2(kind="empty", object_id=second.subject_id), event)
            assert ordinary_object_view(await s.get(Entity, second.subject_id))["contents_ml"] == "0"
            await apply_object_operation(ctx, EffectIntentV2(kind="place", object_id=cup_id), event)
            await apply_object_operation(ctx, EffectIntentV2(kind="take", object_id=cup_id), event)
            await apply_object_operation(
                ctx, EffectIntentV2(kind="give", object_id=cup_id, recipient_id="target"), event
            )
            assert not any(x["id"] == cup_id for x in await visible_objects(s, "c", "hero"))
            with pytest.raises(AccessDenied):
                await apply_object_operation(ctx, EffectIntentV2(kind="empty", object_id=cup_id), event)
            await s.commit()
        async with maker() as s:
            assert ordinary_object_view(await s.get(Entity, cup_id))["contents_ml"] == "150"
        await engine.dispose()

    asyncio.run(run())


def test_material_privacy_and_temporary_contents_release_once(tmp_path):
    async def run():
        engine, maker = await world(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            event = Event(id="event", campaign_id="c", actor_id="hero", tool="universal_action", payload={})
            s.add(event)
            await s.flush()
            wood = await introduce_object(
                s,
                "c",
                IntroductionV2(ref="wood", template="wood_source", name="Щепка", evidence_quote="Видна щепка"),
                "Видна щепка",
                actor_id="hero",
            )
            wood.state = {**wood.state, "hidden": True}
            with pytest.raises(AccessDenied):
                await apply_object_operation(ctx, EffectIntentV2(kind="create_object", source_id=wood.id), event)
            wood.state = {**wood.state, "hidden": False}
            change = await apply_object_operation(
                ctx, EffectIntentV2(kind="create_object", source_id=wood.id, lifetime="timed"), event
            )
            cup = await s.get(Entity, change.subject_id)
            cup.state = {**cup.state, "exploration": {**cup.state["exploration"], "contents_ml": "120"}}
            changes = await expire_temporary_object(s, "c", cup.id)
            assert changes[0].data["released_ml"] == "120"
            assert not await expire_temporary_object(s, "c", cup.id)
            assert ordinary_object_view(cup)["contents_ml"] == "0"
            with pytest.raises(ValueError):
                await introduce_object(
                    s,
                    "c",
                    IntroductionV2(ref="invented", template="wood_source", name="Дуб", evidence_quote="Невидимый дуб"),
                    "Пустая комната",
                    actor_id="hero",
                )
        await engine.dispose()

    asyncio.run(run())


def test_only_real_energy_consumable_restores_and_is_consumed(tmp_path):
    async def run():
        engine, maker = await world(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            event = Event(id="event", campaign_id="c", actor_id="hero", tool="universal_action", payload={})
            s.add(event)
            await s.flush()
            hero = await s.get(Character, "hero")
            hero.resources = {**hero.resources, "energies": {**hero.resources["energies"], "wis": "10"}}
            tonic = await introduce_object(
                s,
                "c",
                IntroductionV2(
                    ref="tonic", template="energy_tonic", name="Настой мудрости", evidence_quote="Настой мудрости"
                ),
                "Настой мудрости",
                actor_id="hero",
            )
            await apply_object_operation(ctx, EffectIntentV2(kind="take", object_id=tonic.id), event)
            await apply_object_operation(ctx, EffectIntentV2(kind="consume", object_id=tonic.id), event)
            assert hero.resources["energies"]["wis"] == "11"
            assert hero.resources["energies"]["cha"] == "25"
            with pytest.raises(AccessDenied):
                await apply_object_operation(ctx, EffectIntentV2(kind="consume", object_id=tonic.id), event)
            with pytest.raises(ValueError):
                await apply_object_operation(ctx, EffectIntentV2(kind="create_object", template="energy_tonic"), event)
        await engine.dispose()

    asyncio.run(run())
