"""Persistent acceptance across authoring, runtime, maps and a fresh connection."""

import asyncio
from copy import deepcopy
from dataclasses import replace

from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.core.campaigns import Viewer
from app.core.map import party_map
from app.core.universal.clock import clock_view
from app.core.universal.combat import run_exchange
from app.core.universal.effects import active_effects
from app.core.universal.exploration_views import exploration_game_card
from app.core.universal.interpretation import compile_exploration
from app.core.universal.inventory import create_item
from app.core.universal.progression import spend_points
from app.core.universal.resolution import ResolutionContext
from app.db.models import Campaign, Character, Entity, Event, Seat, User
from app.db.session import make_engine
from app.rules.dice import FixedDice
from app.rules.universal.exploration import EffectIntentV2, IntentReview, IntentV2
from app.rules.universal.items import ItemProfile
from tests.conftest import login
from tests.test_universal_first_adventure import first_adventure_scenario
from tests.test_universal_resolution import sheet
from tests.test_ws import connect


def test_whole_adventure_on_upgraded_database_isolated_and_replay_safe(settings, tmp_path, monkeypatch):
    url = f"sqlite+aiosqlite:///{tmp_path / 'migrated.db'}"

    async def migrate():
        engine = make_engine(url)
        async with engine.begin() as connection:

            def upgrade(conn, revision):
                config = Config("alembic.ini")
                config.attributes["connection"] = conn
                command.upgrade(config, revision)

            await connection.run_sync(lambda conn: upgrade(conn, "universal_0001"))
            # Core inserts omit the portrait columns introduced after Node1.
            await connection.execute(
                User.__table__.insert().values(id="saved-owner", name="Saved", password_hash="test")
            )
            await connection.execute(
                Campaign.__table__.insert().values(
                    id="saved-game",
                    owner_id="saved-owner",
                    name="Existing world",
                    ruleset_id="universal",
                    ruleset_version="universal.v1",
                )
            )
            await connection.execute(
                Character.__table__.insert().values(
                    id="saved-hero",
                    campaign_id="saved-game",
                    owner_user_id="saved-owner",
                    name="Existing hero",
                    status="active",
                    sheet=sheet().model_dump(mode="json"),
                    resources={"hp": "22"},
                )
            )
            await connection.run_sync(lambda conn: upgrade(conn, "head"))
        await engine.dispose()

    asyncio.run(migrate())
    settings = replace(settings, database_url=url)
    from app.main import create_app

    with TestClient(create_app(settings)) as client:
        client.app.state.master.narrative_preparer = None
        client.app.state.master.signal_recovery = lambda: None
        if client.app.state.master._recovery:
            client.app.state.master._recovery.cancel()
        root = login(client, "root", "rootpass")
        voice = []
        cid, other_id, hero_id, library_before = first_adventure_scenario(client, root, settings, monkeypatch, voice)
        assert len(voice) == 1 and "SECRET-LAW" not in voice[0]
        assert "Vines trace" in voice[0]
        maker = client.app.state.sessionmaker

        async def adventure():
            async with maker() as s:
                hero = await s.get(Character, hero_id)
                campaign = await s.get(Campaign, cid)
                seat = await s.get(Seat, hero.seat_id)
                viewer = Viewer(await s.get(User, hero.owner_user_id), campaign, seat)
                other_before = [
                    (e.id, deepcopy(e.state))
                    for e in await s.scalars(select(Entity).where(Entity.campaign_id == other_id))
                ]
                # A second admitted player receives exactly the same encounter XP.
                companion_seat = next(x for x in campaign.seats if x.role == "player" and x.id != seat.id)
                s.add(
                    Character(
                        id="companion",
                        campaign_id=cid,
                        seat_id=companion_seat.id,
                        name="Companion",
                        status="active",
                        sheet=sheet().model_dump(mode="json"),
                        resources={"hp": "22"},
                        location_id=hero.location_id,
                    )
                )
                await s.flush()
                ctx = ResolutionContext(s, cid, hero.owner_user_id, hero.seat_id, hero.id, FixedDice([]))

                async def act(
                    key, operations, *, source="mundane", targets=None, resolution="automatic", rolls=(), elapsed=6
                ):
                    from app.core.chat import next_seq
                    from app.db.models import Message

                    s.add(
                        Message(
                            id=key,
                            campaign_id=cid,
                            session_id=None,
                            seq=await next_seq(s, cid),
                            seat_id=hero.seat_id,
                            author_user_id=hero.owner_user_id,
                            kind="action",
                            content=key,
                        )
                    )
                    await s.flush()
                    intent = IntentV2(
                        name=key,
                        source=source,
                        resolution=resolution,
                        targets=targets or [hero.id],
                        effects=operations,
                        elapsed_game_seconds=elapsed,
                    )
                    proposal = await compile_exploration(
                        ctx,
                        intent,
                        IntentReview(verdict="pass"),
                        dict(source_message_id=key, source_text=key, evidence=""),
                    )
                    ctx.dice = FixedDice(list(rolls))
                    return await run_exchange(ctx, proposal, request_key=key), proposal

                await act("bush", [EffectIntentV2(kind="camouflage")], source="supernatural")
                assert await active_effects(s, cid, hero.id)
                await act("wait-for-expiry", [EffectIntentV2(kind="wait")], elapsed=60)
                assert not await active_effects(s, cid, hero.id)
                potion = await create_item(
                    s,
                    cid,
                    hero.id,
                    ItemProfile(name="Tonic", kind="consumable", restore_pool="hp", restore_amount=6),
                    "tonic",
                )
                hero.resources = {**hero.resources, "hp": "10"}
                await act("drink", [EffectIntentV2(kind="consume", object_id=potion.id)], source="item")
                assert int(hero.resources["hp"]) > 10
                for index in (1, 2):
                    foe = Entity(
                        id=f"foe{index}",
                        campaign_id=cid,
                        kind="creature",
                        name="Guard",
                        location_id=hero.location_id,
                        state={
                            "hostile": True,
                            "universal_sheet": sheet().model_dump(mode="json"),
                            "resources": {
                                "hp": "1",
                                "energies": {"str": "18", "dex": "20", "int": "23", "wis": "24", "cha": "25"},
                            },
                        },
                    )
                    s.add(foe)
                    await s.flush()
                    results, last = await act(
                        f"win{index}",
                        [EffectIntentV2(kind="damage")],
                        source="supernatural",
                        targets=[foe.id],
                        resolution="attack",
                        rolls=[20, 3, 3],
                    )
                    assert results[0].damage > 0
                assert hero.sheet["xp"] == "300"
                assert (await s.get(Character, "companion")).sheet["xp"] == "300"
                revision = hero.resources["progression_revision"]
                await spend_points(s, cid, hero.id, revision, {"wis": 2}, "grow")
                before = await clock_view(s, cid)
                count = await s.scalar(select(func.count()).select_from(Event).where(Event.campaign_id == cid))
                await s.refresh(campaign)
                assert (await party_map(s, viewer))["here"]
                assert await clock_view(s, cid) == before
                assert [
                    (e.id, e.state) for e in await s.scalars(select(Entity).where(Entity.campaign_id == other_id))
                ] == other_before
                saved = await s.get(Character, "saved-hero")
                assert saved.resources == {"hp": "22"} and saved.name == "Existing hero"
                await s.commit()
            async with maker() as s:
                ctx.session, ctx.dice = s, FixedDice([])
                assert (await run_exchange(ctx, last, request_key="win2"))[0].status == "repeated"
                card = await exploration_game_card(s, await s.get(Character, hero_id))
                assert card["sheet"]["level"] == "2" and card["sheet"]["unspent_points"] == "0"
                assert await s.scalar(select(func.count()).select_from(Event).where(Event.campaign_id == cid)) == count
                assert await clock_view(s, cid) == before
            return card

        card = asyncio.run(adventure())
        assert client.get("/api/me/characters", headers=root).json() == library_before
        with connect(client, root, cid, last_seq=0) as (_, snapshot):
            assert snapshot["payload"]["replay"]
            assert "SECRET-LAW" not in str(snapshot)
        assert card["learned_abilities"]
