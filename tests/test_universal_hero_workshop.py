from fastapi.testclient import TestClient

from app.main import create_app
from tests.universal_helpers import DESCRIPTION, SCORES, create_hero, ready_reply, set_replies


def test_workshop_roundtrip(client, root, settings):
    hero_id = create_hero(client, root)
    url = f"/api/me/characters/{hero_id}"
    before = client.get(url, headers=root).json()
    manual = client.patch(
        url,
        headers=root,
        json={
            "edit": {
                "expected_revision": 1,
                "description_patch": {"appearance": "Зелёный плащ"},
                "base_scores": {**SCORES, "con": "15", "wis": "14"},
            },
            "request_key": "manual",
        },
    )
    assert manual.status_code == 200, manual.text
    assert manual.json()["derived"]["hp_max"] == "25"
    set_replies(
        client,
        [
            ready_reply(
                description={**DESCRIPTION, "name": "Ива Лесная", "appearance": "Зелёный плащ"},
                proposal={
                    "abilities": {**SCORES, "con": "15", "wis": "14"},
                    "explanations": dict.fromkeys(SCORES, "Соответствует образу"),
                },
            )
        ],
    )
    preview = client.post(
        url + "/edit-proposals", headers=root, json={"message": "Добавь прозвище", "expected_revision": 2}
    ).json()
    assert client.get(url, headers=root).json() == manual.json()
    saved = client.post(url + f"/edit-proposals/{preview['id']}/confirm", headers=root, json={"request_key": "chat"})
    assert saved.status_code == 200, saved.text
    assert saved.json()["sheet"]["budget"]["growth_total"] == before["sheet"]["budget"]["growth_total"] == "0"
    with TestClient(create_app(settings)) as restarted:
        assert restarted.get(url, headers=root).json() == saved.json()
