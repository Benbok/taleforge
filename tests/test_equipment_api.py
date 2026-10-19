"""REST access and response contract for player equipment changes."""

from tests.game import import_base, ok, party


def test_player_can_change_own_equipment_and_receives_updated_sheet(client, admin, settings):
    import_base(settings)
    campaign, (player,), hero = party(client, admin)
    cid, hid = campaign["id"], hero["id"]
    sheet = ok(client.get(f"/api/campaigns/{cid}/characters/{hid}", headers=player))
    shield = next(item for item in sheet["inventory"] if item["item"] == "item.shield")
    response = client.put(
        f"/api/campaigns/{cid}/characters/{hid}/equipment",
        json={"inventory_id": shield["id"], "equipped": False},
        headers=player,
    )
    body = ok(response)
    changed = next(item for item in body["character"]["inventory"] if item["id"] == shield["id"])
    assert not changed["equipped"]
    assert body["economy"] is None
    assert body["character"]["equipment"]["can_manage"] is True


def test_other_player_cannot_change_hero_equipment(client, admin, settings):
    import_base(settings)
    campaign, (owner, other), hero = party(client, admin, players=2)
    cid, hid = campaign["id"], hero["id"]
    sheet = ok(client.get(f"/api/campaigns/{cid}/characters/{hid}", headers=owner))
    shield = next(item for item in sheet["inventory"] if item["item"] == "item.shield")
    response = client.put(
        f"/api/campaigns/{cid}/characters/{hid}/equipment",
        json={"inventory_id": shield["id"], "equipped": False},
        headers=other,
    )
    assert response.status_code == 403
