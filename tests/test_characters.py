import pytest

from tests.game import FIGHTER, import_base, ok, party
from tests.test_api import invite, make_campaign, register


@pytest.fixture
def base(settings):
    import_base(settings)


def test_options_and_draft_validation(client, admin, base):
    c = make_campaign(client, admin, players=2)
    inv = invite(client, admin, c["id"])
    p1 = register(client, inv["token"], "Арагорн")
    opts = ok(client.get(f"/api/campaigns/{c['id']}/character-options", headers=p1))
    assert len(opts["classes"]) == 12 and len(opts["origins"]) == 9
    assert opts["ability_methods"] == ["standard_array", "point_buy", "roll"]

    bad = {**FIGHTER, "abilities": {**FIGHTER["abilities"], "str": 18}}
    ch = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=bad, headers=p1), 201)
    assert ch["status"] == "draft" and any("стандартный набор" in e for e in ch["errors"])
    res = ok(client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/submit", headers=p1))
    assert res["status"] == "draft" and res["errors"]

    # у места один активный персонаж
    r = client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=p1)
    assert r.status_code == 409

    fixed = ok(client.put(f"/api/campaigns/{c['id']}/characters/{ch['id']}", json=FIGHTER, headers=p1))
    assert fixed["errors"] == []


def test_roll_abilities_once(client, admin, base):
    c = make_campaign(client, admin, players=1)
    p1 = register(client, invite(client, admin, c["id"])["token"], "Арагорн")
    ch = ok(client.post(f"/api/campaigns/{c['id']}/characters", json={"name": "Кубик"}, headers=p1), 201)
    rolls = ok(client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/roll-abilities", headers=p1))["rolls"]
    assert len(rolls) == 6 and all(3 <= v <= 18 for v in rolls)
    r = client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/roll-abilities", headers=p1)
    assert r.status_code == 409
    # значения должны совпадать с выпавшими
    wrong = {**FIGHTER, "ability_method": "roll", "abilities": {a: 10 for a in FIGHTER["abilities"]}}
    view = ok(client.put(f"/api/campaigns/{c['id']}/characters/{ch['id']}", json=wrong, headers=p1))
    if sorted(rolls) != [10] * 6:
        assert any("выпавшими" in e for e in view["errors"])
    right = {**wrong, "abilities": dict(zip(FIGHTER["abilities"], rolls, strict=True))}
    view = ok(client.put(f"/api/campaigns/{c['id']}/characters/{ch['id']}", json=right, headers=p1))
    assert view["errors"] == []


def test_auto_review_gives_equipment_and_hp(client, admin, base):
    c, (p1,), ch = party(client, admin)
    view = ok(client.get(f"/api/campaigns/{c['id']}/characters/{ch['id']}", headers=p1))
    assert view["status"] == "approved"
    # воин d10 + мод. Телосложения (14 + 1 человеку = 15 → +2)
    assert view["resources"]["hp"] == view["resources"]["hp_max"] == 12
    inv = {i["item"]: i for i in view["inventory"]}
    assert inv["item.chain_mail"]["equipped"] and inv["item.shield"]["equipped"]
    assert inv["item.longsword"]["qty"] == 1 and inv["item.handaxe"]["qty"] == 2
    assert view["derived"]["ac"] == 18  # кольчуга 16 + щит 2
    assert any(a["key"] for a in view["derived"]["attacks"])


def test_master_review_and_visibility(client, admin, base):
    c = make_campaign(client, admin, players=2, master={"type": "owner"})
    inv = invite(client, admin, c["id"])
    p1, p2 = register(client, inv["token"], "Арагорн"), register(client, inv["token"], "Гимли")
    ch = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=p1), 201)
    assert ok(client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/submit", headers=p1))["status"] == (
        "submitted"
    )
    # чужой черновик на проверке не виден другому игроку
    assert ok(client.get(f"/api/campaigns/{c['id']}/characters", headers=p2)) == []
    r = client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/review", json={"approve": True}, headers=p2)
    assert r.status_code == 403
    r = client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/review", json={"approve": False}, headers=admin)
    assert r.status_code == 409  # возврат без комментария
    back = ok(
        client.post(
            f"/api/campaigns/{c['id']}/characters/{ch['id']}/review",
            json={"approve": False, "comment": "Добавь, откуда шрам"},
            headers=admin,
        )
    )
    assert back["status"] == "draft" and back["review_comment"] == "Добавь, откуда шрам"
    ok(client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/submit", headers=p1))
    done = ok(
        client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/review", json={"approve": True}, headers=admin)
    )
    assert done["status"] == "approved"

    public = ok(client.get(f"/api/campaigns/{c['id']}/characters/{ch['id']}", headers=p2))
    assert "private_backstory" not in public and "sheet" not in public
    assert public["public_bio"] == FIGHTER["public_bio"]
    mine = ok(client.get(f"/api/campaigns/{c['id']}/characters/{ch['id']}", headers=p1))
    assert mine["private_backstory"] == FIGHTER["private_backstory"]
    # в игре механику не поменять, имя и историю — можно
    upd = ok(
        client.put(
            f"/api/campaigns/{c['id']}/characters/{ch['id']}",
            json={"name": "Бран Шрам", "class_id": "class.wizard"},
            headers=p1,
        )
    )
    assert upd["name"] == "Бран Шрам" and upd["sheet"]["class_id"] == "class.fighter"
