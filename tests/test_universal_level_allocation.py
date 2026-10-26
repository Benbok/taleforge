import asyncio

import pytest

from app.core.campaigns import Conflict
from app.core.universal.profiles import ActorResources, load_actor
from app.core.universal.progression import award_xp, resize_resources, spend_points
from app.db.models import Character
from app.rules.universal.progression import grant_xp
from tests.test_universal_resolution import setup, sheet


def test_refill_preserves_shortfall_and_never_revives_dead():
    before = sheet()
    after = before.model_copy(update={"abilities": before.abilities.model_copy(update={"dex": 14})})
    resources = ActorResources(hp=0, energies=dict(str=5, dex=5, int=5, wis=5, cha=5))
    resized = resize_resources(resources, before, after)
    assert resized.energies["dex"] == 9 and resized.hp == 0
    grown = grant_xp(before, 300)
    assert resize_resources(resources, before, grown).hp == 6
    assert resize_resources(resources, before, grown, dead=True).hp == 0


def test_allocation_revision_replay_and_no_refund(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await award_xp(s, "c", "earned", ["hero"], 300)
            hero = await s.get(Character, "hero")
            revision = hero.resources["progression_revision"]
            result = await spend_points(s, "c", "hero", revision, {"wis": 2}, "spend")
            assert result.abilities.wis == 16 and result.budget.unspent == 0
            resources = dict(hero.resources)
            await spend_points(s, "c", "hero", revision, {"wis": 2}, "spend")
            assert hero.resources == resources
            with pytest.raises(Conflict):
                await spend_points(s, "c", "hero", revision, {"wis": 2}, "stale")
            with pytest.raises(ValueError):
                await spend_points(s, "c", "hero", revision + 1, {"wis": 1}, "over")
        await engine.dispose()

    asyncio.run(run())


def test_concurrent_allocation_cannot_spend_the_same_points_twice(tmp_path):
    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await award_xp(s, "c", "level", ["hero"], 300)
            await s.commit()

        async def attempt(key):
            async with maker() as s:
                await spend_points(s, "c", "hero", 2, {"wis": 2}, key)
                await s.commit()

        outcomes = await asyncio.gather(attempt("one"), attempt("two"), return_exceptions=True)
        assert sum(isinstance(value, Conflict) for value in outcomes) == 1
        async with maker() as s:
            sh, _ = await load_actor(s, "c", "hero")
            assert sh.abilities.wis == 16 and sh.budget.unspent == 0
        await engine.dispose()

    asyncio.run(run())


def test_allocation_api_rejects_overspend_and_stale_revision(client, root, monkeypatch):
    from app.db.models import Campaign
    from tests.test_api import make_campaign

    monkeypatch.setattr(client.app.state.master, "notify", lambda *_: None)
    cid = make_campaign(client, root, owner_plays=True)["id"]

    async def seed():
        async with client.app.state.sessionmaker() as s:
            campaign = await s.get(Campaign, cid)
            seat = next(row for row in campaign.seats if row.role == "player")
            s.add(
                Character(
                    id="growth-hero",
                    campaign_id=cid,
                    seat_id=seat.id,
                    owner_user_id=campaign.owner_id,
                    name="Hero",
                    status="active",
                    sheet=sheet().model_dump(mode="json"),
                    resources=dict(hp="22", energies=dict(str="18", dex="20", int="23", wis="24", cha="25")),
                )
            )
            await s.flush()
            await award_xp(s, cid, "earned", ["growth-hero"], 300)
            await s.commit()

    asyncio.run(seed())
    endpoint = f"/api/campaigns/{cid}/characters/growth-hero/allocate-points"
    body = dict(expected_revision=2, allocations={"wis": "3"}, request_key="too-much")
    rejected = client.post(endpoint, headers=root, json=body)
    assert rejected.status_code == 409
    body.update(allocations={"wis": "2"}, request_key="spend")
    response = client.post(endpoint, headers=root, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["sheet"]["abilities"]["wis"] == "16"
    assert response.json()["revision"] == 3
    assert client.post(endpoint, headers=root, json=body).status_code == 200
    body["request_key"] = "stale"
    assert client.post(endpoint, headers=root, json=body).status_code == 409


def test_revoked_controller_is_rechecked_inside_growth_lock(tmp_path):
    from app.core.campaigns import AccessDenied
    from app.db.models import Seat

    async def run():
        engine, maker = await setup(tmp_path)
        async with maker() as s:
            await award_xp(s, "c", "earned", ["hero"], 300)
            seat = await s.get(Seat, "seat")
            seat.user_id = None
            await s.commit()
            with pytest.raises(AccessDenied):
                await spend_points(s, "c", "hero", 2, {"wis": 2}, "revoked", user_id="u", seat_id="seat")
        await engine.dispose()

    asyncio.run(run())
