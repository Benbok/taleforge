import asyncio

from app.core.universal.effects import start_effect
from app.core.universal.exploration_resolution import public_exploration_facts, resolve_exploration
from app.core.universal.objects import apply_object_operation, expire_temporary_object
from app.core.universal.perception import assess_detection, introduce_observer, observe_known_scene
from app.core.universal.resolution import ResolutionContext
from app.db.models import Character, Entity, Event
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2, IntroductionV2
from tests.test_exploration_resolution import prepare
from tests.test_universal_resolution import setup


def test_remote_expiry_and_expired_props_are_not_current_public_facts(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add(Entity(id="place", campaign_id="c", kind="location", name="Зал", description="Зал."))
            (await s.get(Character, "hero")).location_id = "place"
            (await s.get(Character, "target")).location_id = "remote"
            event = Event(id="remote-event", campaign_id="c", actor_id="target", tool="universal_action", payload={})
            own = Event(id="own-event", campaign_id="c", actor_id="hero", tool="universal_action", payload={})
            s.add_all([event, own])
            await s.flush()
            await start_effect(
                s,
                "c",
                "target",
                "target",
                event.id,
                "remote",
                EffectIntentV2(kind="illumination", label="SECRET-REMOTE"),
                0,
                6,
            )
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            cup = await apply_object_operation(ctx, EffectIntentV2(kind="create_object", lifetime="timed"), own)
            await expire_temporary_object(s, "c", cup.subject_id)
            assert cup.subject_id not in [c.subject_id for c in await observe_known_scene(ctx, "sight")]
            action = await prepare(s, ctx, "wait", source="mundane")
            outcome = await resolve_exploration(ctx, action, "m")
            assert "SECRET-REMOTE" not in str(public_exploration_facts(outcome))
        await engine.dispose()

    asyncio.run(run())


def test_newly_introduced_watcher_keeps_identity_and_expiry_reveals_form(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add(
                Entity(id="place", campaign_id="c", kind="location", name="Зал", description="Страж смотрит на героя.")
            )
            (await s.get(Character, "hero")).location_id = "place"
            await s.flush()
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([20, 20]))
            observer = await introduce_observer(
                ctx,
                IntroductionV2(
                    ref="guard", template="observer", name="Страж", evidence_quote="Страж смотрит на героя."
                ),
            )
            event = Event(id="cast", campaign_id="c", actor_id="hero", tool="universal_action", payload={})
            s.add(event)
            await s.flush()
            await start_effect(s, "c", "hero", "hero", event.id, "form", EffectIntentV2(kind="change_form"), 0, 6)
            await start_effect(s, "c", "hero", "hero", event.id, "mask", EffectIntentV2(kind="camouflage"), 0, 6)
            assert not (await assess_detection(ctx, observer.id, "hero", "seen")).data["concealed"]
            observer.state = {
                **observer.state,
                "cover_available": False,
                "exploration_observer": {"wis": "10", "notices": {"hero": "concealed"}},
            }
            action = await prepare(s, ctx, "wait", source="mundane")
            result = await resolve_exploration(ctx, action, "m")
            assert any(c.kind == "detection" for c in result.changes)
            assert observer.state["exploration_observer"]["notices"]["hero"] == "detected"
        await engine.dispose()

    asyncio.run(run())
