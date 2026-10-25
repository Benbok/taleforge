import asyncio

import pytest
from sqlalchemy import func, select

from app.core.campaigns import AccessDenied
from app.core.universal.clock import clock_view, complete_step
from app.core.universal.exploration_resolution import resolve_exploration
from app.core.universal.interpretation import compile_exploration
from app.core.universal.objects import accessible, object_state
from app.core.universal.resolution import ResolutionContext
from app.db.models import Character, Entity, Event, HeroAbility, Message, RuntimeProfile
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2, InsufficientEnergy, IntentReview, IntentV2
from app.rules.universal.profiles import CheckNarration
from tests.test_universal_resolution import setup


async def prepare(s, ctx, kind="cosmetic", source="supernatural", resolution="automatic", mid="m"):
    s.add(
        Message(
            id=mid, campaign_id="c", seq=1, seat_id="seat", author_user_id="u", kind="action", content="Пробую действие"
        )
    )
    await s.flush()
    intent = IntentV2(
        name=kind,
        source=source,
        resolution=resolution,
        intensity="light",
        effects=[EffectIntentV2(kind=kind, lifetime="permanent" if kind == "create_object" else "instant")],
        check_outcomes=CheckNarration(
            success="Успех проверки.",
            failure="Провал проверки.",
            critical_success="Особый успех.",
            critical_failure="Особый провал.",
        )
        if resolution == "check"
        else None,
    )
    return await compile_exploration(
        ctx,
        intent,
        IntentReview(verdict="pass"),
        dict(source_message_id=mid, source_text="Пробую действие", evidence=""),
    )


async def run_low(maker, wis="10"):
    """Start from a pool well below its top, so a payment is not hidden by the cap that regeneration respects."""
    async with maker() as s:
        hero = await s.get(Character, "hero")
        hero.resources = {**hero.resources, "energies": {**hero.resources["energies"], "wis": wis}}
        await s.commit()


def test_paid_automatic_cup_learns_once_and_replays_without_time_or_energy(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await run_low(maker)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            action = await prepare(s, ctx, "create_object")
            result = await resolve_exploration(ctx, action, "m")
            assert result.status == "applied" and result.success and result.cost == 1 and result.ability_ref
            assert result.rolls == []
            assert await s.scalar(select(func.count()).select_from(Entity)) == 1
            assert await s.scalar(select(func.count()).select_from(HeroAbility)) == 1
            assert (await resolve_exploration(ctx, action, "m")).status == "repeated"
            # 10, minus the price 1, plus the 2 the six seconds of this step give back; the replay adds nothing
            assert (await s.get(Character, "hero")).resources["energies"]["wis"] == "11"
            assert (await clock_view(s, "c"))["game_seconds"] == "6"
            await s.commit()
        async with maker() as s:
            ctx.session = s
            assert (await resolve_exploration(ctx, action, "m")).status == "repeated"
            assert await s.scalar(select(func.count()).select_from(Entity)) == 1
        await engine.dispose()

    asyncio.run(run())


def test_failed_attempt_spends_but_does_not_apply_or_learn(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await run_low(maker)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([1]))
            action = await prepare(s, ctx, resolution="check")
            result = await resolve_exploration(ctx, action, "m")
            assert result.status == "applied" and not result.success and result.cost == 1
            assert result.critical_failure and not result.ability_ref
            assert (await s.get(Character, "hero")).resources["energies"]["wis"] == "11"  # 10 - 1 + 2 of regeneration
            assert (await s.get(Character, "hero")).resources["hp"] == "22"
            assert not result.changes
        await engine.dispose()

    asyncio.run(run())


def test_free_listening_does_not_learn_and_rejection_creates_nothing(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([20]))
            action = await prepare(s, ctx, "observe", source="mundane", resolution="check")
            result = await resolve_exploration(ctx, action, "m")
            assert result.success and result.cost == 0 and not result.ability_ref
            assert await s.scalar(select(func.count()).select_from(HeroAbility)) == 0
            before = await s.scalar(select(func.count()).select_from(Event))
            denied = await resolve_exploration(ctx, action.model_copy(update={"cost": 50}), "other")
            assert denied.status == "denied"
            assert await s.scalar(select(func.count()).select_from(Event)) == before
            assert await s.scalar(select(func.count()).select_from(RuntimeProfile)) == 0
        await engine.dispose()

    asyncio.run(run())


def test_failure_between_components_rolls_back_debit_objects_and_clock(tmp_path, monkeypatch):
    import app.core.universal.exploration_resolution as executor

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            action = await prepare(s, ctx, "create_object")
            original = executor.apply_object_operation
            calls = 0

            async def broken(*args, **kwargs):
                nonlocal calls
                calls += 1
                change = await original(*args, **kwargs)
                if calls == 2:  # after the read-before-roll simulation
                    raise ValueError("technical component failure")
                return change

            monkeypatch.setattr(executor, "apply_object_operation", broken)
            assert (await resolve_exploration(ctx, action, "m")).status == "denied"
            assert await s.scalar(select(func.count()).select_from(Entity)) == 0
            assert await s.scalar(select(func.count()).select_from(Event)) == 0
            assert await s.scalar(select(func.count()).select_from(HeroAbility)) == 0
            assert (await s.get(Character, "hero")).resources["energies"]["wis"] == "24"
            assert (await clock_view(s, "c"))["game_seconds"] == "0"
        await engine.dispose()

    asyncio.run(run())


def test_dismissing_an_effect_early_is_free_and_gives_no_energy_back(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await run_low(maker)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            action = await prepare(s, ctx, "illumination")
            cast = await resolve_exploration(ctx, action, "m")
            assert cast.status == "applied" and cast.cost == 3
            spent = (await s.get(Character, "hero")).resources["energies"]["wis"]
            assert spent == "9"  # 10 - 3 + 2 of regeneration
            effect_id = next(c.data["effect_id"] for c in cast.changes if c.kind == "illumination")
            s.add(
                Message(
                    id="m2",
                    campaign_id="c",
                    seq=2,
                    seat_id="seat",
                    author_user_id="u",
                    kind="action",
                    content="Гашу свет",
                )
            )
            await s.flush()
            dismiss = await compile_exploration(
                ctx,
                IntentV2(
                    source="mundane",
                    resolution="automatic",
                    effects=[EffectIntentV2(kind="dismiss", effect_id=effect_id)],
                ),
                IntentReview(verdict="pass"),
                dict(source_message_id="m2", source_text="Гашу свет", evidence=""),
            )
            result = await resolve_exploration(ctx, dismiss, "m2")
            assert result.status == "applied" and result.cost == 0
            # only the passing six seconds give energy back (+2); dismissing refunds none of the price
            assert (await s.get(Character, "hero")).resources["energies"]["wis"] == "11"
            from app.core.universal.effects import active_effects

            assert not await active_effects(s, "c", "hero")
        await engine.dispose()

    asyncio.run(run())


def test_a_failed_check_is_described_by_the_outcome_the_model_wrote_for_it(tmp_path):
    async def run():
        for dice, expected in (([4], "Провал проверки."), ([1], "Особый провал.")):
            folder = tmp_path / f"d{dice[0]}"
            folder.mkdir()
            engine, maker = await setup(folder)
            async with maker() as s:
                ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice(dice))
                action = await prepare(s, ctx, "observe", source="mundane", resolution="check")
                result = await resolve_exploration(ctx, action, "m")
                assert not result.success
                assert result.description == expected  # not the same blank line for every failure
            await engine.dispose()

    asyncio.run(run())


def structure(scale="large", lifetime="permanent", **extra):
    return IntentV2(
        name="Мост",
        source="supernatural",
        player_request="supernatural",
        resolution="automatic",
        effects=[
            EffectIntentV2(
                kind="create_object",
                template="structure",
                scale=scale,
                lifetime=lifetime,
                label="Каменный мост",
                appearance="Широкий мост из серого камня.",
                **extra,
            )
        ],
    )


async def build(ctx, session, intent, mid="m", seq=1):
    session.add(
        Message(id=mid, campaign_id="c", seq=seq, seat_id="seat", author_user_id="u", kind="action", content="Строю")
    )
    await session.flush()
    action = await compile_exploration(
        ctx, intent, IntentReview(verdict="pass"), dict(source_message_id=mid, source_text="Строю", evidence="")
    )
    return action, await resolve_exploration(ctx, action, mid)


def test_a_structure_is_remembered_priced_and_not_built_twice(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await run_low(maker, "24")
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            action, result = await build(ctx, s, structure())
            assert result.status == "applied" and result.cost == 12
            rows = list(await s.scalars(select(Entity).where(Entity.kind == "object")))
            assert len(rows) == 1 and rows[0].name == "Каменный мост"
            state = object_state(rows[0])
            assert state.template == "structure" and state.owner_id is None and state.scale == "large"
            energy = (await s.get(Character, "hero")).resources["energies"]["wis"]
            assert energy == "14"  # 24 - 12 + 2 of the step's regeneration
            assert (await resolve_exploration(ctx, action, "m")).status == "repeated"
            assert await s.scalar(select(func.count()).select_from(Entity).where(Entity.kind == "object")) == 1
            assert (await s.get(Character, "hero")).resources["energies"]["wis"] == energy
        await engine.dispose()

    asyncio.run(run())


def test_another_hero_in_the_place_can_use_the_structure_and_one_elsewhere_cannot(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            await build(ctx, s, structure())
            row = await s.scalar(select(Entity).where(Entity.kind == "object"))
            other = await s.get(Character, "target")
            assert accessible(row, other).template == "structure"
            other.location_id = "elsewhere"
            with pytest.raises(AccessDenied):
                accessible(row, other)
        await engine.dispose()

    asyncio.run(run())


def test_a_timed_structure_vanishes_when_its_eighteen_seconds_pass(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            await build(ctx, s, structure("medium", "timed"))
            row = await s.scalar(select(Entity).where(Entity.kind == "object"))
            assert not object_state(row).expired
            await complete_step(s, "c", "later", 24)
            await s.refresh(row)
            assert object_state(row).expired
        await engine.dispose()

    asyncio.run(run())


def test_a_huge_creation_the_hero_cannot_afford_is_refused_with_numbers_and_builds_nothing(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await run_low(maker, "7")
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            with pytest.raises(InsufficientEnergy, match="нужно 24, есть 7"):
                await build(ctx, s, structure("huge"))
            assert await s.scalar(select(func.count()).select_from(Entity).where(Entity.kind == "object")) == 0
            assert await s.scalar(select(func.count()).select_from(Event)) == 0
        await engine.dispose()

    asyncio.run(run())


def test_a_structure_cannot_be_picked_up_or_poured(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            await build(ctx, s, structure())
            row = await s.scalar(select(Entity).where(Entity.kind == "object"))
            take = IntentV2(
                source="mundane",
                player_request="ordinary",
                resolution="automatic",
                effects=[EffectIntentV2(kind="take", object_id=row.id)],
            )
            _, result = await build(ctx, s, take, "m2", 2)
            assert result.status == "denied" and result.failure is not None
            assert object_state(row).owner_id is None  # the structure stays where it was built
        await engine.dispose()

    asyncio.run(run())
