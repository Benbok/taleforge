import asyncio

import pytest
from sqlalchemy import select

from app.core.universal.profiles import get_profile, load_actor, put_profile, save_actor
from app.core.universal.resolution import ActionRef, ProposedAction, ResolutionContext, resolve_action
from app.db.models import Base, Campaign, Character, Event, Seat, User
from app.db.session import make_engine, make_sessionmaker
from app.rules.dice import Dice, FixedDice
from app.rules.universal.contracts import UniversalSheet
from app.rules.universal.profiles import ProfileSpec


def sheet():
    return UniversalSheet(
        abilities=dict(str=8, dex=10, con=12, int=13, wis=14, cha=15), description=dict(identity="traveler")
    )


def test_natural_one_saves_harmful_consequence_and_replay_does_not_repeat_it(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            p = await put_profile(s, "c", ProfileSpec(id="failed-bolt", attribute="wis", kind="damage"))
            proposal = ProposedAction(
                ref=ActionRef(profile_id=p.id, revision=1), actor_id="hero", targets=["target"], profile=p
            )
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([1]))
            result = await resolve_action(ctx, proposal, "critical-one")
            assert result.critical_failure
            assert (await load_actor(s, "c", "hero"))[1].hp == 21
            assert result.public_effects[0].target_id == "hero"
            assert result.public_effects[0].value == 1
            assert (await resolve_action(ctx, proposal, "critical-one")).status == "repeated"
            assert (await load_actor(s, "c", "hero"))[1].hp == 21
        await engine.dispose()

    asyncio.run(run())


async def setup(tmp_path):
    engine = make_engine(f"sqlite+aiosqlite:///{tmp_path / 'runtime.db'}")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = make_sessionmaker(engine)
    async with maker() as s:
        s.add(User(id="u", name="User", password_hash="test"))
        await s.flush()
        s.add(Campaign(id="c", owner_id="u", name="World", ruleset_id="universal", ruleset_version="universal.v1"))
        await s.flush()
        s.add(Seat(id="seat", campaign_id="c", role="player", position=1, user_id="u", occupant_type="human"))
        await s.flush()
        for id, seat in [("hero", "seat"), ("target", None)]:
            s.add(
                Character(
                    id=id,
                    campaign_id="c",
                    seat_id=seat,
                    owner_user_id="u",
                    name=id,
                    status="active",
                    sheet=sheet().model_dump(mode="json"),
                    resources=dict(hp="22", energies=dict(str="18", dex="20", int="23", wis="24", cha="25")),
                )
            )
        await s.commit()
    return engine, maker


def test_profile_scope_and_immutable_revision(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            p = ProfileSpec(id="vine", attribute="wis", kind="damage")
            await put_profile(s, "c", p)
            assert (await get_profile(s, "c", "vine", 1)) == p
            with pytest.raises(ValueError):
                await put_profile(s, "c", p.model_copy(update={"base_dice": "1d8"}))
            from app.core.campaigns import NotFound

            with pytest.raises(NotFound):
                await get_profile(s, "foreign", "vine", 1)
            sh, res = await load_actor(s, "c", "hero")
            assert res.hp == 22
            await save_actor(s, "c", "hero", sh, res)
            assert (await s.get(Character, "hero")).resources["hp"] == "22"
        await engine.dispose()

    asyncio.run(run())


def test_replay_spends_once_and_reconnect(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            p = await put_profile(s, "c", ProfileSpec(id="vine", attribute="wis", kind="damage"))
            proposal = ProposedAction(
                ref=ActionRef(profile_id="vine", revision=1), actor_id="hero", targets=["target"], profile=p
            )
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", Dice(42))
            first = await resolve_action(ctx, proposal, "request")
            before = (await load_actor(s, "c", "hero"))[1].energies["wis"]
            replay = await resolve_action(ctx, proposal, "request")
            assert replay.status == "repeated"
            assert replay.cost == first.cost
            assert (await load_actor(s, "c", "hero"))[1].energies["wis"] == before == 21
            await s.commit()
        async with maker() as s:
            assert len(list((await s.scalars(select(Event).where(Event.tool == "universal_action"))).all())) == 1
            replay = await resolve_action(ResolutionContext(s, "c", "u", "seat", "hero", Dice(0)), proposal, "request")
            assert replay.status == "repeated"
        await engine.dispose()

    asyncio.run(run())


def test_denied_scope_stale_and_unpriced_operations(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            p = await put_profile(s, "c", ProfileSpec(id="vine", attribute="wis", kind="damage"))
            base = ProposedAction(
                ref=ActionRef(profile_id="vine", revision=1), actor_id="hero", targets=["target"], profile=p
            )
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", Dice(42))
            for proposal in [
                base.model_copy(update={"targets": ["foreign"]}),
                base.model_copy(update={"profile": p.model_copy(update={"damage_bonus": 999999})}),
                base.model_copy(update={"actor_id": "target"}),
            ]:
                result = await resolve_action(ctx, proposal, "bad")
                assert result.status == "denied"
                assert (await load_actor(s, "c", "hero"))[1].energies["wis"] == 24
        await engine.dispose()

    asyncio.run(run())


def test_checks_price_training_and_discovery(tmp_path):
    from app.core.universal.discovery import learned_abilities
    from tests.test_universal_discovery import FixedDice

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            for profile, cost, learned in [
                (ProfileSpec(id="look", kind="check", attribute="int"), 0, 0),
                (ProfileSpec(id="sense", kind="check", attribute="wis", resource_key="wis"), 3, 1),
            ]:
                await put_profile(s, "c", profile)
                proposal = ProposedAction(
                    ref=ActionRef(profile_id=profile.id, revision=1), actor_id="hero", targets=["hero"], profile=profile
                )
                outcome = await resolve_action(
                    ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([14])), proposal, profile.id
                )
                assert outcome.success and outcome.cost == cost and outcome.natural == 14
                assert len(await learned_abilities(s, "hero")) == learned
            profile = await put_profile(
                s, "c", ProfileSpec(id="untrained", kind="check", attribute="wis", trained=True)
            )
            result = await resolve_action(
                ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([])),
                ProposedAction(
                    ref=ActionRef(profile_id=profile.id, revision=1), actor_id="hero", targets=["hero"], profile=profile
                ),
                "untrained",
            )
            assert result.status == "denied"
        await engine.dispose()

    asyncio.run(run())


def test_second_operation_failure_rolls_back_all(tmp_path, monkeypatch):
    from app.core.universal import resolution
    from app.rules.universal.profiles import EffectSpec
    from tests.test_universal_discovery import FixedDice

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            p = await put_profile(
                s,
                "c",
                ProfileSpec(id="heal", kind="heal", attribute="wis", effects=[EffectSpec(id="extra", kind="heal")]),
            )
            hero = await s.get(Character, "hero")
            hero.resources = {**hero.resources, "hp": "10"}
            await s.commit()
            real = resolution.restore
            calls = []

            def broken(*args):
                calls.append(args)
                if len(calls) == 2:
                    raise ValueError("operation failed")
                return real(*args)

            monkeypatch.setattr(resolution, "restore", broken)
            proposal = ProposedAction(
                ref=ActionRef(profile_id="heal", revision=1),
                actor_id="hero",
                targets=["hero"],
                profile=p,
                operations=p.effects,
            )
            result = await resolve_action(
                ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([3, 3])), proposal, "broken"
            )
            assert len(calls) == 2 and result.status == "denied"
            _, resources = await load_actor(s, "c", "hero")
            assert resources.hp == 10 and resources.energies["wis"] == 24
            assert not list((await s.scalars(select(Event))).all())
        await engine.dispose()

    asyncio.run(run())


def test_resistance_keeps_damage_and_cost_without_learning(tmp_path):
    from app.core.universal.discovery import learned_abilities
    from app.rules.universal.profiles import EffectSpec, ResistanceSpec
    from tests.test_universal_discovery import FixedDice

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            effect = EffectSpec(
                id="bind", kind="cannot_move", resistance=ResistanceSpec(source_attribute="wis", attribute="dex")
            )
            p = await put_profile(s, "c", ProfileSpec(id="vine", kind="damage", attribute="wis", effects=[effect]))
            proposal = ProposedAction(
                ref=ActionRef(profile_id="vine", revision=1),
                actor_id="hero",
                targets=["target"],
                profile=p,
                operations=p.effects,
            )
            result = await resolve_action(
                ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([18, 4, 20])), proposal, "resisted"
            )
            assert result.success and result.cost == 6 and result.damage == 6
            assert result.effect_outcomes[-1].applied is False
            _, resources = await load_actor(s, "c", "target")
            assert resources.hp == 16 and resources.effects == []
            assert (await load_actor(s, "c", "hero"))[1].energies["wis"] == 18
            assert await learned_abilities(s, "hero") == []
        await engine.dispose()

    asyncio.run(run())


def test_stale_profile_unauthorized_scene_and_changed_replay_are_denied(tmp_path):
    from tests.test_universal_discovery import FixedDice

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            p = await put_profile(s, "c", ProfileSpec(id="sense", kind="check", attribute="wis", resource_key="wis"))
            proposal = ProposedAction(
                ref=ActionRef(profile_id="sense", revision=1), actor_id="hero", targets=["hero"], profile=p
            )
            outcome = await resolve_action(
                ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([14])), proposal, "first"
            )
            assert outcome.success
            for ctx, action in [
                (ResolutionContext(s, "c", "foreign", "seat", "hero", FixedDice([])), proposal),
                (
                    ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]), frozenset()),
                    proposal.model_copy(update={"targets": ["target"]}),
                ),
            ]:
                result = await resolve_action(ctx, action, "denied")
                assert result.status == "denied"
            changed = await resolve_action(
                ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([])),
                proposal.model_copy(update={"difficulty": 2}),
                "first",
            )
            assert changed.status == "denied"
            unlearned = await put_profile(s, "c", p.model_copy(update={"id": "unlearned-stale"}))
            await put_profile(s, "c", unlearned.model_copy(update={"revision": 2}))
            stale_proposal = proposal.model_copy(
                update={"ref": ActionRef(profile_id=unlearned.id, revision=1), "profile": unlearned}
            )
            stale = await resolve_action(
                ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([])), stale_proposal, "stale"
            )
            assert stale.status == "denied"
            assert (await load_actor(s, "c", "hero"))[1].energies["wis"] == 21
        await engine.dispose()

    asyncio.run(run())


def test_receipt_records_all_damage_dice(tmp_path):
    from tests.test_universal_discovery import FixedDice

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            p = await put_profile(s, "c", ProfileSpec(id="strike", attribute="wis", kind="damage"))
            proposal = ProposedAction(
                ref=ActionRef(profile_id="strike", revision=1), actor_id="hero", targets=["target"], profile=p
            )
            await resolve_action(ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([18, 4])), proposal, "dice")
            event = await s.scalar(select(Event).where(Event.idempotency_key == "dice"))
            assert event.dice == [18, 4]
        await engine.dispose()

    asyncio.run(run())


def test_realized_effect_values_capture_clamped_hp_changes(tmp_path):
    from app.rules.universal.profiles import EffectSpec
    from tests.test_universal_discovery import FixedDice

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            row = await s.get(Character, "target")
            row.resources = {**row.resources, "hp": "2"}
            effect = EffectSpec(id="extra", kind="damage")
            p = await put_profile(s, "c", ProfileSpec(id="burst", kind="damage", attribute="wis", effects=[effect]))
            proposal = ProposedAction(
                ref=ActionRef(profile_id="burst", revision=1),
                actor_id="hero",
                targets=["target"],
                profile=p,
                operations=p.effects,
            )
            result = await resolve_action(
                ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([18, 4, 4])), proposal, "burst"
            )
            assert result.public_effects[-1].value == 0
            assert not result.effect_outcomes[-1].applied
        await engine.dispose()

    asyncio.run(run())


def test_concurrent_replay_charges_once(tmp_path):
    from tests.test_universal_discovery import FixedDice

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            p = await put_profile(s, "c", ProfileSpec(id="sense", kind="check", attribute="wis", resource_key="wis"))
            await s.commit()
        proposal = ProposedAction(
            ref=ActionRef(profile_id="sense", revision=1), actor_id="hero", targets=["hero"], profile=p
        )

        async def invoke():
            async with maker() as s:
                outcome = await resolve_action(
                    ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([14])), proposal, "concurrent"
                )
                await s.commit()
                return outcome.status

        assert sorted(await asyncio.gather(invoke(), invoke())) == ["applied", "repeated"]
        async with maker() as s:
            assert (await load_actor(s, "c", "hero"))[1].energies["wis"] == 21
            assert len(list((await s.scalars(select(Event))).all())) == 1
        await engine.dispose()

    asyncio.run(run())


def test_preloaded_sessions_preserve_each_committed_debit_and_damage(tmp_path):
    from tests.test_universal_discovery import FixedDice

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            p = await put_profile(s, "c", ProfileSpec(id="strike", kind="damage", attribute="wis"))
            await s.commit()
        proposal = ProposedAction(
            ref=ActionRef(profile_id=p.id, revision=1), actor_id="hero", targets=["target"], profile=p
        )
        async with maker() as first, maker() as second:
            # Request contexts can load both actors before either acquires the runtime lock.
            held = [await session.get(Character, actor) for session in (first, second) for actor in ("hero", "target")]
            assert len(held) == 4
            for session, key in ((first, "one"), (second, "two")):
                result = await resolve_action(
                    ResolutionContext(session, "c", "u", "seat", "hero", FixedDice([18, 4])), proposal, key
                )
                assert result.status == "applied" and result.damage == 6
                await session.commit()
        async with maker() as s:
            assert (await load_actor(s, "c", "hero"))[1].energies["wis"] == 18
            assert (await load_actor(s, "c", "target"))[1].hp == 10
        await engine.dispose()

    asyncio.run(run())
