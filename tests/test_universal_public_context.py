import asyncio

from app.db.models import Campaign, Character, Entity, KnownFact, Message, Seat
from tests.test_universal_location_knowledge import place
from tests.test_universal_master import prepare
from tests.test_universal_resolution import setup


def test_public_context_intersects_knowledge_and_reuses_ranked_memory(tmp_path):
    async def run():
        from app.agents.master.public_context import public_context

        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await place(maker)
        async with maker() as s:
            s.add(Seat(id="second", campaign_id="c", role="player", position=2, user_id="u", occupant_type="human"))
            await s.flush()
            target = await s.get(Character, "target")
            target.seat_id, target.location_id = "second", "gorge"
            s.add(
                Entity(
                    id="secret",
                    campaign_id="c",
                    kind="object",
                    name="PRIVATE-ENTITY",
                    location_id="gorge",
                    state={"secret": True},
                )
            )
            for hero in ["hero", "target"]:
                s.add(
                    KnownFact(campaign_id="c", character_id=hero, subject_id="gorge", text="The bell warns of floods.")
                )
            s.add(KnownFact(campaign_id="c", character_id="hero", subject_id="gorge", text="PRIVATE-FACT"))
            s.add(KnownFact(campaign_id="c", character_id="hero", subject_id="secret", text="PRIVATE-ENTITY-FACT"))
            s.add(
                Message(campaign_id="c", seq=2, kind="speech", content="Listen for the bell.", data={}, visible_to=None)
            )
            s.add(
                Message(
                    campaign_id="c",
                    seq=3,
                    kind="speech",
                    content="PRIVATE-DIALOGUE",
                    data={"scope": "private"},
                    visible_to=["seat"],
                )
            )
            await s.flush()
            scene = {
                "location": {"id": "gorge", "name": "Gorge", "description": "The bell echoes."},
                "entities": [{"id": "secret", "name": "PRIVATE-ENTITY"}],
                "private_counter": "PRIVATE-COUNTER",
            }
            context = await public_context(
                s,
                await s.get(Campaign, "c"),
                10,
                ["seat", "second"],
                scene,
                {
                    "source": {
                        "description": "PRIVATE-DETAIL",
                        "changes": [
                            {"kind": "observation", "subject_id": "secret", "description": "PRIVATE-DETAIL"},
                            {"kind": "damage", "subject_id": "hero", "description": "Damage applied."},
                            {"kind": "resisted", "subject_id": "hero", "description": "Binding resisted."},
                        ],
                    }
                },
            )
            assert context["knowledge"] == [{"subject_id": "gorge", "text": "The bell warns of floods."}]
            assert context["recent_history"] == ["Listen for the bell."]
            assert "PRIVATE" not in str(context)
            assert context["scene"]["entities"] == []
            assert [c["kind"] for c in context["outcomes"]["source"]["changes"]] == ["damage", "resisted"]
        await engine.dispose()

    asyncio.run(run())


def test_observing_does_not_discover_secret_entities(tmp_path):
    async def run():
        from app.core.universal.perception import observe_known_scene
        from app.core.universal.resolution import ResolutionContext
        from app.rules.dice import FixedDice

        engine, maker = await setup(tmp_path)
        await place(maker)
        async with maker() as s:
            s.add(
                Entity(
                    id="secret",
                    campaign_id="c",
                    kind="object",
                    name="PRIVATE-ENTITY",
                    description="PRIVATE-DETAIL",
                    location_id="gorge",
                    state={"secret": True},
                )
            )
            await s.flush()
            changes = await observe_known_scene(ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([])), "look")
            assert "PRIVATE" not in str(changes)
        await engine.dispose()

    asyncio.run(run())


def test_retry_uses_saved_public_context_without_replaying_action(tmp_path):
    async def run():
        import json

        from sqlalchemy import select

        from app.agents.master.service import MasterService
        from app.db.models import Event, MasterTurn
        from tests.test_universal_master import Bus, Provider

        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await place(maker)
        provider = Provider(
            [
                dict(
                    schema_version=2,
                    source="mundane",
                    player_request="ordinary",
                    resolution="automatic",
                    effects=[dict(kind="observe")],
                ),
                RuntimeError("offline"),
            ]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        initial = json.loads(provider.prompts[-1][-1]["content"])
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "failed"
            assert turn.trace["public_context"]["scene"] == initial["scene"]
            before = len(list(await s.scalars(select(Event))))
            (await s.get(Entity, "gorge")).description = "LATER-DETAIL"
            await s.commit()
        retry = Provider(["The mist drifts over the stones.", dict(verdict="pass")])
        assert await MasterService(maker, Bus(), retry).run_turn("c") == tid
        replay = json.loads(retry.prompts[0][-1]["content"])
        assert replay == initial
        assert "LATER-DETAIL" not in str(retry.prompts)
        async with maker() as s:
            assert (await s.get(MasterTurn, tid)).status == "done"
            assert len(list(await s.scalars(select(Event)))) == before
        await engine.dispose()

    asyncio.run(run())


def test_roll_card_does_not_share_one_heros_revealed_secret(tmp_path):
    async def run():
        from app.core.universal.exploration_resolution import resolve_exploration
        from app.core.universal.resolution import ResolutionContext
        from app.core.universal.rolls import ensure_roll_message
        from app.db.models import Knowledge, now
        from app.rules.dice import FixedDice
        from tests.test_exploration_resolution import prepare as action_for

        engine, maker = await setup(tmp_path)
        await place(maker)
        async with maker() as s:
            s.add(Seat(id="second", campaign_id="c", role="player", position=2, user_id="u", occupant_type="human"))
            await s.flush()
            other = await s.get(Character, "target")
            other.seat_id, other.location_id = "second", "gorge"
            s.add(
                Entity(
                    id="secret",
                    campaign_id="c",
                    kind="object",
                    name="Secret",
                    description="PRIVATE-DETAIL",
                    location_id="gorge",
                    state={"secret": True},
                )
            )
            await s.flush()
            s.add(Knowledge(character_id="hero", entity_id="secret", revealed_at=now()))
            await s.flush()
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            action = await action_for(s, ctx, "observe", source="mundane")
            result = await resolve_exploration(ctx, action, "m")
            assert "PRIVATE-DETAIL" in result.description
            (await s.get(Campaign, "c")).last_seq = 1
            card = await ensure_roll_message(s, "c", None, None, "m", ["seat", "second"])
            assert "PRIVATE-DETAIL" not in str(card.data)
        await engine.dispose()

    asyncio.run(run())
