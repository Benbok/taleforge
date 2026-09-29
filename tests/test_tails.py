# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Хвосты после этапа 7: запись в БД во время ИИ-проверки героя, стартовое снаряжение пакета, имена предметов."""

import sqlite3

import pytest

from tests.game import FIGHTER, ok
from tests.test_api import invite, make_campaign, register
from tests.test_master import admin_g, dice, game_client, llm  # noqa: F401 — фикстуры
from tests.test_ws import connect


def test_db_writable_while_model_reviews_hero(game_client, admin_g, llm, settings):
    if not settings.database_url.startswith("sqlite"):
        pytest.skip("блокировка файла — особенность SQLite")
    path = settings.database_url.split("///", 1)[1]
    c = make_campaign(game_client, admin_g, players=1)
    p1 = register(game_client, invite(game_client, admin_g, c["id"])["token"], "Арагорн")
    ch = ok(game_client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=p1), 201)
    wrote = []

    def review(messages, tools):
        # пока «модель думает», кто-то другой пишет в БД: раньше здесь был «database is locked»
        db = sqlite3.connect(path, timeout=1)
        try:
            db.execute("UPDATE campaigns SET name = name")
            db.commit()
            wrote.append(True)
        finally:
            db.close()
        return {"tool_calls": [("review_character", {"character_id": ch["id"], "approve": True, "comment": "Да"})]}

    llm.replies += [review]
    with connect(game_client, p1, c["id"]) as (ws, _):
        ok(game_client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/submit", headers=p1))
        e = ws.receive_json()
        while e["type"] not in ("character.reviewed", "character.review_failed"):
            e = ws.receive_json()
    assert e["type"] == "character.reviewed", e["payload"]
    assert wrote and e["payload"]["status"] == "approved"


def test_diagnost_starting_gear_is_given_as_items():
    import yaml

    from app.rules.dnd5e.character import starting_items

    raw = yaml.safe_load(open("content/echo-leviathans/data/classes/diagnost.yaml", encoding="utf-8"))
    cls = next(c for c in raw["items"] if c["id"] == "class.diagnost")
    ids = ["item.injector", "item.scale_mail", "item.pleural_armor", "item.dart_launcher", "item.ammo_darts"]
    items = {i: {"id": i} for i in ids + ["item.light_crossbow"]}
    got, errors = starting_items(cls, [{"choice": 0, "option": 1}, {"choice": 1, "option": 0}], items)
    assert not errors
    assert [x["item"] for x in got] == ["item.injector", "item.pleural_armor", "item.dart_launcher", "item.ammo_darts"]
    _, errors = starting_items(cls, [], items)
    assert errors == ["снаряжение: не выбран вариант 1", "снаряжение: не выбран вариант 2"]
