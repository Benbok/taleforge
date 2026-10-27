# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Кампания по готовому приключению: каркас из книги, зацепка, комнаты по номерам и сложности проверок книги."""

from pathlib import Path

from app.agents.master import decision_tools
from app.core import adventure, modules
from app.db.models import AdventureModule, Campaign
from tests.game import import_base, party, run
from tests.module_sample import sample
from tests.test_map import _play

ROOT = Path(__file__).resolve().parents[1] / "content"


GRID = {"cols": 10, "rows": 8, "left": 0.0, "top": 0.0, "right": 1.0, "bottom": 0.8}
CRYPT_MAP = {
    "id": "map1",
    "file": "map1.png",
    "location_id": "location.davos_crypt",
    "grid": GRID,
    "marks": [
        {"number": "1", "x": 0.2, "y": 0.3, "cells": [[0, 0, 3, 5]], "blocked": [[1, 2]]},
        {"number": "2", "x": 0.7, "y": 0.3, "cells": [[6, 0, 9, 5]]},
    ],
}


def publish_sample(settings) -> str:
    draft, errors, _ = modules.check(sample(), ROOT)
    assert errors == []

    async def go(s):
        m = AdventureModule(title=draft["title"], slug=draft["slug"], status="review", draft=draft)
        s.add(m)
        await s.flush()
        mid = m.id
        await modules.publish(s, draft, [CRYPT_MAP], "1.0.0", ROOT, mid)
        m = await s.get(AdventureModule, mid)
        m.pack_id, m.pack_version, m.status = "module-unquiet-dead", "1.0.0", "published"
        await s.commit()
        return mid

    return run(settings, go)


def test_module_tools_stay_off_in_a_regular_campaign(client, admin, settings):
    import_base(settings)
    c, _, _ = party(client, admin)

    async def tools(ctx):
        return decision_tools(ctx)

    assert "enter_room" not in _play(settings, c["id"], tools)

    async def campaign(s):
        return (await s.get(Campaign, c["id"])).settings

    assert "module" not in run(settings, campaign)


def test_find_room_resilient_matching():
    from app.content.catalog import Entry

    rec = Entry(
        id="location.davos_crypt",
        kind="location_template",
        status="active",
        pack_id="pack1",
        data={
            "name": "Семейный склеп Давоса",
            "rooms": [
                {"id": "r1", "name": "Зал Мёртвых", "number": "1"},
                {"id": "graveyard", "name": "Кладбище у мавзолея"},
            ],
        },
    )
    assert adventure.find_room(rec, "1")["id"] == "r1"
    assert adventure.find_room(rec, "r1")["id"] == "r1"
    assert adventure.find_room(rec, "Зал Мёртвых")["id"] == "r1"
    assert adventure.find_room(rec, "комната 1")["id"] == "r1"
    assert adventure.find_room(rec, "room 1")["id"] == "r1"
    assert adventure.find_room(rec, "room_1")["id"] == "r1"
    assert adventure.find_room(rec, "room_1_graveyard_at_the_mausoleum")["id"] == "r1"
    assert adventure.find_room(rec, "graveyard")["id"] == "graveyard"
    assert adventure.find_room(rec, "Кладбище у мавзолея")["id"] == "graveyard"
    assert adventure.find_room(rec, "en_2dd6573b19591abd") is None
    assert adventure.find_room(rec, "en_15aaca9f958785d2") is None
