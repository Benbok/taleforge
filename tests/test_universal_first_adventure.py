"""The first playable adventure through real authoring, admission and transport boundaries."""

import asyncio

from sqlalchemy import select

from app.agents.llm import ScriptedLLM
from app.agents.master.service import MasterService
from app.core.universal.profiles import load_actor
from app.db.models import Campaign, CampaignSecret, Entity, Event, HeroAbility, MasterTurn, RuntimeProfile
from app.db.session import make_engine, make_sessionmaker
from app.rules.dice import FixedDice
from tests.test_universal_master import Bus, Provider
from tests.test_universal_studio import BASE, FIELDS, create, review_reply
from tests.test_ws import connect, wait_message_result
from tests.universal_helpers import create_hero, ready_reply, set_replies


def first_adventure_scenario(client, root, settings, monkeypatch, voice_capture=None):
    # No worker races and no external calls: the real turn executor is driven explicitly below.
    monkeypatch.setattr(client.app.state.master, "notify", lambda *_: None)
    monkeypatch.setattr(client.app.state.master, "schedule_session_open", lambda *_: None)
    library_id = create_hero(client, root)
    library_before = client.get("/api/me/characters", headers=root).json()
    project = create(client, root)
    studio = f"{BASE}/{project['id']}/studio"
    fields = {**FIELDS, "laws": "Plant magic exists. SECRET-LAW: the captain cannot leave the island."}
    saved = client.put(studio, headers=root, json={"expected_revision": project["draft_revision"], "fields": fields})
    assert saved.status_code == 200, saved.text
    revision = saved.json()["draft_revision"]
    client.app.state.studio_llm = ScriptedLLM([review_reply()])
    review = client.post(studio + "/review", headers=root, json={"expected_revision": revision})
    assert review.status_code == 200 and review.json()["status"] == "ready", review.text
    accepted = client.post(
        studio + "/accept", headers=root, json={"expected_revision": revision, "request_key": "accept"}
    )
    assert accepted.status_code == 201, accepted.text
    version = accepted.json()["id"]
    options = {
        "name": "First adventure",
        "owner_plays": True,
        "tts_enabled": False,
        "master": {"type": "agent", "provider": "claude", "model": "x"},
    }
    launched = client.post(
        f"/api/adventures/{version}/games", headers=root, json={"options": options, "request_key": "first-game"}
    )
    assert launched.status_code == 201, launched.text
    cid = launched.json()["campaign_id"]
    assert (
        client.post(
            f"/api/adventures/{version}/games", headers=root, json={"options": options, "request_key": "first-game"}
        ).json()
        == launched.json()
    )
    second = client.post(
        f"/api/adventures/{version}/games", headers=root, json={"options": options, "request_key": "second-game"}
    )
    assert second.status_code == 201, second.text
    second_id = second.json()["campaign_id"]
    assert second_id != cid
    set_replies(client, [ready_reply()])
    admission = client.post(f"/api/campaigns/{cid}/characters/from-library/{library_id}/admission", headers=root)
    assert admission.status_code == 201, admission.text
    draft = admission.json()
    confirmation = client.post(
        f"/api/hero-creation/dialogues/{draft['id']}/confirm",
        headers=root,
        json={"expected_revision": draft["revision"]},
    )
    assert confirmation.status_code == 200, confirmation.text
    hero_id = confirmation.json()["hero_id"]
    started = client.post(f"/api/campaigns/{cid}/session/start", headers=root)
    assert started.status_code == 200 and started.json()["status"] == "active", started.text

    async def inspect(maker):
        async with maker() as session:
            sheet, resources = await load_actor(session, cid, hero_id)
            events = list(await session.scalars(select(Event).where(Event.campaign_id == cid)))
            learned = list(await session.scalars(select(HeroAbility).where(HeroAbility.campaign_id == cid)))
            return sheet, resources, events, learned

    maker = client.app.state.sessionmaker
    before_sheet, before_resources, _, _ = asyncio.run(inspect(maker))
    assert before_sheet.level == 1 and before_sheet.xp == 0
    with connect(client, root, cid) as (ws, snapshot):
        assert snapshot["payload"]["scene"]["location"]["description"]
        ws.send_json(
            {
                "type": "message.send",
                "payload": {"kind": "action", "text": "Investigate the harbor gate.", "client_id": "investigate"},
            }
        )
        assert wait_message_result(ws, client_id="investigate")["type"] == "message.new"
    free = Provider(
        [
            dict(
                schema_version=2,
                source="mundane",
                player_request="ordinary",
                resolution="automatic",
                attribute="int",
                effects=[dict(kind="observe")],
            ),
            "The gate bears a fresh trail.",
            dict(verdict="pass"),
        ]
    )
    free_service = MasterService(maker, Bus(), free, dice_factory=lambda: FixedDice([10]))
    free_turn = asyncio.run(free_service.run_turn(cid))
    assert free_turn
    assert asyncio.run(inspect(maker))[1].energies == before_resources.energies
    with connect(client, root, cid) as (ws, _):
        ws.send_json(
            {
                "type": "message.send",
                "payload": {"kind": "action", "text": "Invent vine sight to follow the trail.", "client_id": "vine"},
            }
        )
        assert wait_message_result(ws, client_id="vine")["type"] == "message.new"
    ability = {
        "schema_version": 2,
        "name": "Vine sight",
        "source": "supernatural",
        "resolution": "automatic",
        "intensity": "light",
        "effects": [dict(kind="illumination")],
    }
    failed = MasterService(
        maker,
        Bus(),
        Provider([ability, dict(verdict="pass"), RuntimeError("narrator unavailable")]),
        dice_factory=lambda: FixedDice([10]),
    )
    tid = asyncio.run(failed.run_turn(cid))
    sheet, debited, events, learned = asyncio.run(inspect(maker))
    from app.rules.universal.mechanics import derive, energy_regen, starting_defense_bonuses

    top = derive(sheet, starting_defense_bonuses(sheet)).energy_max["wis"]
    # the price 3, then the energy the six seconds of that step give back, never above the pool
    assert debited.energies["wis"] == min(top, before_resources.energies["wis"] - 3 + energy_regen(top))
    assert len([e for e in events if e.tool != "universal_catchup"]) == 2 and len(learned) == 1

    async def assert_failed():
        async with maker() as session:
            turn = await session.get(MasterTurn, tid)
            assert turn.status == "failed", turn.trace

    asyncio.run(assert_failed())

    # Reopen the same persisted database through a fresh engine/maker and master service.
    restarted_engine = make_engine(settings.database_url)
    restarted_maker = make_sessionmaker(restarted_engine)
    narrator = Provider(["Vines trace the hidden path beyond the gate.", dict(verdict="pass")])

    class CapturedVoice:
        enabled = True

        async def voice_for_narration(self, media_dir, cid, text, **kwargs):
            voice_capture.append(text)
            return None

    if voice_capture is not None:

        async def enable_voice():
            async with restarted_maker() as s:
                campaign = await s.get(Campaign, cid)
                campaign.settings = {**campaign.settings, "tts_enabled": True, "tts_text_enabled": True}
                await s.commit()

        asyncio.run(enable_voice())
    from pathlib import Path

    restarted = MasterService(
        restarted_maker,
        Bus(),
        narrator,
        dice_factory=lambda: FixedDice([10]),
        tts=CapturedVoice() if voice_capture is not None else None,
        media_dir=Path("."),
    )
    assert asyncio.run(restarted.run_turn(cid)) == tid
    assert asyncio.run(restarted.run_turn(cid)) is None
    _, restored, restored_events, restored_learned = asyncio.run(inspect(restarted_maker))
    assert restored == debited
    assert len([e for e in restored_events if e.tool != "universal_catchup"]) == 2 and len(restored_learned) == 1
    assert "SECRET-LAW" not in str(narrator.prompts)
    with connect(client, root, cid, last_seq=0) as (_, snapshot):
        payload = snapshot["payload"]
        assert payload["replay"]
        assert any("Vines trace" in row["content"] for row in payload["messages"])
        assert payload["scene"]["location"]["description"]
        assert "SECRET-LAW" not in str(payload)
    card = client.get(f"/api/campaigns/{cid}/characters/{hero_id}", headers=root)
    assert card.status_code == 200, card.text
    assert len(card.json()["learned_abilities"]) == 1
    assert client.get("/api/me/characters", headers=root).json() == library_before

    async def isolated():
        async with restarted_maker() as session:
            ids = [
                set(await session.scalars(select(Entity.id).where(Entity.campaign_id == game)))
                for game in (cid, second_id)
            ]
            assert ids[0] and ids[0].isdisjoint(ids[1])
            secret = await session.get(CampaignSecret, second_id)
            assert secret.setting["studio"] == fields
            assert not list(
                await session.scalars(select(RuntimeProfile).where(RuntimeProfile.campaign_id == second_id))
            )
            assert not list(await session.scalars(select(HeroAbility).where(HeroAbility.campaign_id == second_id)))
        await restarted_engine.dispose()

    asyncio.run(isolated())
    return cid, second_id, hero_id, library_before


def test_first_adventure_survives_restart_and_failed_narration(client, root, settings, monkeypatch):
    first_adventure_scenario(client, root, settings, monkeypatch)


def test_universal_turn_uses_campaign_selected_model_and_endpoint(tmp_path):
    from app.db.models import AgentConfig, Seat
    from tests.test_universal_master import prepare
    from tests.test_universal_resolution import setup

    class RecordingProvider(Provider):
        def __init__(self):
            super().__init__(
                [
                    dict(
                        schema_version=2,
                        source="mundane",
                        player_request="ordinary",
                        resolution="automatic",
                        effects=[dict(kind="speak")],
                    ),
                    "The guard nods.",
                    dict(verdict="pass"),
                ]
            )
            self.options = []

        async def complete(self, messages, **kwargs):
            self.options.append(kwargs)
            return await super().complete(messages, **kwargs)

    async def exercise():
        engine, maker = await setup(tmp_path)
        await prepare(maker)
        async with maker() as session:
            config = AgentConfig(
                provider="local",
                model="chosen-local-model",
                temperature=0.6,
                settings={"api_base": "http://local-provider.invalid/v1"},
            )
            session.add(config)
            await session.flush()
            master = await session.get(Seat, "master")
            master.agent_config_id = config.id
            await session.commit()
        provider = RecordingProvider()
        service = MasterService(maker, Bus(), provider)
        tid = await service.run_turn("c")
        async with maker() as session:
            assert (await session.get(MasterTurn, tid)).status == "done"
        assert len(provider.options) == 3  # the decision, the story and its check
        for options in provider.options:
            from app.agents.llm import model_for

            assert options["model"] == model_for("local", "chosen-local-model")
            assert options["api_base"] == "http://local-provider.invalid/v1"
        assert provider.options[1]["temperature"] == 0.6
        await engine.dispose()

    asyncio.run(exercise())
