"""Authored NPCs receive real, persistent cells rather than disappearing from maps."""

from app.core import positions, reach, sketch
from app.db.models import Entity
from tests.game import import_base, party
from tests.test_map import _map, _ok, _play
from tests.test_sketch import CELL


def test_residents_get_free_cells_without_repositioning_authored_actors(client, admin, settings):
    import_base(settings)
    campaign, (player,), _hero = party(client, admin)
    cid = campaign["id"]

    async def setup(ctx):
        place = (await _ok(ctx, "create_location", {"name": "Room", "make_current": True}))["location_id"]
        await _ok(ctx, "sketch_place", CELL)
        other = (await _ok(ctx, "create_location", {"name": "Elsewhere"}))["location_id"]
        actors = []
        for name, target, state in [
            ("Guard", place, {"attitude": "neutral"}),
            ("Warden", place, {"cell": [3, 0], "attitude": "neutral"}),
            ("Hidden guard", place, {"secret": True}),
            ("Distant guard", other, {}),
        ]:
            actor = Entity(campaign_id=cid, kind="creature", name=name, location_id=target, state=state, zone="near")
            ctx.session.add(actor)
            await ctx.session.flush()
            ctx.world.entities[actor.id] = actor
            actors.append(actor)
        before = dict(actors[1].state)
        inverse = []
        placed = positions.place_residents(ctx.world, place, inverse)
        assert {aid for aid, _ in placed} == {actors[0].id, actors[2].id}
        assert actors[1].state == before
        assert "cell" not in actors[3].state
        sk = sketch.of_place(ctx.world.entities[place], ctx.world.catalog, ctx.world.entities)
        cells = {positions.to_master(ctx.world, place, positions.pos_of(ctx.world, aid).cell) for aid, _ in placed}
        assert len(cells) == len(placed)
        assert cells <= reach.walk_region(sk, tuple(sk["party"]))
        assert not cells & {tuple(sk["party"])}
        assert not cells & {tuple(c) for exit_ in sk["exits"] for c in sketch.exit_cells(sk, exit_)}
        assert positions.place_residents(ctx.world, place, inverse) == []
        assert inverse
        return [a.id for a in actors]

    guard, warden, hidden, distant = _play(settings, cid, setup)
    packet = _map(client, player, cid)
    tokens = {t["id"]: t for t in packet["scene_view"]}
    assert tokens[guard]["cell"] and tokens[warden]["cell"]
    assert hidden not in tokens and distant not in tokens


def test_complex_reservation_keeps_fresh_world_references():
    from app.core.authoring.references import RefMap, adapt_state, restore_state

    refs = RefMap()
    refs.entities = {"en_root": "root", "en_cell": "cell"}
    state = {
        "content_reservation": {
            "areas": {"cells": {"complex_root_id": "en_root", "location_id": "en_cell", "budget": 3}}
        }
    }
    logical = adapt_state(state, refs)
    copied = restore_state(logical, {"root": "en_new_root", "cell": "en_new_cell"})
    area = copied["content_reservation"]["areas"]["cells"]
    assert area == {"complex_root_id": "en_new_root", "location_id": "en_new_cell", "budget": 3}
    assert state["content_reservation"]["areas"]["cells"]["complex_root_id"] == "en_root"


def test_launch_places_legacy_residents_and_keeps_author_source_unchanged(settings):
    from sqlalchemy import select

    from app.core.authoring.instances import instantiate_adventure
    from app.db.models import Campaign
    from tests.test_adventure_instances import OPTIONS, published
    from tests.test_authoring_validation import _prepared

    async def body(maker, pid, cid):
        async with maker() as session:
            source = list(
                await session.scalars(select(Entity).where(Entity.campaign_id == cid, Entity.kind == "creature"))
            )
            assert source
            for actor in source:
                actor.state = {k: v for k, v in actor.state.items() if k != "cell"}
            await session.commit()
            project, version, owner = await published(session, pid)
            receipt = await instantiate_adventure(session, owner, version, OPTIONS, "resident-placement")
            await session.commit()
            from app.content.catalog import campaign_catalog
            from app.core.world import load_world

            game = await session.get(Campaign, receipt.campaign_id)
            world = await load_world(session, game, await campaign_catalog(session, game))
            actors = [e for e in world.entities.values() if e.kind == "creature"]
            assert actors
            for actor in actors:
                place = world.entities.get(actor.location_id)
                if place and (place.state or {}).get("sketch"):
                    assert positions.pos_of(world, actor.id).cell is not None
            assert all("cell" not in actor.state for actor in source)

    _prepared(settings, body)
