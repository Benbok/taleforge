from tests.universal_helpers import DESCRIPTION, PROPOSAL, create_hero, ready_reply, set_replies

EQUIPMENT = {
    "weapon": {
        "name": "Посох травницы",
        "description": "Прочный дорожный посох с резной рукоятью.",
        "reason": "Подходит путешественнице, знакомой с лесом.",
        "attack_ability": "str",
    },
    "armor": {
        "name": "Стёганый дорожный жилет",
        "description": "Зелёный жилет под плащом.",
        "reason": "Лёгкая защита для долгих походов.",
    },
}


def test_master_proposal_saves_exactly_one_weapon_and_armor(client, root):
    set_replies(client, [ready_reply(proposal={**PROPOSAL, "equipment": EQUIPMENT})])
    draft = client.post("/api/hero-creation/dialogues", headers=root, json={"description": DESCRIPTION})
    assert draft.status_code == 201, draft.text
    draft = draft.json()
    gear = draft["proposal"]["equipment"]
    assert gear["weapon"]["name"] == "Посох травницы"
    assert gear["armor"]["defense_bonus"] == "1"
    assert client.get("/api/me/characters", headers=root).json() == []
    confirm = client.post(
        f"/api/hero-creation/dialogues/{draft['id']}/confirm",
        headers=root,
        json={"expected_revision": draft["revision"]},
    )
    assert confirm.status_code == 200, confirm.text
    card = client.get(f"/api/me/characters/{confirm.json()['hero_id']}", headers=root).json()
    assert [item["kind"] for item in card["equipment"]] == ["weapon", "armor"]
    assert all(item["quantity"] == "1" and item["status"] == "common" for item in card["equipment"])
    assert card["derived"]["ac"] == "14"
    assert card["sheet"]["level"] == "1"
    assert (
        client.post(
            f"/api/hero-creation/dialogues/{draft['id']}/confirm",
            headers=root,
            json={"expected_revision": draft["revision"]},
        ).json()
        == confirm.json()
    )
    assert len(client.app.state.hero_llm.requests) == 1


def test_manual_edit_and_campaign_copy_preserve_generated_items(client, root):
    from tests.test_api import make_campaign

    hid = create_hero(client, root)
    before = client.get(f"/api/me/characters/{hid}", headers=root).json()
    assert len(before["equipment"]) == 2
    edited = client.patch(
        f"/api/me/characters/{hid}",
        headers=root,
        json={"request_key": "rename", "edit": {"expected_revision": 1, "description_patch": {"name": "Новая Ива"}}},
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["equipment"] == before["equipment"]
    cid = make_campaign(client, root, owner_plays=True)["id"]
    copied = client.post(f"/api/campaigns/{cid}/characters/from-library/{hid}", headers=root)
    assert copied.status_code == 201, copied.text
    assert copied.json()["equipment"] == before["equipment"]
    assert copied.json()["derived"]["ac"] == before["derived"]["ac"]


def test_overpowered_or_missing_gear_preserves_unconfirmed_draft(client, root):
    for equipment in (
        None,
        {**EQUIPMENT, "armor": {**EQUIPMENT["armor"], "defense_bonus": "999"}},
        {**EQUIPMENT, "weapon": {**EQUIPMENT["weapon"], "quantity": "2"}},
        {**EQUIPMENT, "weapon": {**EQUIPMENT["weapon"], "status": "epic"}},
    ):
        set_replies(client, [ready_reply(proposal={**PROPOSAL, "equipment": equipment})])
        response = client.post("/api/hero-creation/dialogues", headers=root, json={"description": DESCRIPTION})
        assert response.status_code == 409, response.text
    assert client.get("/api/me/characters", headers=root).json() == []


def test_older_saved_proposal_requires_explicit_equipment_review(client, root):
    import asyncio

    from app.db.models import HeroDialogue

    set_replies(client, [ready_reply(), ready_reply()])
    draft = client.post("/api/hero-creation/dialogues", headers=root, json={"description": DESCRIPTION}).json()

    async def remove_gear():
        async with client.app.state.sessionmaker() as session:
            saved = await session.get(HeroDialogue, draft["id"])
            saved.proposal = {key: value for key, value in saved.proposal.items() if key != "equipment"}
            await session.commit()

    asyncio.run(remove_gear())
    url = f"/api/hero-creation/dialogues/{draft['id']}"
    assert client.post(url + "/confirm", headers=root, json={"expected_revision": draft["revision"]}).status_code == 409
    assert len(client.app.state.hero_llm.requests) == 1
    updated = client.post(
        url + "/answers",
        headers=root,
        json={"expected_revision": draft["revision"], "answer": "Подбери оружие и броню"},
    ).json()
    assert updated["proposal"]["equipment"]["weapon"]["quantity"] == "1"
    assert (
        client.post(url + "/confirm", headers=root, json={"expected_revision": updated["revision"]}).status_code == 200
    )
