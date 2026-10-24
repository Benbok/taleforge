from tests.universal_helpers import PROPOSAL, create_hero, ready_reply, set_replies


def test_equipment_regeneration_previews_then_confirms_without_changing_hero_or_game_copy(client, root):
    from tests.test_api import make_campaign

    hid = create_hero(client, root)
    url = f"/api/me/characters/{hid}"
    before = client.get(url, headers=root).json()
    cid = make_campaign(client, root, owner_plays=True)["id"]
    copied = client.post(f"/api/campaigns/{cid}/characters/from-library/{hid}", headers=root).json()
    equipment = {**PROPOSAL["equipment"], "weapon": {**PROPOSAL["equipment"]["weapon"], "name": "Лесной клинок"}}
    set_replies(client, [ready_reply(proposal={**PROPOSAL, "equipment": equipment})])
    proposed = client.post(url + "/equipment-proposals", headers=root, json={"expected_revision": before["revision"]})
    assert proposed.status_code == 201, proposed.text
    assert client.get(url, headers=root).json() == before
    preview = proposed.json()
    assert preview["edit"]["starting_equipment"]["weapon"]["name"] == "Лесной клинок"
    assert preview["edit"]["description_patch"] == {}
    assert preview["edit"]["base_scores"] is None
    confirm = url + f"/edit-proposals/{preview['id']}/confirm"
    saved = client.post(confirm, headers=root, json={"request_key": "equipment-one"})
    assert saved.status_code == 200, saved.text
    card = saved.json()
    assert card["equipment"][0]["name"] == "Лесной клинок"
    assert card["sheet"]["abilities"] == before["sheet"]["abilities"]
    assert card["sheet"]["description"] == before["sheet"]["description"]
    assert card["revision"] == before["revision"] + 1
    assert client.post(confirm, headers=root, json={"request_key": "equipment-replay"}).json() == card
    assert len(client.app.state.hero_llm.requests) == 1
    game_card = client.get(f"/api/campaigns/{cid}/characters/{copied['id']}", headers=root).json()
    assert game_card["equipment"] == copied["equipment"]


def test_equipment_failure_and_stale_confirmation_preserve_saved_items(client, root):
    hid = create_hero(client, root)
    url = f"/api/me/characters/{hid}"
    before = client.get(url, headers=root).json()
    set_replies(client, [ready_reply(proposal={**PROPOSAL, "equipment": None})])
    assert client.post(url + "/equipment-proposals", headers=root, json={"expected_revision": 1}).status_code == 409
    assert client.get(url, headers=root).json() == before
    set_replies(client, [ready_reply()])
    preview = client.post(url + "/equipment-proposals", headers=root, json={"expected_revision": 1}).json()
    edited = client.patch(
        url,
        headers=root,
        json={"edit": {"expected_revision": 1, "description_patch": {"name": "Ива новая"}}, "request_key": "rename"},
    )
    assert edited.status_code == 200
    assert (
        client.post(
            url + f"/edit-proposals/{preview['id']}/confirm", headers=root, json={"request_key": "stale"}
        ).status_code
        == 409
    )
    assert client.get(url, headers=root).json()["equipment"] == before["equipment"]
