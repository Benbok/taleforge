import asyncio

from app.agents.master.service import MasterService
from app.core.campaigns import Viewer
from app.core.chat import message_payload
from app.core.inspect import entity_card
from app.core.universal.references import project_history
from app.db.models import Campaign, Character, Entity, MasterTurn, Message, User
from tests.test_universal_master import Bus, Provider, prepare, seed_legacy
from tests.test_universal_resolution import setup


async def place(maker):
    async with maker() as s:
        s.add(Entity(id="gorge", campaign_id="c", kind="location", name="Серая Глотка", description="Сырое ущелье."))
        (await s.get(Character, "hero")).location_id = "gorge"
        await s.commit()


def test_narration_links_known_location_and_drops_unknown_references(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await place(maker)
        provider = Provider([dict(kind="narrative"), "Среди обломков Серой Глотки слышится [[private-place|стук]]."])
        await seed_legacy(maker, provider.replies.pop(0))
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "done", turn.trace
            message = await s.get(Message, turn.narration_message_id)
            assert "[[gorge|Серой Глотки]]" in message.content
            assert "private-place" not in message.content
        await engine.dispose()

    asyncio.run(run())


def test_location_knowledge_accumulates_all_public_observations_without_foreign_whispers(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await place(maker)
        async with maker() as s:
            for i in range(7):
                s.add(
                    Message(
                        id=f"story{i}",
                        campaign_id="c",
                        seq=i + 2,
                        kind="narration",
                        content=f"В [[gorge|Серой Глотке]] найден след номер {i}.",
                    )
                )
            s.add(
                Message(
                    id="secret",
                    campaign_id="c",
                    seq=9,
                    kind="narration",
                    content="В [[gorge|Серой Глотке]] скрыт SECRET-PASSAGE.",
                    visible_to=["other-seat"],
                )
            )
            old = Message(
                id="old-story",
                campaign_id="c",
                seq=10,
                kind="narration",
                content="У тоннеля появился мост.",
                data={"universal": True},
            )
            s.add(old)
            s.add(
                MasterTurn(
                    id="old-turn",
                    campaign_id="c",
                    session_id="game",
                    upto_seq=10,
                    status="done",
                    narration_message_id="old-story",
                    trace={"universal": True, "scene": {"location": {"id": "gorge", "name": "Серая Глотка"}}},
                )
            )
            await s.commit()
            campaign = await s.get(Campaign, "c")
            user = await s.get(User, "u")
            viewer = Viewer(user, campaign, next(x for x in campaign.seats if x.id == "seat"))
            card = await entity_card(s, viewer, "gorge")
            assert len(card["heard"]) == 8
            assert "номер 0" in card["heard"][0] and "мост" in card["heard"][-1]
            assert "SECRET-PASSAGE" not in str(card)
            projected = await project_history(s, campaign, [old], [message_payload(old)])
            assert projected[0]["data"]["location_ref"]["id"] == "gorge"
            assert "location_ref" not in old.data  # Read-only legacy projection.
        await engine.dispose()

    asyncio.run(run())


def test_location_reference_remains_accessible_after_leaving_without_revealing_new_state(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await place(maker)
        await seed_legacy(maker, dict(kind="narrative"))
        await MasterService(maker, Bus(), Provider(["У тоннеля появился мост."])).run_turn("c")
        async with maker() as s:
            (await s.get(Character, "hero")).location_id = "elsewhere"
            (await s.get(Entity, "gorge")).description = "SECRET-UNOBSERVED-CHANGE"
            await s.commit()
            campaign = await s.get(Campaign, "c")
            viewer = Viewer(await s.get(User, "u"), campaign, next(x for x in campaign.seats if x.id == "seat"))
            card = await entity_card(s, viewer, "gorge")
            assert "мост" in str(card["heard"])
            assert card["description"] == "Сырое ущелье."
            assert "SECRET-UNOBSERVED-CHANGE" not in str(card)
            assert card["memory"] is True
        await engine.dispose()

    asyncio.run(run())


def test_mixed_turn_keeps_technical_notice_out_of_location_knowledge(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await place(maker)
        notice = "Этот эффект пока не поддерживается движком. Ресурсы не потрачены."
        async with maker() as s:
            s.add(
                Message(
                    id="mixed",
                    campaign_id="c",
                    seq=2,
                    kind="narration",
                    content="У тоннеля появился мост.\n\n" + notice,
                )
            )
            s.add(
                MasterTurn(
                    id="mixed-turn",
                    campaign_id="c",
                    session_id="game",
                    upto_seq=2,
                    status="done",
                    narration_message_id="mixed",
                    trace={
                        "universal": True,
                        "scene": {"location": {"id": "gorge"}},
                        "outcomes": {
                            "one": {"success": True},
                            "two": {"failure": {"category": "unsupported_capability", "message": notice}},
                        },
                    },
                )
            )
            await s.commit()
            campaign = await s.get(Campaign, "c")
            viewer = Viewer(await s.get(User, "u"), campaign, next(x for x in campaign.seats if x.id == "seat"))
            card = await entity_card(s, viewer, "gorge")
            assert card["heard"] == ["У тоннеля появился мост."]
        await engine.dispose()

    asyncio.run(run())
