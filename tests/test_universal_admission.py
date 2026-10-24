import asyncio

from sqlalchemy import select

from app.db.models import Campaign, CampaignSecret, Character
from tests.test_api import make_campaign
from tests.universal_helpers import create_hero, ready_reply, set_replies


def studio_campaign(client, root):
    campaign = make_campaign(client, root, owner_plays=True)

    async def configure():
        async with client.app.state.sessionmaker() as session:
            row = await session.get(Campaign, campaign["id"])
            row.ruleset_id = "universal"
            row.settings = {**row.settings, "studio_entry_location_id": "entry"}
            secret = await session.get(CampaignSecret, row.id)
            secret.setting = {"studio": {"laws": "No supernatural powers; plants respond only to science."}}
            await session.commit()

    asyncio.run(configure())
    return campaign["id"]


def test_library_admission_requires_confirmed_copy_and_preserves_original(client, root):
    library_id = create_hero(client, root)
    original = client.get("/api/me/characters", headers=root).json()
    cid = studio_campaign(client, root)
    blocked = client.post(f"/api/campaigns/{cid}/characters/from-library/{library_id}", headers=root)
    assert blocked.status_code == 409
    set_replies(
        client,
        [ready_reply(description={"name": "Iva", "identity": "Botanist", "capabilities": "Uses scientific tools"})],
    )
    response = client.post(f"/api/campaigns/{cid}/characters/from-library/{library_id}/admission", headers=root)
    assert response.status_code == 201, response.text
    draft = response.json()
    assert all(message["role"] in ("user", "assistant") for message in draft["transcript"])
    assert "Adapt only this campaign copy" not in response.text
    reloaded = client.get(f"/api/hero-creation/dialogues/{draft['id']}", headers=root)
    assert "source_revision" not in reloaded.text
    assert "Adapt only this campaign copy" not in reloaded.text
    assert "No supernatural powers" in str(client.app.state.hero_llm.requests)

    async def count():
        async with client.app.state.sessionmaker() as session:
            return len((await session.scalars(select(Character).where(Character.campaign_id == cid))).all())

    assert asyncio.run(count()) == 0
    body = {"expected_revision": draft["revision"]}
    url = f"/api/hero-creation/dialogues/{draft['id']}/confirm"
    first = client.post(url, headers=root, json=body)
    assert first.status_code == 200, first.text
    assert client.post(url, headers=root, json=body).json() == first.json()
    assert asyncio.run(count()) == 1
    assert client.get("/api/me/characters", headers=root).json() == original

    async def copied():
        async with client.app.state.sessionmaker() as session:
            return await session.get(Character, first.json()["hero_id"])

    hero = asyncio.run(copied())
    assert hero.location_id == "entry"
    assert hero.sheet["level"] == "1" and hero.sheet["xp"] == "0"
    assert hero.sheet["starting_equipment"] == original[0]["sheet"]["starting_equipment"]


def test_direct_world_creation_asks_before_incompatible_hero_can_join(client, root):
    cid = studio_campaign(client, root)
    set_replies(client, [ready_reply(question="Magic is impossible here. Will you use botany instead?", proposal=None)])
    response = client.post(
        "/api/hero-creation/dialogues",
        headers=root,
        json={"campaign_id": cid, "description": {"identity": "Plant wizard"}},
    )
    assert response.status_code == 201, response.text
    draft = response.json()
    assert draft["status"] == "questions"
    assert "No supernatural powers" in str(client.app.state.hero_llm.requests)
    rejected = client.post(
        f"/api/hero-creation/dialogues/{draft['id']}/confirm",
        headers=root,
        json={"expected_revision": draft["revision"]},
    )
    assert rejected.status_code == 409


def test_stale_library_adaptation_cannot_join(client, root):
    library_id = create_hero(client, root)
    cid = studio_campaign(client, root)
    set_replies(client, [ready_reply()])
    draft = client.post(f"/api/campaigns/{cid}/characters/from-library/{library_id}/admission", headers=root).json()

    async def edit_original():
        from app.db.models import LibraryCharacter

        async with client.app.state.sessionmaker() as session:
            original = await session.get(LibraryCharacter, library_id)
            original.revision += 1
            await session.commit()

    asyncio.run(edit_original())
    rejected = client.post(
        f"/api/hero-creation/dialogues/{draft['id']}/confirm",
        headers=root,
        json={"expected_revision": draft["revision"]},
    )
    assert rejected.status_code == 409


def test_admission_preserves_library_portrait(client, root):
    from app.db.models import LibraryCharacter

    library_id = create_hero(client, root)

    async def portrait():
        async with client.app.state.sessionmaker() as session:
            original = await session.get(LibraryCharacter, library_id)
            original.portrait_id = "preserved-portrait"
            await session.commit()

    asyncio.run(portrait())
    cid = studio_campaign(client, root)
    set_replies(client, [ready_reply()])
    draft = client.post(f"/api/campaigns/{cid}/characters/from-library/{library_id}/admission", headers=root).json()
    response = client.post(
        f"/api/hero-creation/dialogues/{draft['id']}/confirm",
        headers=root,
        json={"expected_revision": draft["revision"]},
    )
    assert response.status_code == 200, response.text

    async def check():
        async with client.app.state.sessionmaker() as session:
            return (await session.get(Character, response.json()["hero_id"])).portrait_id

    assert asyncio.run(check()) == "preserved-portrait"


def test_admission_rejects_library_change_during_guidance(client, root):
    from app.db.models import HeroDialogue, LibraryCharacter

    library_id = create_hero(client, root)
    cid = studio_campaign(client, root)

    async def mutate():
        async with client.app.state.sessionmaker() as session:
            original = await session.get(LibraryCharacter, library_id)
            original.revision += 1
            await session.commit()

    def reply(messages, tools):
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(lambda: asyncio.run(mutate())).result()
        return ready_reply()

    set_replies(client, [reply])
    response = client.post(f"/api/campaigns/{cid}/characters/from-library/{library_id}/admission", headers=root)
    assert response.status_code == 409

    async def check():
        async with client.app.state.sessionmaker() as session:
            return (await session.scalar(select(HeroDialogue).where(HeroDialogue.campaign_id == cid))).status

    assert asyncio.run(check()) == "questions"


def test_player_guidance_does_not_receive_master_secrets(client, root):
    cid = studio_campaign(client, root)

    async def secrets():
        async with client.app.state.sessionmaker() as session:
            secret = await session.get(CampaignSecret, cid)
            secret.setting = {
                "studio": {**secret.setting["studio"], "history": "HIDDEN-HISTORY", "secret_text": "HIDDEN-PLOT"}
            }
            await session.commit()

    asyncio.run(secrets())
    set_replies(client, [ready_reply()])
    response = client.post(
        "/api/hero-creation/dialogues", headers=root, json={"campaign_id": cid, "description": {"identity": "Botanist"}}
    )
    assert response.status_code == 201, response.text
    requests = str(client.app.state.hero_llm.requests)
    assert "No supernatural powers" in requests
    assert "HIDDEN-HISTORY" not in requests and "HIDDEN-PLOT" not in requests
