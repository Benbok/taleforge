import asyncio
import json

from sqlalchemy import select

from app.agents.llm import ScriptedLLM
from app.db.models import AdventureVersion, AuthorProject, Campaign, LlmCall

BASE = "/api/author/projects"
FIELDS = dict(
    title="Glass islands",
    premise="Explore the lost harbor",
    world="Floating islands",
    laws="SECRET-LAW: nobody can fly",
    inhabitants="Sailors",
    powers="Wind machines",
    history="SECRET-HISTORY: the harbor sank",
    start="At the harbor gate",
    style="Exploration",
    difficulty="normal",
    excluded_themes=["cruelty"],
    public_text="A harbor awaits.",
    secret_text="SECRET-PLOT: the captain is a ghost",
)


def create(client, root):
    response = client.post(BASE, headers=root, json={"title": FIELDS["title"], "studio": FIELDS})
    assert response.status_code == 201, response.text
    return response.json()


def review_reply(question=None):
    return {"text": json.dumps({"question": question, "notes": ["The premise is coherent."]})}


def test_review_revision_and_immutable_acceptance(client, root):
    project = create(client, root)
    pid, rev = project["id"], project["draft_revision"]
    url = f"{BASE}/{pid}/studio"
    assert (
        client.post(url + "/accept", headers=root, json={"expected_revision": rev, "request_key": "early"}).status_code
        == 409
    )
    client.app.state.studio_llm = ScriptedLLM(
        [review_reply("How do sailors travel if nobody can fly?"), review_reply()]
    )
    asked = client.post(url + "/review", headers=root, json={"expected_revision": rev})
    assert asked.status_code == 200, asked.text
    assert asked.json()["status"] == "questions"
    assert "travel" in asked.json()["question"]
    assert (
        client.post(
            url + "/accept", headers=root, json={"expected_revision": rev, "request_key": "question"}
        ).status_code
        == 409
    )
    ready = client.post(
        url + "/review",
        headers=root,
        json={"expected_revision": rev, "answer": "They sail between islands, without flight."},
    )
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "ready"
    saved = client.get(url, headers=root).json()
    assert saved["fields"] == FIELDS
    accepted = client.post(url + "/accept", headers=root, json={"expected_revision": rev, "request_key": "accept1"})
    assert accepted.status_code == 201, accepted.text
    assert "SECRET" not in str(accepted.json()["public_summary"])
    version = accepted.json()
    assert version["source_revision"] == rev
    assert (
        client.post(url + "/accept", headers=root, json={"expected_revision": rev, "request_key": "accept1"}).json()[
            "id"
        ]
        == version["id"]
    )
    changed = client.put(
        url, headers=root, json={"expected_revision": rev, "fields": {**FIELDS, "premise": "New exploration"}}
    )
    assert changed.status_code == 200, changed.text
    new_rev = changed.json()["draft_revision"]
    assert new_rev > rev
    stale = client.post(url + "/review", headers=root, json={"expected_revision": rev})
    assert stale.status_code == 409
    assert (
        client.post(
            f"{BASE}/{pid}/publish", headers=root, json={"expected_revision": new_rev, "request_key": "bypass"}
        ).status_code
        == 409
    )

    async def check():
        async with client.app.state.sessionmaker() as s:
            rows = list(await s.scalars(select(AdventureVersion).where(AdventureVersion.project_id == pid)))
            assert len(rows) == 1
            assert rows[0].bundle["setting"]["studio"] == FIELDS
            assert rows[0].bundle["meta"]["ruleset_id"] == "universal"
            assert len(list(await s.scalars(select(LlmCall).where(LlmCall.purpose == "studio_review")))) == 2

    asyncio.run(check())


def test_review_cannot_authorize_concurrently_changed_content(client, root):
    project = create(client, root)
    pid, rev = project["id"], project["draft_revision"]
    url = f"{BASE}/{pid}/studio"

    async def mutate():
        async with client.app.state.sessionmaker() as s:
            p = await s.get(AuthorProject, pid)
            p.draft_revision += 1
            await s.commit()

    def reply(messages, tools):
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(lambda: asyncio.run(mutate())).result()
        return review_reply()

    client.app.state.studio_llm = ScriptedLLM([reply])
    response = client.post(url + "/review", headers=root, json={"expected_revision": rev})
    assert response.status_code == 409
    assert client.get(url, headers=root).json()["review"] is None


def test_studio_does_not_require_catalog_or_pregeneration_and_checks_ownership(client, root):
    project = create(client, root)
    url = f"{BASE}/{project['id']}/studio"
    from tests.test_profile import signup

    other = signup(client, "Other author")
    assert client.get(url, headers=other).status_code == 404
    client.app.state.studio_llm = ScriptedLLM([review_reply()])
    reviewed = client.post(url + "/review", headers=root, json={"expected_revision": project["draft_revision"]})
    assert reviewed.status_code == 200, reviewed.text
    accepted = client.post(
        url + "/accept",
        headers=root,
        json={"expected_revision": project["draft_revision"], "request_key": "no-generators"},
    )
    assert accepted.status_code == 201, accepted.text

    async def check():
        async with client.app.state.sessionmaker() as s:
            world = await s.get(Campaign, (await s.get(AuthorProject, project["id"])).workspace_campaign_id)
            assert world.pack_id is None and world.ruleset_id == "universal"

    asyncio.run(check())


def test_malformed_review_preserves_fields_and_readiness(client, root):
    project = create(client, root)
    url = f"{BASE}/{project['id']}/studio"
    client.app.state.studio_llm = ScriptedLLM(
        [{"text": json.dumps({"question": None, "notes": [], "laws": "Everyone flies"})}]
    )
    response = client.post(url + "/review", headers=root, json={"expected_revision": project["draft_revision"]})
    assert response.status_code == 409
    saved = client.get(url, headers=root).json()
    assert saved["fields"] == FIELDS and saved["review"] is None


def test_empty_start_cannot_be_accepted_even_if_model_says_ready(client, root):
    incomplete = {**FIELDS, "start": ""}
    project = client.post(BASE, headers=root, json={"title": FIELDS["title"], "studio": incomplete}).json()
    url = f"{BASE}/{project['id']}/studio"
    client.app.state.studio_llm = ScriptedLLM([review_reply()])
    reviewed = client.post(url + "/review", headers=root, json={"expected_revision": project["draft_revision"]})
    assert reviewed.status_code == 200, reviewed.text
    assert reviewed.json()["status"] == "questions"
    assert "start" in reviewed.json()["question"]
    assert (
        client.post(
            url + "/accept",
            headers=root,
            json={"expected_revision": project["draft_revision"], "request_key": "empty-start"},
        ).status_code
        == 409
    )


def test_stale_save_preserves_saved_facts_and_latest_question_revokes_readiness(client, root):
    project = create(client, root)
    url = f"{BASE}/{project['id']}/studio"
    rev = project["draft_revision"]
    stale = client.put(
        url, headers=root, json={"expected_revision": rev + 1, "fields": {**FIELDS, "laws": "Everyone flies"}}
    )
    assert stale.status_code == 409
    assert client.get(url, headers=root).json()["fields"] == FIELDS
    client.app.state.studio_llm = ScriptedLLM([review_reply(), review_reply("What moves the ships?")])
    assert client.post(url + "/review", headers=root, json={"expected_revision": rev}).json()["status"] == "ready"
    assert client.post(url + "/review", headers=root, json={"expected_revision": rev}).json()["status"] == "questions"
    assert (
        client.post(
            url + "/accept", headers=root, json={"expected_revision": rev, "request_key": "old-ready"}
        ).status_code
        == 409
    )


def test_optional_generated_objects_do_not_replace_authored_entry_scene(client, root):
    from app.db.models import Entity

    project = create(client, root)
    pid = project["id"]

    async def generated():
        async with client.app.state.sessionmaker() as s:
            p = await s.get(AuthorProject, pid)
            s.add(Entity(campaign_id=p.workspace_campaign_id, kind="item", name="Optional compass", state={}))
            await s.commit()

    asyncio.run(generated())
    url = f"{BASE}/{pid}/studio"
    rev = client.get(url, headers=root).json()["draft_revision"]
    client.app.state.studio_llm = ScriptedLLM([review_reply()])
    assert client.post(url + "/review", headers=root, json={"expected_revision": rev}).status_code == 200
    response = client.post(
        url + "/accept", headers=root, json={"expected_revision": rev, "request_key": "optional-content"}
    )
    assert response.status_code == 201, response.text

    async def check():
        async with client.app.state.sessionmaker() as s:
            bundle = (await s.get(AdventureVersion, response.json()["id"])).bundle
            assert bundle["meta"]["studio_entry_ref"] == "studio_entry"
            assert len(bundle["entities"]) == 2
            assert next(e for e in bundle["entities"] if e["ref"] == "studio_entry")["description"] == FIELDS["start"]

    asyncio.run(check())
