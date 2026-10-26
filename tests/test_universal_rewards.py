import asyncio

from app.core.universal.combat import run_exchange
from app.core.universal.profiles import load_actor
from app.core.universal.resolution import ResolutionContext
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2
from tests.test_universal_combat_actions import attack
from tests.test_universal_exchange import enemy
from tests.test_universal_resolution import setup


def test_saved_victory_awards_all_local_participants_once(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await enemy(s, hp="1")
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([20, 4, 4]))
            action = await attack(s, ctx, [EffectIntentV2(kind="damage")], targets=["foe"])
            await run_exchange(ctx, action, request_key="attack")
            assert (await load_actor(s, "c", "hero"))[0].xp == 150
            await run_exchange(ctx, action, request_key="attack")
            assert (await load_actor(s, "c", "hero"))[0].xp == 150
        await engine.dispose()

    asyncio.run(run())


def test_model_cleaner_keeps_real_combat_targets():
    from app.rules.universal.exploration import clean_model_intent

    assert clean_model_intent(dict(source="supernatural", targets=["foe"], effects=[dict(kind="damage")]))[
        "targets"
    ] == ["foe"]


def test_exploration_rewards_four_players_once_and_rejects_invented_achievement(tmp_path):
    from app.core.universal.interpretation import compile_exploration
    from app.db.models import Character, Entity, Message, Seat
    from app.rules.universal.exploration import IntentReview, IntentV2
    from app.rules.universal.progression import RewardIntent
    from tests.test_universal_resolution import sheet

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add(Entity(id="place", campaign_id="c", kind="location", name="Ruins", description="Known walls."))
            await s.flush()
            (await s.get(Character, "hero")).location_id = "place"
            ids = ["hero"]
            for index in range(2, 5):
                seat = Seat(id=f"p{index}", campaign_id="c", role="player", position=index, occupant_type="human")
                s.add(seat)
                await s.flush()
                actor = Character(
                    id=f"hero{index}",
                    campaign_id="c",
                    seat_id=seat.id,
                    owner_user_id="u",
                    name="Ally",
                    status="active",
                    location_id="place",
                    sheet=sheet().model_dump(mode="json"),
                    resources=dict(hp="22", energies=dict(str="18", dex="20", int="23", wis="24", cha="25")),
                )
                s.add(actor)
                ids.append(actor.id)
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            for index, subject in enumerate(["missing", "place", "place"], 1):
                key = f"observe{index}"
                s.add(
                    Message(
                        id=key,
                        campaign_id="c",
                        seq=index,
                        seat_id="seat",
                        author_user_id="u",
                        kind="action",
                        content=key,
                    )
                )
                await s.flush()
                intent = IntentV2(
                    source="mundane",
                    resolution="automatic",
                    effects=[EffectIntentV2(kind="observe")],
                    reward=RewardIntent(
                        category="exploration", subject_id=subject, difficulty="hard", reason="Исследованы руины"
                    ),
                )
                action = await compile_exploration(
                    ctx, intent, IntentReview(verdict="pass"), dict(source_message_id=key, source_text=key, evidence="")
                )
                await run_exchange(ctx, action, request_key=key)
                for aid in ids:
                    assert (await load_actor(s, "c", aid))[0].xp == (0 if index == 1 else 300)
        await engine.dispose()

    asyncio.run(run())


def test_periodic_victory_awards_even_when_current_check_failed(tmp_path):
    from app.db.models import Message
    from tests.test_exploration_resolution import prepare

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await enemy(s, hp="1")
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            action = await attack(
                s, ctx, [EffectIntentV2(kind="damage_over_time")], targets=["foe"], resolution="automatic"
            )

            async def pass_reply(_):
                return None

            await run_exchange(ctx, action, choose_reply=pass_reply, request_key="attack")
            (await s.get(Message, "attack")).seq = 0
            await s.flush()
            wait = await prepare(s, ctx, "wait", source="mundane", resolution="check", mid="wait")
            ctx.dice = FixedDice([1, 4])
            results = await run_exchange(ctx, wait, choose_reply=pass_reply, request_key="wait")
            assert not results[0].success
            assert (await load_actor(s, "c", "hero"))[0].xp == 150
            ctx.dice = FixedDice([])
            await run_exchange(ctx, wait, request_key="wait")
            assert (await load_actor(s, "c", "hero"))[0].xp == 150
        await engine.dispose()

    asyncio.run(run())


def test_area_victories_use_one_preaward_group_level(tmp_path):
    from app.db.models import Entity
    from tests.test_universal_resolution import sheet

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            for index in range(4):
                s.add(
                    Entity(
                        id=f"foe{index}",
                        campaign_id="c",
                        kind="creature",
                        name="Foe",
                        state={
                            "hostile": True,
                            "universal_sheet": sheet().model_dump(mode="json"),
                            "resources": dict(hp="1", energies=dict(str="18", dex="20", int="23", wis="24", cha="25")),
                        },
                    )
                )
            await s.flush()
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([20, 3, 3] * 4))
            action = await attack(s, ctx, [EffectIntentV2(kind="damage")], targets=[f"foe{i}" for i in range(4)])
            await run_exchange(ctx, action, request_key="attack")
            assert (await load_actor(s, "c", "hero"))[0].xp == 600
        await engine.dispose()

    asyncio.run(run())


def test_periodic_remote_victory_awards_its_party_without_leaking_to_actor(tmp_path):
    from sqlalchemy import select

    from app.core.universal.effects import start_effect
    from app.db.models import Character, CombatExchange, Entity, Event, Seat
    from tests.test_exploration_resolution import prepare

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add_all(
                [
                    Entity(id="left", campaign_id="c", kind="location", name="Left"),
                    Entity(id="right", campaign_id="c", kind="location", name="Right"),
                    Seat(id="remote-seat", campaign_id="c", role="player", position=2, occupant_type="human"),
                ]
            )
            await s.flush()
            (await s.get(Character, "hero")).location_id = "left"
            target = await s.get(Character, "target")
            target.seat_id = "remote-seat"
            target.location_id = "right"
            foe = await enemy(s, hp="1")
            foe.location_id = "right"
            s.add(Event(id="remote-dot", campaign_id="c", actor_id="target", tool="universal_action", payload={}))
            await s.flush()
            await start_effect(
                s, "c", "target", "foe", "remote-dot", "dot", EffectIntentV2(kind="damage_over_time"), 0, 18
            )
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([4]))
            action = await prepare(s, ctx, "wait", source="mundane")
            await run_exchange(ctx, action, request_key="m")
            assert (await load_actor(s, "c", "hero"))[0].xp == 0
            assert (await load_actor(s, "c", "target"))[0].xp == 150
            exchange = await s.scalar(select(CombatExchange))
            assert all(c["private"] for c in exchange.changes if c["kind"] == "xp_awarded")
        await engine.dispose()

    asyncio.run(run())


def test_quest_reward_requires_completed_saved_quest_and_observed_evidence(tmp_path):
    from app.core.universal.interpretation import compile_exploration
    from app.db.models import Character, Entity, Message
    from app.rules.universal.exploration import IntentReview, IntentV2
    from app.rules.universal.progression import RewardIntent

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add(Entity(id="place", campaign_id="c", kind="location", name="Hall"))
            quest = Entity(
                id="quest",
                campaign_id="c",
                kind="quest",
                location_id="place",
                name="Bridge repaired",
                description="Known achievement",
                state={"completed": False},
            )
            s.add(quest)
            await s.flush()
            (await s.get(Character, "hero")).location_id = "place"
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            for index in (1, 2, 3):
                if index == 2:
                    quest.state = {"completed": True}
                key = f"quest{index}"
                s.add(
                    Message(
                        id=key,
                        campaign_id="c",
                        seq=index,
                        seat_id="seat",
                        author_user_id="u",
                        kind="action",
                        content=key,
                    )
                )
                await s.flush()
                intent = IntentV2(
                    source="mundane",
                    resolution="automatic",
                    effects=[EffectIntentV2(kind="observe")],
                    reward=RewardIntent(
                        category="quest", subject_id=quest.id, difficulty="hard", reason="Мост восстановлен"
                    ),
                )
                action = await compile_exploration(
                    ctx, intent, IntentReview(verdict="pass"), dict(source_message_id=key, source_text=key, evidence="")
                )
                await run_exchange(ctx, action, request_key=key)
                assert (await load_actor(s, "c", "hero"))[0].xp == (0 if index == 1 else 300)
        await engine.dispose()

    asyncio.run(run())
