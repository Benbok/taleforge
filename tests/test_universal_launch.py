import asyncio

from sqlalchemy import select

from app.agents.llm import ScriptedLLM
from app.core.authoring.contracts import InstanceOptions
from app.core.authoring.instances import instantiate_adventure
from app.db.models import AdventureVersion, AuthorProject, Campaign, CampaignSecret, Entity, User
from tests.test_universal_studio import BASE, create, review_reply


def test_two_launches_isolated_and_replay_preserves_receipt(client, root):
    project = create(client, root)
    client.app.state.studio_llm = ScriptedLLM([review_reply()])
    url = f"{BASE}/{project['id']}/studio"
    client.post(url + "/review", headers=root, json={"expected_revision": project["draft_revision"]})
    accepted = client.post(
        url + "/accept", headers=root, json={"expected_revision": project["draft_revision"], "request_key": "accept"}
    )
    assert accepted.status_code == 201, accepted.text

    async def exercise():
        async with client.app.state.sessionmaker() as session:
            version = await session.get(AdventureVersion, accepted.json()["id"])
            authored = await session.get(AuthorProject, project["id"])
            workspace = await session.get(Campaign, authored.workspace_campaign_id)
            owner = await session.get(User, workspace.owner_id)
            import copy

            before = copy.deepcopy(version.bundle)
            options = InstanceOptions(name="Adventure", master={"type": "agent", "provider": "claude", "model": "x"})
            first = await instantiate_adventure(session, owner, version, options, "one")
            second = await instantiate_adventure(session, owner, version, options, "two")
            assert first.campaign_id != second.campaign_id
            assert await instantiate_adventure(session, owner, version, options, "one") == first
            games = [await session.get(Campaign, receipt.campaign_id) for receipt in (first, second)]
            assert all(game.ruleset_id == "universal" for game in games)
            ids = [set(await session.scalars(select(Entity.id).where(Entity.campaign_id == game.id))) for game in games]
            assert ids[0] and ids[0].isdisjoint(ids[1])
            assert all(
                game.settings["studio_entry_location_id"] in entity_ids
                for game, entity_ids in zip(games, ids, strict=True)
            )
            secret = await session.get(CampaignSecret, games[0].id)
            secret.setting = {**secret.setting, "studio": {"laws": "Changed in one game"}}
            await session.flush()
            other = await session.get(CampaignSecret, games[1].id)
            assert other.setting["studio"]["laws"] == before["setting"]["studio"]["laws"]
            assert version.bundle == before

    asyncio.run(exercise())
