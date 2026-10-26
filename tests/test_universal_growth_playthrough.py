import asyncio

from sqlalchemy import func, select

from app.core.universal.combat import run_exchange
from app.core.universal.exploration_views import exploration_game_card
from app.core.universal.interpretation import compile_exploration
from app.core.universal.profiles import load_actor
from app.core.universal.progression import catch_up_copy, spend_points
from app.core.universal.resolution import ResolutionContext
from app.db.models import Character, Entity, Event, Message, Seat
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2, IntentReview, IntentV2
from tests.test_universal_exchange import enemy
from tests.test_universal_resolution import setup, sheet


def test_victories_growth_allocation_join_and_reconnect_do_not_inflate(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            for index in (1, 2):
                foe = (
                    await enemy(s, hp="1")
                    if index == 1
                    else Entity(id="foe2", campaign_id="c", kind="creature", name="Second foe", state={"hostile": True})
                )
                if index == 2:
                    s.add(foe)
                    await s.flush()
                    from app.core.universal.combat_actions import initialize_combatant

                    await initialize_combatant(s, "c", foe.id)
                    foe.state = {**foe.state, "resources": {**foe.state["resources"], "hp": "1"}}
                key = f"attack{index}"
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
                    name="Bolt",
                    source="supernatural",
                    resolution="attack",
                    targets=[foe.id],
                    effects=[EffectIntentV2(kind="damage")],
                )
                action = await compile_exploration(
                    ctx, intent, IntentReview(verdict="pass"), dict(source_message_id=key, source_text=key, evidence="")
                )
                ctx.dice = FixedDice([20, 3, 3])
                await run_exchange(ctx, action, request_key=key)
            hero = await s.get(Character, "hero")
            assert (await load_actor(s, "c", hero.id))[0].unspent_points == 2
            revision = hero.resources["progression_revision"]
            grown = await spend_points(s, "c", hero.id, revision, {"wis": 2}, "allocation")
            assert grown.level == 2 and grown.abilities.wis == 16
            s.add(Seat(id="new-seat", campaign_id="c", role="player", position=2, occupant_type="human"))
            await s.flush()
            copied = Character(
                id="new-copy",
                campaign_id="c",
                seat_id="new-seat",
                owner_user_id="u",
                name="New",
                status="approved",
                sheet=sheet().model_dump(mode="json"),
                resources=dict(hp="22", energies=dict(str="18", dex="20", int="23", wis="24", cha="25")),
            )
            s.add(copied)
            await s.flush()
            assert (await catch_up_copy(s, "c", copied.id)).unspent_points == 2
            await s.commit()
            count = await s.scalar(select(func.count()).select_from(Event))
        async with maker() as s:
            ctx.session = s
            ctx.dice = FixedDice([])
            await run_exchange(ctx, action, request_key="attack2")
            await spend_points(s, "c", "hero", revision, {"wis": 2}, "allocation")
            await catch_up_copy(s, "c", "new-copy")
            card = await exploration_game_card(s, await s.get(Character, "hero"))
            assert card["sheet"]["xp"] == "300" and card["sheet"]["unspent_points"] == "0"
            assert card["sheet"]["abilities"]["wis"] == "16"
            assert await s.scalar(select(func.count()).select_from(Event)) == count
        await engine.dispose()

    asyncio.run(run())
