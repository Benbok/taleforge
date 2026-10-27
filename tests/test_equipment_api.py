"""Equipment controls use authoritative Universal actions, with retained ownership and replay guards."""

from tests.game import import_base, ok, party


def test_unequip_updates_defense_and_replay_never_repeats_game_time(client, admin, settings):
    import_base(settings)
    campaign, (player,), hero = party(client, admin)
    url = f"/api/campaigns/{campaign['id']}/characters/{hero['id']}"
    before = ok(client.get(url, headers=player))
    armor = next(item for item in before["combat"]["inventory"] if item["kind"] == "armor")
    action = {"kind": "unequip", "item_id": armor["id"], "request_key": "remove-armor"}
    after = ok(client.post(url + "/universal-actions", json=action, headers=player))
    assert int(after["derived"]["ac"]) < int(before["derived"]["ac"])
    repeated = ok(client.post(url + "/universal-actions", json=action, headers=player))
    assert repeated["exploration"]["game_seconds"] == after["exploration"]["game_seconds"]
    assert repeated["derived"] == after["derived"]
    changed = client.post(url + "/universal-actions", json={**action, "kind": "equip"}, headers=player)
    assert changed.status_code == 409


def test_other_player_cannot_change_equipment_or_learn_private_card(client, admin, settings):
    import_base(settings)
    campaign, (player, other), hero = party(client, admin, players=2)
    url = f"/api/campaigns/{campaign['id']}/characters/{hero['id']}"
    before = ok(client.get(url, headers=player))
    armor = next(item for item in before["combat"]["inventory"] if item["kind"] == "armor")
    public = ok(client.get(url, headers=other))
    assert not {"sheet", "resources", "combat", "energies"} & public.keys()
    denied = client.post(
        url + "/universal-actions",
        json={"kind": "unequip", "item_id": armor["id"], "request_key": "steal"},
        headers=other,
    )
    assert denied.status_code == 403
    assert ok(client.get(url, headers=player))["derived"] == before["derived"]
