"""Фазы комплекса в механизме подготовки (спецификация 2026-10-12, §8): CHECK, миграция и идемпотентный резерв."""

from app.core.layout import store
from tests.game import import_base, party, quiet
from tests.layout_pilot import pilot_intent
from tests.test_map import _ok, _play


def test_reserve_layout_is_idempotent(client, admin, settings):
    import_base(settings)
    campaign, _heads, _hero = party(client, admin)
    quiet(client)
    cid = campaign["id"]

    async def go(ctx):
        temple = (await _ok(ctx, "create_location", {"name": "Старый храм"}))["location_id"]
        root = ctx.world.entities[temple]
        first = await store.reserve_layout(ctx.session, ctx.campaign, root, pilot_intent())
        again = await store.reserve_layout(ctx.session, ctx.campaign, root, pilot_intent())
        assert first.id == again.id and first.phase == "location_layout" and first.requested_at is None
        assert first.reservation["intent"] == pilot_intent().model_dump(mode="json")
        assert first.seed == store.layout_seed(cid, temple) and 0 <= first.seed < 2**31
        assert store.complex_of(root) is None and store.blueprint_of(root) is None
        return first.id

    ref = _play(settings, cid, go)
    assert isinstance(ref, str)
