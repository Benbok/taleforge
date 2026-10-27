import asyncio

from app.core.universal.exploration_resolution import resolve_exploration
from app.core.universal.interpretation import compile_exploration
from app.core.universal.perception import observe_known_scene
from app.core.universal.resolution import ResolutionContext
from app.db.models import Entity, Message
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2, IntentReview, IntentV2
from tests.test_universal_location_knowledge import place
from tests.test_universal_resolution import setup


async def crowd(s):
    s.add_all(
        [
            Entity(
                id="wall",
                campaign_id="c",
                kind="object",
                name="Стена",
                description="Стена с натёками.",
                location_id="gorge",
                state={},
            ),
            Entity(
                id="rats",
                campaign_id="c",
                kind="creature",
                name="Крысы",
                description="Слепые крысы шуршат в костях.",
                location_id="gorge",
                state={},
            ),
        ]
    )
    await s.flush()
    return ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))


def test_listening_without_a_target_hears_creatures_not_every_object(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await place(maker)
        async with maker() as s:
            ctx = await crowd(s)
            heard = {c.subject_id for c in await observe_known_scene(ctx, "hearing")}
            assert "rats" in heard and "wall" not in heard
        await engine.dispose()

    asyncio.run(run())


def test_observing_a_named_target_reports_only_that_target(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await place(maker)
        async with maker() as s:
            ctx = await crowd(s)
            seen = {c.subject_id for c in await observe_known_scene(ctx, "general", "wall")}
            assert seen == {"wall"}
        await engine.dispose()

    asyncio.run(run())


def test_speaking_to_a_creature_in_the_place_gives_the_narrator_an_addressee(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await place(maker)
        async with maker() as s:
            ctx = await crowd(s)
            s.add(
                Message(id="m", campaign_id="c", seq=1, seat_id="seat", author_user_id="u", kind="action", content="x")
            )
            await s.flush()
            intent = IntentV2(
                name="Разговор",
                source="mundane",
                resolution="automatic",
                effects=[EffectIntentV2(kind="speak", recipient_id="rats")],
            )
            action = await compile_exploration(
                ctx, intent, IntentReview(verdict="pass"), dict(source_message_id="m", source_text="x", evidence="")
            )
            result = await resolve_exploration(ctx, action, "m")
            speech = [c for c in result.changes if c.kind == "speech"]
            assert len(speech) == 1 and speech[0].subject_id == "rats" and "Крысы" in speech[0].description
            assert "Стена" not in result.description
        await engine.dispose()

    asyncio.run(run())
