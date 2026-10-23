import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.agents.llm import LLMReply
from tests.universal_helpers import DESCRIPTION, create_hero, ready_reply, set_replies

BASE = "/api/hero-creation/dialogues"


@pytest.mark.parametrize("questions", [False, True])
def test_delete_own_draft_keeps_created_heroes(client, root, questions):
    hero_id = create_hero(client, root)
    reply = ready_reply(question="Как действует герой?", proposal=None) if questions else ready_reply()
    set_replies(client, [reply])
    draft = client.post(BASE, headers=root, json={"description": DESCRIPTION}).json()
    url = f"{BASE}/{draft['id']}"
    result = client.delete(url, headers=root, params={"expected_revision": draft["revision"]})
    assert result.status_code == 204, result.text
    assert client.get(url, headers=root).status_code == 404
    assert client.get(BASE, headers=root).json() == []
    assert client.get(f"/api/me/characters/{hero_id}", headers=root).status_code == 200


def test_delete_rejects_foreign_stale_and_confirmed_drafts(client, root):
    from tests.test_profile import signup

    set_replies(client, [ready_reply(), ready_reply()])
    draft = client.post(BASE, headers=root, json={"description": DESCRIPTION}).json()
    url = f"{BASE}/{draft['id']}"
    other = signup(client, "Другой")
    params = {"expected_revision": draft["revision"]}
    assert client.delete(url, headers=other, params=params).status_code == 404
    assert client.delete(url, params=params).status_code == 401
    updated = client.post(
        url + "/answers", headers=root, json={"expected_revision": draft["revision"], "answer": "Уточняю замысел"}
    ).json()
    assert client.delete(url, headers=root, params=params).status_code == 409
    confirmed = client.post(url + "/confirm", headers=root, json={"expected_revision": updated["revision"]}).json()
    assert client.delete(url, headers=root, params={"expected_revision": updated["revision"] + 1}).status_code == 409
    assert client.get(f"/api/me/characters/{confirmed['hero_id']}", headers=root).status_code == 200


def test_deleted_draft_is_not_recreated_by_inflight_model(client, root):
    set_replies(client, [ready_reply(question="Как действует герой?", proposal=None)])
    draft = client.post(BASE, headers=root, json={"description": DESCRIPTION}).json()
    url = f"{BASE}/{draft['id']}"
    started, release = threading.Event(), threading.Event()

    class SlowLLM:
        async def complete(self, *args, **kwargs):
            started.set()
            assert await asyncio.to_thread(release.wait, 10)
            return LLMReply(text=ready_reply()["text"])

    client.app.state.hero_llm = SlowLLM()
    with ThreadPoolExecutor(1) as pool:
        answer = pool.submit(
            client.post,
            url + "/answers",
            headers=root,
            json={"expected_revision": draft["revision"], "answer": "Отвечаю"},
        )
        try:
            assert started.wait(10)
            assert client.delete(url, headers=root, params={"expected_revision": draft["revision"]}).status_code == 204
        finally:
            release.set()
        assert answer.result(timeout=10).status_code == 409
    assert client.get(url, headers=root).status_code == 404
    assert client.get("/api/me/characters", headers=root).json() == []
