"""Пакет кампании: записи, придуманные мастером, видит только своя кампания (спецификация 2026-10-13, §5)."""

from app.content import overlay
from app.content.catalog import campaign_catalog
from app.core import audio
from app.db.models import Campaign
from tests.game import import_base, party, run

BERRY = {
    "id": "item.goodberry_x",
    "name": "Добрая ягода",
    "status": "proposal",
    "category": "consumable",
    "price": {"cp": 0},
    "description": "Лечит 1 хит.",
    "modifiers": [{"op": "resource", "stat": "hp", "delta": 1}],
}


def _camp(client, admin, settings):
    import_base(settings)
    c, _heads, _hero = party(client, admin)
    return c["id"]


def test_overlay_is_visible_only_to_its_campaign(client, admin, settings):
    a = _camp(client, admin, settings)
    b, _h, _x = party(client, admin, names=["Боромир"])

    async def go(s):
        ca = await s.get(Campaign, a)
        view = await overlay.add_record(s, ca, "item_template", BERRY)
        await s.commit()
        assert not ca.settings.get("allow_proposals")
        assert view.find("item.goodberry_x", "item_template").data["modifiers"][0]["delta"] == 1
        assert ca.content_chain[-1][0] == overlay.overlay_id(a)
        other = await campaign_catalog(s, await s.get(Campaign, b["id"]))
        return other.find("item.goodberry_x", "item_template")

    assert run(settings, go) is None


def test_second_record_keeps_first_and_versions_are_unique(client, admin, settings):
    a = _camp(client, admin, settings)

    async def go(s):
        c = await s.get(Campaign, a)
        await overlay.add_record(s, c, "item_template", BERRY)
        v1 = c.content_chain[-1][1]
        view = await overlay.add_record(s, c, "item_template", {**BERRY, "id": "item.moss_salve", "name": "Мазь"})
        await s.commit()
        return v1, c.content_chain[-1][1], view, len(await overlay.overlay_records(s, c))

    v1, v2, view, n = run(settings, go)
    assert v1 != v2 and n == 2
    assert view.find("item.goodberry_x", "item_template") and view.find("item.moss_salve", "item_template")


def test_rollback_restores_chain(client, admin, settings):
    a = _camp(client, admin, settings)

    async def go(s):
        c = await s.get(Campaign, a)
        before = [list(x) for x in c.content_chain]
        nested = await s.begin_nested()
        await overlay.add_record(s, c, "item_template", BERRY)
        await nested.rollback()
        await s.refresh(c)
        view = await campaign_catalog(s, c)
        return before, c.content_chain, view.find("item.goodberry_x", "item_template")

    before, after, found = run(settings, go)
    assert before == after and found is None


def test_pack_of_skips_campaign_overlay(client, admin, settings):
    a = _camp(client, admin, settings)

    async def go(s):
        c = await s.get(Campaign, a)
        world = audio.pack_of(c)
        c.pack_id = None
        await overlay.add_record(s, c, "item_template", BERRY)
        return world, audio.pack_of(c)

    world, after = run(settings, go)
    assert after is not None and not overlay.is_overlay(after)
    assert world is None or after == world or not overlay.is_overlay(after)
