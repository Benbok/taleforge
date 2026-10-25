import asyncio

from sqlalchemy import select

from app.core.universal.clock import clock_view
from app.core.universal.exploration_resolution import resolve_exploration
from app.core.universal.exploration_views import exploration_game_card
from app.core.universal.interpretation import compile_exploration
from app.core.universal.resolution import ResolutionContext
from app.db.models import Character, Entity, Message, UniversalEffect
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2, IntentReview, IntentV2, IntroductionV2
from tests.test_universal_resolution import setup


def test_cup_light_form_and_reconnect_are_real_scoped_state(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add(
                Entity(
                    id="place",
                    campaign_id="c",
                    kind="location",
                    name="Руины",
                    description="Рядом лежат щепки; из стены сочится вода.",
                    state={},
                )
            )
            hero = await s.get(Character, "hero")
            hero.location_id = "place"
            await s.flush()
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            seq = 0

            async def act(ops, source="mundane", introductions=None, elapsed=6):
                nonlocal seq
                seq += 1
                mid = f"action-{seq}"
                s.add(
                    Message(
                        id=mid, campaign_id="c", seq=seq, seat_id="seat", author_user_id="u", kind="action", content=mid
                    )
                )
                await s.flush()
                action = await compile_exploration(
                    ctx,
                    IntentV2(
                        source=source,
                        name="Опыт",
                        intensity="light",
                        resolution="automatic",
                        effects=ops,
                        introductions=introductions or [],
                        elapsed_game_seconds=elapsed,
                    ),
                    IntentReview(verdict="pass"),
                    dict(source_message_id=mid, source_text=mid, evidence="Рядом лежат щепки; из стены сочится вода."),
                )
                result = await resolve_exploration(ctx, action, mid)
                assert result.status == "applied", result
                return result

            result = await act(
                [EffectIntentV2(kind="create_object", source_id="intro:wood", lifetime="permanent")],
                "supernatural",
                [
                    IntroductionV2(
                        ref="wood", template="wood_source", name="Щепки", evidence_quote="Рядом лежат щепки"
                    ),
                    IntroductionV2(
                        ref="water", template="water_source", name="Вода", evidence_quote="из стены сочится вода"
                    ),
                ],
            )
            cup = next(c.subject_id for c in result.changes if c.kind == "object_created")
            view = await exploration_game_card(s, hero)
            water = next(o["id"] for o in view["exploration"]["objects"] if o["template"] == "water_source")
            await act([EffectIntentV2(kind="fill", object_id=cup, source_id=water, amount=200)])
            await act([EffectIntentV2(kind="place", object_id=cup)])
            await act([EffectIntentV2(kind="illumination")], "supernatural")
            before = await clock_view(s, "c")
            view = await exploration_game_card(s, hero)
            assert view["editable"] is False
            assert next(o for o in view["exploration"]["objects"] if o["id"] == cup)["contents_ml"] == "200"
            assert view["exploration"]["effects"][0]["remaining_seconds"] == "18"
            assert len(view["learned_abilities"]) == 2
            assert await clock_view(s, "c") == before
            await act([EffectIntentV2(kind="change_form"), EffectIntentV2(kind="camouflage")], "supernatural")
            assert not (await exploration_game_card(s, hero))["exploration"]["constraints"]["can_speak"]
            await act([EffectIntentV2(kind="wait")], elapsed=18)
            assert not (await exploration_game_card(s, hero))["exploration"]["effects"]
            assert await s.scalar(select(UniversalEffect).where(UniversalEffect.status == "active")) is None
            await s.commit()
        async with maker() as s:
            hero = await s.get(Character, "hero")
            view = await exploration_game_card(s, hero)
            assert next(o for o in view["exploration"]["objects"] if o["id"] == cup)["contents_ml"] == "200"
            assert len(view["learned_abilities"]) == 3
        await engine.dispose()

    asyncio.run(run())
