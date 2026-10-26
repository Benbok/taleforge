import asyncio

from app.core.universal.inventory import create_item, ensure_inventory
from app.db.models import Campaign, Character, GameSession
from app.rules.universal.items import ItemProfile
from tests.test_api import make_campaign
from tests.test_universal_resolution import sheet


def test_authenticated_equipment_action_and_reconnect_preserve_actual_defense(client, root, monkeypatch):
    monkeypatch.setattr(client.app.state.master, "notify", lambda *_: None)
    game = make_campaign(client, root, owner_plays=True)
    cid = game["id"]

    async def seed():
        async with client.app.state.sessionmaker() as s:
            campaign = await s.get(Campaign, cid)
            seat = next(row for row in campaign.seats if row.role == "player")
            hero = Character(
                id="combat-hero",
                campaign_id=cid,
                seat_id=seat.id,
                owner_user_id=campaign.owner_id,
                name="Искатель",
                status="active",
                sheet=sheet().model_dump(mode="json"),
                resources=dict(hp="22", energies=dict(str="18", dex="20", int="23", wis="24", cha="25")),
            )
            s.add(hero)
            s.add(GameSession(id="combat-game", campaign_id=cid))
            await s.flush()
            await ensure_inventory(s, cid, hero.id)
            armor = await create_item(
                s, cid, hero.id, ItemProfile(name="Кираса", kind="armor", defense_bonus=3), "test-armor"
            )
            await s.commit()
            return armor.id

    item_id = asyncio.run(seed())
    endpoint = f"/api/campaigns/{cid}/characters/combat-hero/universal-actions"
    body = dict(kind="equip", item_id=item_id, request_key="equip-once")
    result = client.post(endpoint, headers=root, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["derived"]["ac"] == "15"
    assert result.json()["combat"]["inventory"][0]["equipped"]
    assert client.post(endpoint, headers=root, json=body).json()["combat"]["game_seconds"] == "6"
    loaded = client.get(f"/api/campaigns/{cid}/characters/combat-hero", headers=root)
    assert loaded.json()["derived"]["ac"] == "15"
    assert "failures" not in loaded.text and "successes" not in loaded.text
    removed = client.post(endpoint, headers=root, json=dict(kind="unequip", item_id=item_id, request_key="remove"))
    assert removed.status_code == 200 and removed.json()["derived"]["ac"] == "12"


def test_equipment_vine_reply_binding_expiry_consumable_rescue_and_reconnect(tmp_path):
    import json

    from sqlalchemy import func, select

    from app.core.universal.combat import run_exchange
    from app.core.universal.exploration_views import exploration_game_card
    from app.core.universal.interpretation import compile_exploration
    from app.core.universal.resolution import ResolutionContext
    from app.db.models import CombatExchange, Entity, Event, Message
    from app.rules.dice import FixedDice
    from app.rules.universal.exploration import EffectIntentV2, IntentReview, IntentV2
    from tests.test_universal_exchange import enemy
    from tests.test_universal_resolution import setup

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            foe = await enemy(s)
            armor = await create_item(s, "c", "hero", ItemProfile(name="Armor", kind="armor", defense_bonus=3), "armor")
            tonic = await create_item(
                s,
                "c",
                "hero",
                ItemProfile(name="Tonic", kind="consumable", restore_pool="wis", restore_amount=6),
                "tonic",
            )
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))

            async def act(
                key, kind, rolls, *, source="mundane", targets=None, effects=None, resolution="automatic", elapsed=6
            ):
                ctx.dice = FixedDice(rolls)
                from app.core.chat import next_seq

                s.add(
                    Message(
                        id=key,
                        campaign_id="c",
                        seq=await next_seq(s, "c"),
                        seat_id="seat",
                        author_user_id="u",
                        kind="action",
                        content=key,
                    )
                )
                await s.flush()
                intent = IntentV2(
                    name=key,
                    source=source,
                    resolution=resolution,
                    targets=targets or ["hero"],
                    effects=effects or [EffectIntentV2(kind=kind)],
                    elapsed_game_seconds=elapsed,
                )
                action = await compile_exploration(
                    ctx, intent, IntentReview(verdict="pass"), dict(source_message_id=key, source_text=key, evidence="")
                )
                return await run_exchange(ctx, action, request_key=key), action

            results, _ = await act("equip", "equip", [5], effects=[EffectIntentV2(kind="equip", object_id=armor.id)])
            assert len(results) == 2
            assert (await exploration_game_card(s, await s.get(Character, "hero")))["derived"]["ac"] == "15"
            results, _ = await act(
                "vine",
                "damage",
                [15, 4, 20, 5],
                source="supernatural",
                targets=["foe"],
                resolution="attack",
                effects=[EffectIntentV2(kind="damage"), EffectIntentV2(kind="cannot_move")],
            )
            assert len(results) == 2 and results[0].damage > 0 and not results[0].effect_outcomes[0].applied
            foe = await s.get(Entity, "foe")
            foe.zone = "far"
            results, _ = await act("bind", "cannot_move", [1], source="supernatural", targets=["foe"])
            assert len(results) == 1 and results[0].effect_outcomes[0].applied
            await act("wait", "wait", [], elapsed=18)
            from app.core.universal.effects import active_effects

            assert not await active_effects(s, "c", "foe")
            results, _ = await act(
                "tonic", "consume", [5], source="item", effects=[EffectIntentV2(kind="consume", object_id=tonic.id)]
            )
            assert len(results) == 2
            assert (await s.get(Character, "hero")).resources["energies"]["wis"] == "9"
            hero = await s.get(Character, "hero")
            hero.resources = {**hero.resources, "hp": "1"}
            results, last = await act("rescue", "guard", [20, 6, 6, 20])
            assert len(results) == 2
            assert (await s.get(Character, "hero")).resources["hp"] == "1"
            card = await exploration_game_card(s, await s.get(Character, "hero"))
            assert card["combat"]["life_state"] == "conscious"
            assert "successes" not in json.dumps(card) and "failures" not in json.dumps(card)
            count = await s.scalar(select(func.count()).select_from(Event))
            await s.commit()
        async with maker() as s:
            ctx.session = s
            ctx.dice = FixedDice([])
            assert (await run_exchange(ctx, last, request_key="rescue"))[0].status == "repeated"
            assert await s.scalar(select(func.count()).select_from(Event)) == count
            assert (
                await s.scalar(select(CombatExchange).where(CombatExchange.source_key == "rescue"))
            ).status == "ticks_done"
        await engine.dispose()

    asyncio.run(run())


def test_ui_consumption_resumes_after_committed_hero_crash(tmp_path, monkeypatch):
    import datetime

    from sqlalchemy import select

    from app.core.campaigns import Viewer
    from app.core.universal import ui_actions
    from app.core.universal.combat import run_exchange
    from app.core.universal.exploration_views import exploration_game_card
    from app.db.models import CombatExchange, Entity, Seat, User
    from app.rules.dice import FixedDice
    from app.rules.universal.items import GameItemAction
    from tests.test_universal_exchange import enemy
    from tests.test_universal_resolution import setup

    class Crash(BaseException):
        pass

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await enemy(s)
            hero = await s.get(Character, "hero")
            hero.resources = {**hero.resources, "hp": "10"}
            s.add(GameSession(id="game", campaign_id="c"))
            potion = await create_item(
                s,
                "c",
                "hero",
                ItemProfile(name="Potion", kind="consumable", restore_pool="hp", restore_amount=6),
                "potion",
            )
            pid = potion.id
            await s.commit()
            viewer = Viewer(await s.get(User, "u"), await s.get(Campaign, "c"), await s.get(Seat, "seat"))
            body = GameItemAction(kind="consume", item_id=pid, request_key="recover-once")

            async def crash_choice(_):
                raise Crash()

            async def interrupted(ctx, action, request_key):
                return await run_exchange(ctx, action, choose_reply=crash_choice, request_key=request_key)

            monkeypatch.setattr(ui_actions, "run_exchange", interrupted)
            import pytest

            with pytest.raises(Crash):
                await ui_actions.perform_item_action(s, viewer, hero, body, FixedDice([]))
        async with maker() as s:
            hero = await s.get(Character, "hero")
            card = await exploration_game_card(s, hero)
            assert card["combat"]["pending_request"]["request_key"] == "recover-once"
            assert hero.resources["hp"] == "16"
            exchange = await s.scalar(select(CombatExchange))
            exchange.selection_expires_at = datetime.datetime(2000, 1, 1, tzinfo=datetime.UTC)
            await s.commit()
            monkeypatch.setattr(ui_actions, "run_exchange", run_exchange)
            viewer = Viewer(await s.get(User, "u"), await s.get(Campaign, "c"), await s.get(Seat, "seat"))
            card, messages = await ui_actions.perform_item_action(s, viewer, hero, body, FixedDice([]))
            assert card["combat"]["pending_request"] is None
            assert card["combat"]["game_seconds"] == "6" and hero.resources["hp"] == "16"
            assert (await s.get(Entity, pid)).state["universal_item"]["quantity"] == "0"
            assert messages
        await engine.dispose()

    asyncio.run(run())
