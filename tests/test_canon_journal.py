"""Журнал канона собирается из событий творческих инструментов: пока без API и экрана."""

from app.core.canon_journal import canon_journal, entry
from app.db.models import Campaign, Event
from app.tools.runtime import open_context
from tests.game import QueueDice, import_base, party, run
from tests.test_world_objects_transfer import ok


def test_entry_reads_each_creative_tool_and_ignores_the_rest():
    def ev(tool, **kw):
        return Event(id="ev_1", campaign_id="c", tool=tool, **kw)

    assert (
        entry(ev("keep_found_item", payload={"item": "Бумаги", "reason": "тайник", "inventory_id": "inv_1"}))["name"]
        == "Бумаги"
    )
    placed = entry(ev("place_item", payload={"item": "Печать", "entity_id": "en_1", "reason": "под столом"}))
    assert placed["subject_id"] == "en_1" and placed["reason"] == "под столом"
    assert entry(ev("add_landmark", target_id="en_2", payload={"name": "Статуя"}))["kind"] == "Примета места"
    assert entry(ev("invent_item", payload={"missing_id": "item.x", "record": {"name": "Зелье"}}))["name"] == "Зелье"
    assert entry(ev("roll_check", payload={})) is None


def test_journal_lists_what_the_master_created_in_a_real_campaign(client, admin, settings):
    import_base(settings)
    campaign, _heads, hero = party(client, admin)
    cid = campaign["id"]

    async def go(session):
        ctx = await open_context(
            session, await session.get(Campaign, cid), QueueDice([]), turn_id="t_canon", seat_id=None
        )
        await ok(ctx, "create_location", {"name": "Камера", "make_current": True})
        await ok(ctx, "add_landmark", {"name": "Стол пыток", "zone": "near"})
        await session.commit()
        return [e["name"] for e in await canon_journal(session, cid)]

    assert "Стол пыток" in run(settings, go)
    assert hero["id"]


def test_canon_journal_endpoint_is_for_the_owner_only(client, admin, settings):
    import_base(settings)
    campaign, _heads, _hero = party(client, admin)
    cid = campaign["id"]

    async def go(session):
        ctx = await open_context(
            session, await session.get(Campaign, cid), QueueDice([]), turn_id="t_canon2", seat_id=None
        )
        await ok(ctx, "create_location", {"name": "Камера", "make_current": True})
        await ok(ctx, "add_landmark", {"name": "Решётка", "zone": "near"})
        await session.commit()

    run(settings, go)
    got = client.get(f"/api/campaigns/{cid}/canon-journal", headers=admin)
    assert got.status_code == 200, got.text
    assert [e["name"] for e in got.json()["entries"]] == ["Решётка"]
    assert got.json()["entries"][0]["kind"] == "Примета места"
    assert client.get(f"/api/campaigns/{cid}/canon-journal").status_code in (401, 403)
