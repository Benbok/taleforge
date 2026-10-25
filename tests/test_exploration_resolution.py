import asyncio

from sqlalchemy import func, select

from app.core.universal.clock import clock_view
from app.core.universal.exploration_resolution import resolve_exploration
from app.core.universal.interpretation import compile_exploration
from app.core.universal.resolution import ResolutionContext
from app.db.models import Character, Entity, Event, HeroAbility, Message, RuntimeProfile
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2, IntentReview, IntentV2
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
