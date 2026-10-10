"""Общие заготовки тестов этапа 3: базовый пакет в БД, управляемые кубики, готовый герой в кампании."""

from __future__ import annotations

import asyncio
from pathlib import Path

from app.content.catalog import clear_cache
from app.content.importer import import_pack
from app.content.yaml_io import load_file
from app.db.session import make_engine, make_sessionmaker
from app.rules.dice import Dice
from tests.test_api import invite, make_campaign, register

BASE = Path(__file__).resolve().parents[1] / "content" / "dnd5e-srd"
BASE_VERSION = str(load_file(BASE / "pack.yaml")["version"])

FIGHTER = {
    "name": "Бран",
    "class_id": "class.fighter",
    "origin_id": "origin.human",
    "ability_method": "standard_array",
    "abilities": {"str": 15, "dex": 13, "con": 14, "int": 8, "wis": 12, "cha": 10},
    "skills": ["athletics", "perception"],
    "fighting_style": "protection",
    "equipment_choices": [
        {"choice": 0, "option": 0},
        {"choice": 1, "option": 0, "items": ["item.longsword"]},
        {"choice": 2, "option": 1},
        {"choice": 3, "option": 0},
    ],
    "public_bio": "Широкоплечий наёмник со шрамом.",
    "private_backstory": "Бежал из гарнизона, за ним охотятся.",
}


def run(settings, fn):
    async def go():
        engine = make_engine(settings.database_url)
        try:
            async with make_sessionmaker(engine)() as s:
                return await fn(s)
        finally:
            await engine.dispose()

    return asyncio.run(go())


def import_base(settings) -> None:
    clear_cache()
    run(settings, lambda s: import_pack(s, BASE))


class QueueDice(Dice):
    """Кубики из общей очереди; когда очередь пуста — среднее значение грани. Значение больше грани — ошибка теста."""

    def __init__(self, queue: list[int]):
        super().__init__(seed=0)
        self.queue = queue

    def die(self, sides: int) -> int:
        if self.queue:
            v = self.queue.pop(0)
            assert 1 <= v <= sides, f"в очереди {v} для d{sides}"
            return v
        return (sides + 1) // 2


def ok(r, code=200):
    assert r.status_code == code, r.text
    return r.json()


def party(client, admin, *, players=1, master=None, rules=None, **kw):
    """Кампания с базовым пакетом, игроки и одобренный воин у первого игрока, сессия начата."""
    body = {"creation_rules": {"review": "auto", **(rules or {})}, "collect_window_sec": 0, **kw}
    if master:
        body["master"] = master
    c = make_campaign(client, admin, players=players, **body)
    inv = invite(client, admin, c["id"])
    names = ["Арагорн", "Гимли", "Леголас"]
    heads = [register(client, inv["token"], names[i]) for i in range(players)]
    ch = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=heads[0]), 201)
    res = ok(client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/submit", headers=heads[0]))
    assert res["status"] == "approved", res
    ok(client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin))
    return c, heads, ch
