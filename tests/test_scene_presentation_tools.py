# The imported fixture must remain in module globals; pytest resolves the
# parameter named ``game`` from this re-export.
# ruff: noqa: F401, F811
from sqlalchemy import select

from app.db.models import Entity, Event
from tests.test_tools import call, game, play, run


def test_presentation_preserves_other_state_and_has_inverse(game):
    settings, cid, _ = game

    async def fn(ctx):
        loc = Entity(
            id="loc_presentation",
            campaign_id=cid,
            kind="location",
            name="Бухта",
            state={"links": [{"to": "other"}], "visited_by": ["hero"], "secret": True},
        )
        ctx.session.add(loc)
        await ctx.session.flush()
        ctx.world.entities[loc.id] = loc
        return await call(
            ctx,
            "set_location_presentation",
            {
                "location_id": loc.id,
                "preset": "coast",
                "period": "dusk",
                "weather": "fog",
                "illustration_key": "salt_bay",
            },
        )

    out = play(settings, cid, [], fn)
    assert out["ok"], out

    async def read(s):
        loc = await s.get(Entity, "loc_presentation")
        event = (await s.scalars(select(Event).where(Event.tool == "set_location_presentation"))).first()
        return loc, event

    loc, event = run(settings, read)
    assert loc.state["links"] == [{"to": "other"}]
    assert loc.state["secret"] is True
    assert loc.state["presentation"]["preset"] == "coast"
    assert event.inverse[0]["before"]["secret"] is True


def test_presentation_rejects_non_location_and_invalid_keys(game):
    settings, cid, hero = game

    async def fn(ctx):
        return (
            await call(ctx, "set_location_presentation", {"location_id": hero, "preset": "coast"}),
            await call(ctx, "set_location_presentation", {"location_id": "missing", "preset": "coast"}),
        )

    non_location, missing = play(settings, cid, [], fn)
    assert not non_location["ok"] and "локац" in non_location["error"]
    assert not missing["ok"]


def test_presentation_retry_is_idempotent(game):
    settings, cid, _ = game

    async def fn(ctx):
        loc = Entity(id="loc_retry", campaign_id=cid, kind="location", name="Лес", state={})
        ctx.session.add(loc)
        await ctx.session.flush()
        ctx.world.entities[loc.id] = loc
        args = {"location_id": loc.id, "preset": "forest", "illustration_key": "forest"}
        return await call(ctx, "set_location_presentation", args, key="presentation:retry"), await call(
            ctx, "set_location_presentation", args, key="presentation:retry"
        )

    first, second = play(settings, cid, [], fn)
    assert first["ok"] and second.get("repeated")
