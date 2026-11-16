import asyncio

from sqlalchemy import delete

from app.db.models import Character, LibraryCharacter
from tests.universal_helpers import DESCRIPTION, PROPOSAL, ready_reply, set_replies
from tools.backfill_library_heroes import backfill

BASE = "/api/hero-creation/dialogues"


def test_old_campaign_hero_gets_one_level_one_library_copy(client, root):
    from tests.test_api import make_campaign

    cid = make_campaign(client, root, owner_plays=True)["id"]
    set_replies(client, [ready_reply()])
    draft = client.post(BASE, headers=root, json=dict(description=DESCRIPTION, campaign_id=cid)).json()
    hero_id = client.post(f"{BASE}/{draft['id']}/confirm", headers=root, json={"expected_revision": draft["revision"]})
    hero_id = hero_id.json()["hero_id"]

    async def run():
        async with client.app.state.sessionmaker(expire_on_commit=False) as session:
            # герой из времени до сохранения в библиотеку: без связи, библиотека пуста, в игре он уже вырос
            await session.execute(delete(LibraryCharacter))
            hero = await session.get(Character, hero_id)
            sheet = {k: v for k, v in hero.sheet.items() if k != "source_library_id"}
            hero.sheet = {**sheet, "level": "3", "xp": "900", "abilities": {**sheet["abilities"], "str": "10"}}
            await session.commit()
            assert await backfill(session, apply=False) == 1
            assert await backfill(session, apply=True) == 1
            assert await backfill(session, apply=True) == 0

    asyncio.run(run())
    [library] = client.get("/api/me/characters", headers=root).json()
    assert library["name"] == DESCRIPTION["name"]
    assert library["level"] == "1" and library["sheet"]["xp"] == "0"
    assert library["sheet"]["abilities"] == PROPOSAL["abilities"]
