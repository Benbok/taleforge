"""Регрессии единой топологии карты: книга сильнее старых links и разметки."""

from app.content.catalog import Catalog, Entry
from app.core import sketch
from app.core.topology import LocationExit, location_exits
from app.db.models import Entity


def _book():
    rec = Entry(
        id="location.test_crypt",
        kind="location_template",
        status="canon",
        pack_id="test",
        data={
            "name": "Крипта",
            "rooms": [
                {"id": "r1", "number": "1", "name": "Преддверие", "exits": ["r2"]},
                {"id": "r2", "number": "2", "name": "Скрытая крипта", "exits": ["r1"]},
            ],
        },
    )
    catalog = Catalog({rec.id: rec}).view(False)
    parent = Entity(id="en_crypt", campaign_id="cp_test", kind="location", name="Крипта", template_id=rec.id, state={})
    r1 = Entity(
        id="en_room_1",
        campaign_id="cp_test",
        kind="location",
        name="Преддверие",
        location_id=parent.id,
        state={"room": {"of": rec.id, "id": "r1", "number": "1"}, "links": [{"to": "en_false"}]},
    )
    r2 = Entity(
        id="en_room_2",
        campaign_id="cp_test",
        kind="location",
        name="Скрытая крипта",
        location_id=parent.id,
        state={"room": {"of": rec.id, "id": "r2", "number": "2"}},
    )
    stray = Entity(id="en_false", campaign_id="cp_test", kind="location", name="Старый путь", state={})
    return catalog, parent, r1, r2, stray


def test_book_exits_ignore_legacy_links():
    catalog, parent, r1, r2, stray = _book()
    places = {e.id: e for e in (parent, r1, r2, stray)}
    assert location_exits(r1, catalog, places) == [
        LocationExit(target_id=r2.id, room_ref="r2", label="Комната 2", bearing=None)
    ]
    # Родитель для карты является группой, но не дополнительным физическим выходом.
    assert all(e.target_id != parent.id for e in location_exits(r1, catalog, places))


def test_book_exit_survives_missing_entity():
    catalog, parent, r1, _, stray = _book()
    places = {e.id: e for e in (parent, r1, stray)}
    before = dict(places)
    assert location_exits(r1, catalog, places) == [
        LocationExit(target_id=None, room_ref="r2", label="Комната 2", bearing=None)
    ]
    assert places == before  # просмотр карты не материализует соседнюю комнату


def test_unmarked_exit_is_available_without_grid_portal():
    catalog, parent, r1, _, _ = _book()
    route = location_exits(r1, catalog, {e.id: e for e in (parent, r1)})
    sketch_data = sketch.from_book(
        {"cells": [[0, 0, 2, 2]], "blocked": []},
        {"cols": 8, "rows": 8},
        [(e.label, e.target_id, e.room_ref) for e in route],
    )
    assert sketch_data is not None
    assert sketch_data["exits"] == []
    assert sketch_data["unplaced_exits"] == [
        {"name": "Комната 2", "to": None, "room_ref": "r2"}
    ]


def test_free_campaign_preserves_links_reverse_links_and_containment():
    square = Entity(
        id="en_square", campaign_id="cp_test", kind="location", name="Площадь",
        state={"links": [{"to": "en_docks", "label": "переулок", "bearing": "e"}]},
    )
    docks = Entity(id="en_docks", campaign_id="cp_test", kind="location", name="Доки", state={})
    shop = Entity(id="en_shop", campaign_id="cp_test", kind="location", name="Лавка",
                  location_id=square.id, state={})
    places = {e.id: e for e in (square, docks, shop)}
    assert location_exits(square, None, places) == [
        LocationExit(docks.id, None, "переулок", "e"),
        LocationExit(shop.id, None, "внутри", None),
    ]
    assert LocationExit(square.id, None, "переулок", None) in location_exits(docks, None, places)
    assert location_exits(shop, None, places) == [LocationExit(square.id, None, "наружу", None)]
