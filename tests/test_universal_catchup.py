import asyncio

import pytest
from sqlalchemy import select

from app.core.universal.profiles import load_actor
from app.core.universal.progression import catch_up_copy
from app.db.models import Character, Event, Seat
from app.rules.universal.progression import grant_xp, level_threshold
from tests.test_universal_resolution import setup, sheet


def test_catchup_is_separate_once_and_does_not_allocate(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add(Seat(id="second", campaign_id="c", role="player", position=2, user_id="u", occupant_type="human"))
            target = await s.get(Character, "target")
            target.seat_id = "second"
            target.sheet = grant_xp(sheet(), level_threshold(10)).model_dump(mode="json")
            await s.commit()
            assert (await load_actor(s, "c", "hero"))[0].level == 1
            after = await catch_up_copy(s, "c", "hero")
            assert after.level == 10 and after.unspent_points == 18 and after.abilities.wis == 14
            assert (await catch_up_copy(s, "c", "hero")).budget.growth_total == 18
            event = await s.scalar(select(Event).where(Event.tool == "universal_catchup"))
            assert event.payload["created_sheet"]["level"] == "1" and event.payload["created_sheet"]["xp"] == "0"
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("from_library", [False, True])
def test_creation_and_library_admission_catch_up_after_l1(client, root, from_library):
    from app.db.models import Campaign
    from tests.test_universal_admission import studio_campaign
    from tests.universal_helpers import DESCRIPTION, create_hero, ready_reply, set_replies

    cid = studio_campaign(client, root)
    library_id = create_hero(client, root)
    original = client.get("/api/me/characters", headers=root).json()

    async def seed():
        async with client.app.state.sessionmaker() as s:
            campaign = await s.get(Campaign, cid)
            party_seat = next(row for row in campaign.seats if row.role == "player" and row.user_id is None)
            party_seat.occupant_type = "ai"
            await s.flush()
            sh = grant_xp(sheet(), level_threshold(10))
            from app.rules.universal.mechanics import derive

            derived = derive(sh, [])
            s.add(
                Character(
                    id="party-hero",
                    campaign_id=cid,
                    seat_id=party_seat.id,
                    owner_user_id=campaign.owner_id,
                    status="active",
                    name="Veteran",
                    sheet=sh.model_dump(mode="json"),
                    resources=dict(hp=str(derived.hp_max), energies={k: str(v) for k, v in derived.energy_max.items()}),
                )
            )
            await s.commit()

    asyncio.run(seed())
    set_replies(client, [ready_reply()])
    if from_library:
        draft = client.post(f"/api/campaigns/{cid}/characters/from-library/{library_id}/admission", headers=root).json()
    else:
        draft = client.post(
            "/api/hero-creation/dialogues", headers=root, json={"campaign_id": cid, "description": DESCRIPTION}
        ).json()
    response = client.post(
        f"/api/hero-creation/dialogues/{draft['id']}/confirm",
        headers=root,
        json={"expected_revision": draft["revision"]},
    )
    assert response.status_code == 200, response.text
    hero_id = response.json()["hero_id"]
    card = client.get(f"/api/campaigns/{cid}/characters/{hero_id}", headers=root).json()
    assert card["sheet"]["level"] == "10" and card["sheet"]["unspent_points"] == "18"
    assert client.get("/api/me/characters", headers=root).json() == original


def test_dead_and_foreign_party_do_not_inflate_catchup(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            s.add(Seat(id="second", campaign_id="c", role="player", position=2, user_id="u", occupant_type="human"))
            target = await s.get(Character, "target")
            target.seat_id = "second"
            target.sheet = grant_xp(sheet(), level_threshold(100)).model_dump(mode="json")
            target.resources = {**target.resources, "hp": "0", "vitality": {"state": "dead"}}
            await s.flush()
            assert (await catch_up_copy(s, "c", "hero")).level == 1
            await s.commit()
            from app.core.campaigns import AccessDenied, NotFound

            with pytest.raises((AccessDenied, NotFound)):
                await catch_up_copy(s, "elsewhere", "hero")
        await engine.dispose()

    asyncio.run(run())


def test_pending_admission_blocks_awards_until_catchup_is_recorded(tmp_path):
    from app.core.campaigns import AccessDenied
    from app.core.universal.progression import award_xp

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hero = await s.get(Character, "hero")
            hero.resources = {**hero.resources, "admission_pending": True}
            s.add(Seat(id="second", campaign_id="c", role="player", position=2, user_id="u", occupant_type="human"))
            target = await s.get(Character, "target")
            target.seat_id = "second"
            target.sheet = grant_xp(sheet(), level_threshold(10)).model_dump(mode="json")
            await s.commit()
            with pytest.raises(AccessDenied):
                await award_xp(s, "c", "interleaved", ["hero"], 150)
            assert (await catch_up_copy(s, "c", "hero")).unspent_points == 18
            assert not hero.resources.get("admission_pending")
            await s.commit()
        await engine.dispose()

    asyncio.run(run())


def test_pending_copy_recovery_is_explicit_and_blocks_action_before_admission(tmp_path):
    from app.core.universal.progression import resume_admission
    from app.core.universal.resolution import ResolutionContext
    from app.rules.dice import FixedDice
    from tests.test_exploration_resolution import prepare

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            hero = await s.get(Character, "hero")
            hero.resources = {**hero.resources, "admission_pending": True}
            await s.commit()
            with pytest.raises(ValueError):
                await prepare(
                    s, ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([])), "wait", source="mundane"
                )
            await resume_admission(s, "c", "hero", "u", "seat")
            await s.commit()
            assert not hero.resources["admission_pending"]
            await resume_admission(s, "c", "hero", "u", "seat")
            assert (await load_actor(s, "c", "hero"))[0].level == 1
        await engine.dispose()

    asyncio.run(run())


def test_interrupted_creation_can_resume_through_owner_endpoint(client, root, monkeypatch):
    from app.core.universal import creation
    from tests.test_universal_admission import studio_campaign
    from tests.universal_helpers import DESCRIPTION, ready_reply, set_replies

    cid = studio_campaign(client, root)

    async def interrupted(*_):
        pass

    monkeypatch.setattr(creation, "_finish_admission", interrupted)
    set_replies(client, [ready_reply()])
    draft = client.post(
        "/api/hero-creation/dialogues", headers=root, json={"campaign_id": cid, "description": DESCRIPTION}
    ).json()
    created = client.post(
        f"/api/hero-creation/dialogues/{draft['id']}/confirm",
        headers=root,
        json={"expected_revision": draft["revision"]},
    )
    assert created.status_code == 200, created.text
    hero_id = created.json()["hero_id"]
    card = client.get(f"/api/campaigns/{cid}/characters/{hero_id}", headers=root).json()
    assert card["progression"]["admission_pending"] is True
    endpoint = f"/api/campaigns/{cid}/characters/{hero_id}/resume-admission"
    assert client.post(endpoint).status_code == 401
    done = client.post(endpoint, headers=root, json={"target_level": 999})
    assert done.status_code == 200, done.text
    assert done.json()["level"] == "1" and not done.json()["progression"]["admission_pending"]
    assert client.post(endpoint, headers=root).json()["sheet"]["unspent_points"] == "0"


def test_pending_copy_cannot_be_targeted_before_admission(tmp_path):
    from app.core.universal.resolution import ResolutionContext
    from app.rules.dice import FixedDice
    from app.rules.universal.exploration import EffectIntentV2
    from tests.test_universal_combat_actions import attack

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            target = await s.get(Character, "target")
            target.resources = {**target.resources, "admission_pending": True}
            ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
            with pytest.raises(ValueError):
                await attack(s, ctx, [EffectIntentV2(kind="damage")])
        await engine.dispose()

    asyncio.run(run())
