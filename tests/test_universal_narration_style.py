import asyncio
import json

from app.agents.master.service import MasterService
from app.core.campaigns import Viewer
from app.core.inspect import entity_card
from app.core.universal.scene import universal_scene
from app.db.models import Campaign, Entity, MasterTurn, Message, User
from tests.test_universal_location_knowledge import place
from tests.test_universal_master import Bus, Provider, prepare
from tests.test_universal_resolution import setup


def test_generated_entry_is_not_presented_as_the_campaign_title(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await place(maker)
        async with maker() as s:
            campaign = await s.get(Campaign, "c")
            location = await s.get(Entity, "gorge")
            location.name, location.state = campaign.name, {"studio_entry": True}
            await s.commit()
            viewer = Viewer(await s.get(User, "u"), campaign, next(x for x in campaign.seats if x.id == "seat"))
            scene = await universal_scene(s, campaign, viewer)
            assert scene["location"]["name"] != campaign.name
            assert (await entity_card(s, viewer, "gorge"))["name"] == scene["location"]["name"]
            assert location.name == campaign.name  # Existing world data is not rewritten.
        await engine.dispose()

    asyncio.run(run())


def test_narration_has_visible_story_context_and_preserves_literary_paragraphs(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        await place(maker)
        async with maker() as s:
            source = await s.get(Message, "source")
            source.seq = 10
            campaign = await s.get(Campaign, "c")
            campaign.last_seq = 10
            for mid, seq, text, audience, data in [
                ("public", 2, "На камнях осела сизая пыль.", None, {}),
                ("party", 3, "Из тоннеля слышится сухой стук.", ["seat"], {"scope": "party"}),
                ("whisper", 4, "PRIVATE-WHISPER", ["seat", "master"], {"whisper_reply": "question"}),
                ("other", 5, "OTHER-GROUP-SECRET", ["other-seat"], {"scope": "party"}),
                ("untagged", 6, "UNTAGGED-PRIVATE", ["seat", "master"], {}),
            ]:
                s.add(
                    Message(
                        id=mid, campaign_id="c", seq=seq, kind="narration", content=text, visible_to=audience, data=data
                    )
                )
            await s.commit()
        prose = (
            "Сизая пыль тихо оседает на разбитые камни. За стеной тумана темнеет проём тоннеля.\n\n"
            "Сухой стук звучит оттуда всё отчётливее; короткие удары отзываются под каменными сводами."
        )
        provider = Provider(
            [
                dict(
                    schema_version=2,
                    source="mundane",
                    player_request="ordinary",
                    resolution="automatic",
                    effects=[dict(kind="observe")],
                ),
                prose,
                dict(verdict="pass"),
            ]
        )
        tid = await MasterService(maker, Bus(), provider).run_turn("c")
        payload = json.loads(provider.prompts[-2][-1]["content"])
        assert payload["recent_history"] == ["На камнях осела сизая пыль.", "Из тоннеля слышится сухой стук."]
        decision = json.loads(provider.prompts[0][-1]["content"])
        assert decision["history"] == payload["recent_history"]
        assert "PRIVATE-WHISPER" not in str(provider.prompts[-1])
        assert "OTHER-GROUP-SECRET" not in str(provider.prompts[-1])
        assert "UNTAGGED-PRIVATE" not in str(provider.prompts[-1])
        async with maker() as s:
            turn = await s.get(MasterTurn, tid)
            assert turn.status == "done", turn.trace
            narration = await s.get(Message, turn.narration_message_id)
            assert len(narration.content.split("\n\n")) == 2
        await engine.dispose()

    asyncio.run(run())
