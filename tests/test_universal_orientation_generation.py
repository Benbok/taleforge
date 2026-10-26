import asyncio
from copy import deepcopy

import pytest
from sqlalchemy import func, select

from app.core.campaigns import Viewer
from app.core.map import party_map
from app.core.universal.clock import clock_view
from app.db.models import Campaign, Character, Entity, Event, Seat, User
from tests.test_universal_location_knowledge import place
from tests.test_universal_resolution import setup


def test_generation_is_saved_private_safe_and_free_of_gameplay_mutation(tmp_path):
    async def run():
        from app.core.universal.orientation_generation import generate_for_viewer

        engine, maker = await setup(tmp_path)
        await place(maker)
        async with maker() as s:
            s.add_all(
                [
                    Entity(id="cart", campaign_id="c", kind="object", name="Повозка", location_id="gorge"),
                    Entity(
                        id="secret",
                        campaign_id="c",
                        kind="object",
                        name="PRIVATE",
                        location_id="gorge",
                        state={"secret": True},
                    ),
                    Entity(
                        id="owned",
                        campaign_id="c",
                        kind="object",
                        name="PRIVATE-ITEM",
                        location_id="gorge",
                        state={"universal_item": {"owner_id": "hero"}},
                    ),
                ]
            )
            await s.commit()
            hero = await s.get(Character, "hero")
            resources = deepcopy(hero.resources)
            viewer = Viewer(await s.get(User, "u"), await s.get(Campaign, "c"), await s.get(Seat, "seat"))
            before = await clock_view(s, "c")
            assert (await party_map(s, viewer))["sketch"] is None
            assert (await generate_for_viewer(s, viewer, "gorge"))["created"]
            saved = deepcopy((await s.get(Entity, "gorge")).state)
            assert saved["sketch"]["mask"]
            assert "PRIVATE" not in str(saved)
            assert "cart" in str(saved)
            assert not (await generate_for_viewer(s, viewer, "gorge"))["created"]
            assert (await s.get(Entity, "gorge")).state == saved
            assert hero.resources == resources and await clock_view(s, "c") == before
            assert await s.scalar(select(func.count()).select_from(Event)) == 0
            await s.commit()
        async with maker() as s:
            assert (await s.get(Entity, "gorge")).state == saved
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("entry", ["session", "travel", "crossing"])
def test_first_entry_prepares_map_without_replacing_the_location(tmp_path, entry):
    async def run():
        engine, maker = await setup(tmp_path)
        await place(maker)
        async with maker() as s:
            if entry == "session":
                from app.core.chat import start_session

                s.add(Seat(id="master", campaign_id="c", role="master", position=0, occupant_type="human"))
                await s.flush()
                viewer = Viewer(await s.get(User, "u"), await s.get(Campaign, "c"), await s.get(Seat, "seat"))
                await start_session(s, viewer)
                location = await s.get(Entity, "gorge")
            elif entry == "travel":
                from app.core.universal.resolution import ResolutionContext
                from app.core.universal.travel import move_hero
                from app.rules.dice import FixedDice

                (await s.get(Entity, "gorge")).state = {"links": [{"to": "next"}]}
                s.add(Entity(id="next", campaign_id="c", kind="location", name="Forest"))
                await s.flush()
                await move_hero(ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([])), "next")
                location = await s.get(Entity, "next")
            else:
                from app.core.universal.resolution import ResolutionContext
                from app.rules.dice import FixedDice
                from tests.test_exploration_crossing import bridge, walk
                from tests.test_exploration_resolution import build

                ctx = ResolutionContext(s, "c", "u", "seat", "hero", FixedDice([]))
                await build(ctx, s, bridge())
                obj = await s.scalar(select(Entity).where(Entity.kind == "object"))
                await build(ctx, s, walk(obj.id), "m2", 2)
                location = await s.get(Entity, (await s.get(Character, "hero")).location_id)
            assert location.state.get("sketch")
            assert location.state["orientation_map"]["version"] == 1
        await engine.dispose()

    asyncio.run(run())


def test_existing_campaign_map_generation_endpoint_is_authenticated_and_idempotent(client, root, monkeypatch):
    from tests.test_api import make_campaign
    from tests.test_universal_resolution import sheet

    monkeypatch.setattr(client.app.state.master, "notify", lambda *_: None)
    campaign = make_campaign(client, root, owner_plays=True)
    cid = campaign["id"]

    async def seed():
        async with client.app.state.sessionmaker() as s:
            c = await s.get(Campaign, cid)
            c.ruleset_id, c.ruleset_version = "universal", "universal.v1"
            seat = next(x for x in c.seats if x.role == "player" and x.user_id == c.owner_id)
            s.add(Entity(id="here", campaign_id=cid, kind="location", name="Cave", description="A dark cave."))
            s.add(
                Character(
                    id="map-hero",
                    campaign_id=cid,
                    seat_id=seat.id,
                    owner_user_id=c.owner_id,
                    name="Hero",
                    status="active",
                    location_id="here",
                    sheet=sheet().model_dump(mode="json"),
                    resources={"hp": "22"},
                )
            )
            await s.commit()

    asyncio.run(seed())
    path = f"/api/campaigns/{cid}/orientation-map"
    assert client.post(path, json={"location_id": "here"}).status_code == 401
    response = client.post(path, headers=root, json={"location_id": "here"})
    assert response.status_code == 200, response.text
    assert response.json() == {"created": True, "location_id": "here"}
    assert client.post(path, headers=root, json={"location_id": "here"}).json()["created"] is False
    assert client.post(path, headers=root, json={"location_id": "missing"}).status_code == 409


@pytest.mark.parametrize("variant", ["saved", "complex", "book", "foreign", "stale"])
def test_generation_preserves_authored_maps_and_rejects_other_locations(tmp_path, variant):
    async def run():
        from app.core.universal.orientation_generation import generate_for_viewer

        engine, maker = await setup(tmp_path)
        await place(maker)
        async with maker() as s:
            location = await s.get(Entity, "gorge")
            if variant == "saved":
                location.state = {"sketch": {"original": True}}
            if variant == "complex":
                location.state = {"complex": {"root_id": "root", "area_ref": "entry"}}
            if variant == "book":
                location.state = {"room": {"of": "module", "id": "room1"}}
            if variant == "foreign":
                s.add(
                    Campaign(
                        id="other", owner_id="u", name="Other", ruleset_id="universal", ruleset_version="universal.v1"
                    )
                )
                await s.flush()
                s.add(Entity(id="elsewhere", campaign_id="other", kind="location", name="Foreign"))
            elif variant == "stale":
                s.add(Entity(id="elsewhere", campaign_id="c", kind="location", name="Elsewhere"))
            await s.commit()
            before = deepcopy(location.state)
            viewer = Viewer(await s.get(User, "u"), await s.get(Campaign, "c"), await s.get(Seat, "seat"))
            if variant in {"foreign", "stale"}:
                with pytest.raises(ValueError):
                    await generate_for_viewer(s, viewer, "elsewhere")
            elif variant == "book":
                from app.core.universal.orientation_generation import ensure_map

                assert not await ensure_map(s, "c", "gorge")
            else:
                assert not (await generate_for_viewer(s, viewer, "gorge"))["created"]
            assert location.state == before
        await engine.dispose()

    asyncio.run(run())


def test_master_generates_the_location_displayed_on_the_map(tmp_path):
    async def run():
        from app.core.universal.orientation_generation import generate_for_viewer
        from app.db.models import Scene

        engine, maker = await setup(tmp_path)
        await place(maker)
        async with maker() as s:
            (await s.get(Character, "target")).status = "retired"
            s.add(Entity(id="old", campaign_id="c", kind="location", name="Old place"))
            s.add(Scene(campaign_id="c", location_id="old", state={}))
            s.add(Seat(id="master", campaign_id="c", role="master", position=0, occupant_type="human"))
            await s.flush()
            viewer = Viewer(await s.get(User, "u"), await s.get(Campaign, "c"), await s.get(Seat, "master"))
            assert (await party_map(s, viewer))["here"]["id"] == "gorge"
            assert (await generate_for_viewer(s, viewer, "gorge"))["created"]
            assert not (await s.get(Entity, "old")).state.get("sketch")
        await engine.dispose()

    asyncio.run(run())


def test_simultaneous_requests_create_only_one_sketch(tmp_path):
    async def run():
        from app.core.universal.orientation_generation import generate_for_viewer

        engine, maker = await setup(tmp_path)
        await place(maker)

        async def generate():
            async with maker() as s:
                viewer = Viewer(await s.get(User, "u"), await s.get(Campaign, "c"), await s.get(Seat, "seat"))
                result = await generate_for_viewer(s, viewer, "gorge")
                await s.commit()
                return result

        results = await asyncio.gather(generate(), generate())
        assert sum(r["created"] for r in results) == 1
        await engine.dispose()

    asyncio.run(run())


@pytest.mark.parametrize("description", ["Empty cave", "An open field"])
def test_outline_does_not_invent_scenery_or_block_existing_markers(description):
    from app.core.universal.orientation_generation import build_sketch

    location = Entity(id="loc", campaign_id="c", kind="location", name="Place", description=description, state={})
    assert build_sketch("c", location, {"loc": location})["features"] == []
    objects = {
        key: Entity(id=key, campaign_id="c", kind="object", name="Marker", location_id="loc", state={})
        for key in ["x" * 31 + "1", "x" * 31 + "2"]
    }
    sketch = build_sketch("c", location, {"loc": location, **objects})
    assert len(sketch["features"]) == 2
    assert len({f["id"] for f in sketch["features"]}) == 2
    assert not sketch["walls"]


@pytest.mark.parametrize("entry", ["button", "session"])
def test_shared_scene_heroes_get_the_same_current_location_semantics_as_the_map(tmp_path, entry):
    async def run():
        from app.core.universal.orientation_generation import generate_for_viewer
        from app.db.models import Scene

        engine, maker = await setup(tmp_path)
        await place(maker)
        async with maker() as s:
            hero = await s.get(Character, "hero")
            hero.location_id = None
            s.add(Scene(campaign_id="c", location_id="gorge", state={}))
            s.add(Seat(id="master", campaign_id="c", role="master", position=0, occupant_type="human"))
            await s.flush()
            viewer = Viewer(await s.get(User, "u"), await s.get(Campaign, "c"), await s.get(Seat, "seat"))
            assert (await party_map(s, viewer))["here"]["id"] == "gorge"
            if entry == "button":
                assert (await generate_for_viewer(s, viewer, "gorge"))["created"]
            else:
                from app.core.chat import start_session

                await start_session(s, viewer)
            assert (await s.get(Entity, "gorge")).state.get("sketch")
            assert hero.location_id is None
        await engine.dispose()

    asyncio.run(run())
