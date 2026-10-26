import asyncio

import pytest

from app.core.universal.combat import run_exchange
from app.core.universal.exploration_resolution import resolve_exploration
from app.core.universal.profiles import load_actor, save_actor
from app.core.universal.resolution import ResolutionContext
from app.db.models import Character
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2
from tests.test_exploration_resolution import prepare
from tests.test_universal_combat_actions import attack
from tests.test_universal_exchange import enemy
from tests.test_universal_resolution import setup


def test_npc_saving_preserves_private_lifecycle_and_inventory(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            foe = await enemy(s)
            extras = dict(vitality=dict(state="dead", failures=3), inventory_initialized=True)
            foe.state = {**foe.state, "resources": {**foe.state["resources"], **extras}}
            sh, res = await load_actor(s, "c", foe.id)
            await save_actor(s, "c", foe.id, sh, res)
            assert all(foe.state["resources"].get(k) == v for k, v in extras.items())
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("flag,value", [("visibility", "private"), ("secret", True), ("hidden", True)])
def test_target_visibility_rechecked_at_execution(tmp_path, flag, value):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            foe = await enemy(s)
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([15, 4]))
            action = await attack(s, ctx, [EffectIntentV2(kind="damage")], targets=["foe"])
            foe.state = {**foe.state, flag: value}
            await s.flush()
            result = await resolve_exploration(ctx, action, "attack")
            assert result.status == "denied"
        await engine.dispose()

    asyncio.run(run())


def test_observer_enemy_can_reply(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            foe = await enemy(s)
            foe.state = {**foe.state, "exploration_observer": dict(wis="10", notices={"hero": "witness"})}
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([20, 3, 3]))
            action = await prepare(s, ctx, "wait", source="mundane")
            results = await run_exchange(ctx, action, request_key="m")
            assert len(results) == 2
            assert (await s.get(Character, "hero")).resources["hp"] != "22"
        await engine.dispose()

    asyncio.run(run())


def test_remote_combat_does_not_regenerate_and_stunned_foe_keeps_combat(tmp_path):
    from app.db.models import Entity, Scene

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add_all(
                [
                    Entity(id="remote", campaign_id="c", kind="location", name="remote"),
                    Entity(id="local", campaign_id="c", kind="location", name="local"),
                ]
            )
            await s.flush()
            foe = await enemy(s)
            foe.location_id = "remote"
            target = await s.get(Character, "target")
            target.location_id = "remote"
            target.resources = {**target.resources, "energies": {**target.resources["energies"], "wis": "0"}}
            hero = await s.get(Character, "hero")
            hero.location_id = "local"
            s.add(Scene(campaign_id="c", mode="combat", location_id="remote"))
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            action = await prepare(s, ctx, "wait", source="mundane")
            await run_exchange(ctx, action, request_key="m")
            assert (await s.get(Character, "target")).resources["energies"]["wis"] == "0"
            assert (await s.get(Scene, "c")).mode == "combat"
        await engine.dispose()

    asyncio.run(run())


def test_bound_hero_cannot_melee_distant_enemy(tmp_path):
    from app.core.universal.effects import start_effect
    from app.core.universal.inventory import create_item
    from app.db.models import Event
    from app.rules.universal.items import ItemProfile

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            foe = await enemy(s)
            foe.zone = "far"
            weapon = await create_item(
                s, "c", "hero", ItemProfile(name="Sword", kind="weapon"), "weapon", equipped=True
            )
            s.add(Event(id="binding", campaign_id="c", actor_id="hero", tool="universal_action", payload={}))
            await s.flush()
            await start_effect(s, "c", "hero", "hero", "binding", "bound", EffectIntentV2(kind="cannot_move"), 0, 18)
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            with pytest.raises(ValueError):
                await attack(
                    s, ctx, [EffectIntentV2(kind="weapon_attack", object_id=weapon.id)], targets=["foe"], source="item"
                )
        await engine.dispose()

    asyncio.run(run())


def test_deferred_form_is_present_for_detection_and_expiry_reassesses(tmp_path):

    from app.db.models import Entity

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            observer = Entity(
                id="watch",
                campaign_id="c",
                kind="creature",
                name="Watcher",
                state={"exploration_observer": {"wis": "10", "notices": {}}},
            )
            s.add(observer)
            await s.flush()
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([20]))
            action = await prepare(s, ctx, "change_form")
            result = await run_exchange(ctx, action, request_key="m")
            detections = [c for c in result[0].changes if c.kind == "detection"]
            assert detections[0].data["concealed"]
            ctx.dice = FixedDice([])
            from app.db.models import Message

            (await s.get(Message, "m")).seq = 0
            await s.flush()
            action = await prepare(s, ctx, "wait", source="mundane", mid="wait")
            action.elapsed_game_seconds = 18
            result = await run_exchange(ctx, action, request_key="wait")
            assert any(c.kind == "detection" and not c.data["concealed"] for c in result[0].changes)
        await engine.dispose()

    asyncio.run(run())


def test_pending_equipment_binding_survives_reconnect(tmp_path):
    from app.core.universal.exploration_views import exploration_game_card
    from app.db.models import CombatExchange

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            action = await prepare(s, ctx, "guard", source="mundane")
            from app.db.models import Message

            message = await s.get(Message, "m")
            binding = dict(kind="guard", request_key="original-key", item_id=None, target_id=None)
            message.intent = {"item_control": binding}
            s.add(
                CombatExchange(
                    campaign_id="c",
                    source_key="m",
                    actor_id="hero",
                    status="reply_pending",
                    proposal=action.model_dump(mode="json"),
                    sequence="1",
                    started_seconds="0",
                    elapsed_seconds="6",
                )
            )
            await s.commit()
        async with maker() as s:
            card = await exploration_game_card(s, await s.get(Character, "hero"))
            assert card["combat"]["pending_request"] == binding
        await engine.dispose()

    asyncio.run(run())


def test_incapacitated_hero_can_only_passively_wait(tmp_path):
    from app.core.universal.effects import active_effects, start_effect
    from app.db.models import Event

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add(Event(id="stun", campaign_id="c", actor_id="hero", tool="universal_action", payload={}))
            await s.flush()
            await start_effect(s, "c", "hero", "hero", "stun", "stun", EffectIntentV2(kind="cannot_act"), 0, 6)
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            action = await prepare(s, ctx, "wait", source="mundane")
            result = await run_exchange(ctx, action, request_key="m")
            assert result[0].status == "applied"
            assert not await active_effects(s, "c", "hero")
        await engine.dispose()

    asyncio.run(run())


def test_combat_publication_refreshes_every_seated_hero(tmp_path):
    from app.core.universal.publication import publish_game_state
    from app.db.models import Campaign, Seat

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add(Seat(id="seat2", campaign_id="c", role="player", position=2, user_id="u", occupant_type="human"))
            target = await s.get(Character, "target")
            target.seat_id = "seat2"
            await s.commit()

            class Bus:
                def __init__(self):
                    self.sent = []

                async def publish(self, cid, event, audience):
                    self.sent.append((event, audience))

            bus = Bus()
            await publish_game_state(s, bus, await s.get(Campaign, "c"))
            sheets = [audience for event, audience in bus.sent if event["type"] == "character.sheet"]
            assert ["seat"] in sheets and ["seat2"] in sheets
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("state", [{"secret": True}, {"visibility": "private"}])
def test_hidden_enemy_absent_from_scene_combat_and_completion(tmp_path, state):
    from app.core.campaigns import Viewer
    from app.core.universal.effects import scope_changes
    from app.core.universal.exploration_views import exploration_game_card
    from app.core.universal.scene import universal_scene
    from app.db.models import Campaign, Scene, Seat, User
    from app.rules.universal.exploration import EffectChange

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            foe = await enemy(s)
            foe.state = {**foe.state, **state}
            s.add(Scene(campaign_id="c", mode="combat"))
            await s.flush()
            hero = await s.get(Character, "hero")
            viewer = Viewer(await s.get(User, "u"), await s.get(Campaign, "c"), await s.get(Seat, "seat"))
            card = await exploration_game_card(s, hero)
            assert not card["combat"]["enemies"]
            scene = await universal_scene(s, viewer.campaign, viewer)
            assert not any(row["id"] == "foe" for row in scene["entities"])
            assert scene["mode"] == "free"
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            changes = await scope_changes(
                ctx, [EffectChange(kind="periodic_damage", subject_id="foe", description="Secret foe")]
            )
            assert changes[0].private
        await engine.dispose()

    asyncio.run(run())


def test_visible_unprofiled_foe_is_selectable_without_mutating_on_read(tmp_path):
    from app.core.universal.exploration_views import exploration_game_card
    from app.db.models import Entity

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            foe = Entity(id="new-foe", campaign_id="c", kind="creature", name="Foe", state={"hostile": True})
            s.add(foe)
            await s.flush()
            card = await exploration_game_card(s, await s.get(Character, "hero"))
            assert card["combat"]["enemies"][0]["id"] == "new-foe"
            assert "universal_sheet" not in foe.state
        await engine.dispose()

    asyncio.run(run())
