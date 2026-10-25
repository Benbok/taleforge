import asyncio

from app.core.universal.clock import complete_step
from app.core.universal.effects import active_effects, dismiss_effect, start_effect
from app.core.universal.perception import actor_constraints, assess_detection, illumination_view, stealth_edge
from app.core.universal.resolution import ResolutionContext
from app.db.models import Entity, Event
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2
from tests.test_universal_resolution import setup


def test_camouflage_edge_is_single_conditional_and_does_not_erase_witness():
    effects = [dict(kind="camouflage"), dict(kind="camouflage")]
    assert stealth_edge(effects, dict(cover=True, direct_witness=False)) == "advantage"
    assert stealth_edge(effects, dict(cover=False, direct_witness=False)) == "normal"
    assert stealth_edge(effects, dict(cover=True, direct_witness=True)) == "normal"


def test_form_light_and_private_detection_survive_and_expire(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            event = Event(id="event", campaign_id="c", actor_id="hero", tool="universal_action", payload={})
            s.add(event)
            s.add(
                Entity(
                    id="observer",
                    campaign_id="c",
                    kind="creature",
                    name="Свидетель",
                    state={"exploration_observer": {"wis": "14", "notices": {}}, "hidden": True},
                )
            )
            await s.flush()
            form = await start_effect(
                s, "c", "hero", "hero", event.id, "form", EffectIntentV2(kind="change_form"), 0, 18
            )
            await start_effect(
                s,
                "c",
                "hero",
                "hero",
                event.id,
                "mask",
                EffectIntentV2(kind="camouflage"),
                0,
                18,
                context={"requires_form": True},
            )
            await start_effect(s, "c", "hero", "hero", event.id, "light", EffectIntentV2(kind="illumination"), 0, 18)
            constraints = await actor_constraints(s, "c", "hero")
            assert not constraints["can_move"] and not constraints["can_speak"] and constraints["can_see"]
            assert constraints["needs_air"] and not constraints["immune"]
            assert (await illumination_view(s, "c", "hero"))["magical_light"]
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([1, 20]))
            result = await assess_detection(ctx, "observer", "hero", "detection1")
            assert result.private and result.data["natural"] == 20 and result.data["concealed"]
            assert "difficulty" not in result.data
            # A direct witness remembers even on natural20.
            observer = await s.get(Entity, "observer")
            observer.state = {**observer.state, "exploration_observer": {"wis": "14", "notices": {"hero": "witness"}}}
            ctx.dice = FixedDice([20])
            assert not (await assess_detection(ctx, "observer", "hero", "detection2")).data["concealed"]
            await dismiss_effect(s, "c", "hero", form.id)
            assert (await actor_constraints(s, "c", "hero"))["can_speak"]
            assert [e["kind"] for e in await active_effects(s, "c", "hero")] == ["illumination"]
            await complete_step(s, "c", "wait", 18)
            assert not (await illumination_view(s, "c", "hero"))["magical_light"]
        await engine.dispose()

    asyncio.run(run())
