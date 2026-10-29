"""Общие заготовки тестов этапа 3: базовый пакет в БД, управляемые кубики, готовый герой в кампании."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

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


def add_hero(client, campaign_id, head, name=None, *, abilities=None):
    """Герой через универсальный диалог создания: создать, подтвердить, вернуть карточку героя кампании."""
    from copy import deepcopy

    from tests.universal_helpers import DESCRIPTION, PROPOSAL, ready_reply, set_replies

    proposal = deepcopy(PROPOSAL)
    proposal["abilities"] = {key: str(value) for key, value in (abilities or FIGHTER["abilities"]).items()}
    description = {**DESCRIPTION, "name": name or FIGHTER["name"], "identity": FIGHTER["public_bio"]}
    previous = client.app.state.hero_llm
    try:
        set_replies(client, [ready_reply(description=description, proposal=proposal)])
        draft = ok(
            client.post(
                "/api/hero-creation/dialogues",
                json={"campaign_id": campaign_id, "description": description},
                headers=head,
            ),
            201,
        )
        confirmed = ok(
            client.post(
                f"/api/hero-creation/dialogues/{draft['id']}/confirm",
                json={"expected_revision": draft["revision"]},
                headers=head,
            )
        )
    finally:
        client.app.state.hero_llm = previous
    return ok(client.get(f"/api/campaigns/{campaign_id}/characters/{confirmed['hero_id']}", headers=head))


def party(
    client,
    admin,
    *,
    players=1,
    master=None,
    rules=None,
    names=None,
    start=True,
    location_layouts=False,
    location_layouts_llm=False,
    **kw,
):
    """Кампания с базовым пакетом, игроки и одобренный воин у первого игрока, сессия начата."""
    body = {"creation_rules": {"review": "auto", **(rules or {})}, "collect_window_sec": 0, **kw}
    if master:
        body["master"] = master
    c = make_campaign(client, admin, players=players, **body)
    # Legacy gameplay scenarios script narration only; layout scenarios explicitly enable generation.
    c = ok(
        client.patch(
            f"/api/campaigns/{c['id']}",
            json={"location_layouts": location_layouts, "location_layouts_llm": location_layouts_llm},
            headers=admin,
        )
    )
    inv = invite(client, admin, c["id"])
    names = names or ["Арагорн", "Гимли", "Леголас"]
    heads = [register(client, inv["token"], names[i]) for i in range(players)]
    ch = add_hero(client, c["id"], heads[0], FIGHTER["name"])
    if start:
        ok(client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin))
        quiet(client)  # the session greeting is written first; it is not part of what scenarios script or count
        getattr(client.app.state.master.llm, "requests", []).clear()
    return c, heads, ch


def quiet(client) -> None:
    """Дождаться фоновых задач мастера (открытие сессии пишет настройки кампании и двигает ревизию мира), чтобы
    шаги теста не конфликтовали с ними по времени."""
    master = client.app.state.master

    async def wait():
        while any(not t.done() for t in list(master._background)):
            await asyncio.sleep(0.05)

    client.portal.call(wait)


ECHO = Path(__file__).resolve().parents[1] / "content" / "echo-leviathans"


@pytest.fixture
def worlds(settings):
    """Base pack plus the Echo pack imported into the test database."""
    import_base(settings)
    run(settings, lambda s: import_pack(s, ECHO))
