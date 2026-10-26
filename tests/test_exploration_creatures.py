import asyncio

import pytest
from sqlalchemy import func, select

from app.core.campaigns import AccessDenied
from app.core.universal.clock import complete_step
from app.core.universal.effects import active_effects
from app.core.universal.objects import apply_object_operation, object_state
from app.core.universal.resolution import ResolutionContext
from app.db.models import Character, Entity, Event
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2, IntentV2
from tests.test_exploration_resolution import build
from tests.test_universal_resolution import setup


def puppet(**extra):
    return IntentV2(
        name="Марионетка",
        source="supernatural",
        player_request="supernatural",
        resolution="automatic",
        effects=[
            EffectIntentV2(
                kind="create_object",
                template="creature",
                scale="medium",
                label="Глиняный человечек",
                appearance="Фигурка из глины ростом с ладонь.",
                abilities="Ходит, переносит лёгкое, понимает простые приказы; силой с ребёнка.",
                **extra,
            )
        ],
    )


def order(object_id, what="принести ключ со стола"):
    return IntentV2(
        source="mundane",
        player_request="ordinary",
        resolution="automatic",
        effects=[EffectIntentV2(kind="command", object_id=object_id, label=what)],
    )


async def the_puppet(s):
    return await s.scalar(select(Entity).where(Entity.kind == "object"))


async def wis(s):
    return (await s.get(Character, "hero", populate_existing=True)).resources["energies"]["wis"]


def test_a_clay_puppet_is_created_for_its_term_and_priced_by_size(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            _, made = await build(ctx, s, puppet())
            assert made.status == "applied" and made.cost == 12  # medium: 4 per unit, three units
            row = await the_puppet(s)
            state = object_state(row)
            assert state.template == "creature" and state.controller_id == "hero" and state.temporary
            assert "силой с ребёнка" in state.abilities and row.name == "Глиняный человечек"
            assert await wis(s) == "14"  # 24 - 12 + 2 of the step's regeneration
        await engine.dispose()

    asyncio.run(run())


def test_the_creator_orders_the_puppet_about_for_free_and_a_stranger_cannot(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            await build(ctx, s, puppet())
            row = await the_puppet(s)
            before = await wis(s)
            _, ordered = await build(ctx, s, order(row.id), "m2", 2)
            assert ordered.status == "applied" and ordered.cost == 0
            assert any(c.kind == "commanded" and "принести ключ" in c.description for c in ordered.changes)
            assert int(await wis(s)) == int(before) + 2  # only the passing six seconds give energy back
            stranger = ResolutionContext(s, "c", "u", "seat", "target", FixedDice([]))
            s.add(Event(id="e-stranger", campaign_id="c", actor_id="target", tool="universal_action", payload={}))
            await s.flush()
            op = EffectIntentV2(kind="command", object_id=row.id, label="убежать")
            with pytest.raises(ValueError, match="создатель"):
                await apply_object_operation(stranger, op, await s.get(Event, "e-stranger"))
        await engine.dispose()

    asyncio.run(run())


def test_a_puppet_dissolves_when_its_term_ends_and_takes_no_more_orders(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            await build(ctx, s, puppet())
            row = await the_puppet(s)
            await complete_step(s, "c", "later", 24)
            await s.refresh(row)
            assert object_state(row).expired
            with pytest.raises(AccessDenied):
                await build(ctx, s, order(row.id), "m2", 2)
        await engine.dispose()

    asyncio.run(run())


def free_effect():
    return IntentV2(
        name="Остановить",
        source="supernatural",
        player_request="supernatural",
        resolution="automatic",
        effects=[
            EffectIntentV2(
                kind="free_effect",
                scale="small",
                label="Скелеты в тоннеле остановлены",
                appearance="Костяные силуэты замерли на месте и не двигаются.",
            )
        ],
    )


def test_a_free_effect_is_remembered_and_shown_to_the_master_until_it_ends(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            _, made = await build(ctx, s, free_effect())
            assert made.status == "applied" and made.cost == 6  # small: 2 per unit, three units
            running = await active_effects(s, "c", "hero")
            assert [e["kind"] for e in running] == ["free_effect"]
            assert running[0]["definition"]["label"] == "Скелеты в тоннеле остановлены"
            assert "замерли" in running[0]["definition"]["appearance"]
            await complete_step(s, "c", "later", 24)
            assert not await active_effects(s, "c", "hero")
        await engine.dispose()

    asyncio.run(run())


def test_replaying_a_creation_or_free_effect_makes_no_second_one(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            action, _ = await build(ctx, s, puppet())
            after = await wis(s)
            from app.core.universal.exploration_resolution import resolve_exploration

            assert (await resolve_exploration(ctx, action, "m")).status == "repeated"
            assert await s.scalar(select(func.count()).select_from(Entity).where(Entity.kind == "object")) == 1
            assert await wis(s) == after
            effect, _ = await build(ctx, s, free_effect(), "m2", 2)
            assert (await resolve_exploration(ctx, effect, "m2")).status == "repeated"
            assert len([e for e in await active_effects(s, "c", "hero") if e["kind"] == "free_effect"]) == 1
        await engine.dispose()

    asyncio.run(run())
