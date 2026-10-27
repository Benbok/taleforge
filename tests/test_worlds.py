"""Герой и мир пакета: конструктор кампании мира предлагает только его происхождения и классы, герой профиля
собирается для выбранного мира, а при копировании в чужой мир называется, что заменить."""

from pathlib import Path

import pytest

from app.content.importer import import_pack
from tests.game import FIGHTER, import_base, ok, run
from tests.test_api import invite, make_campaign
from tests.test_profile import signup

ECHO = Path(__file__).resolve().parents[1] / "content" / "echo-leviathans"
SRD_RACES = {"origin.human", "origin.elf_high", "origin.dwarf_hill", "origin.tiefling", "origin.dragonborn"}
ECHO_FIGHTER = {**FIGHTER, "name": "Ржавый", "origin_id": "origin.tushevik", "ability_choice": ["str"]}


@pytest.fixture
def worlds(settings):
    import_base(settings)
    run(settings, lambda s: import_pack(s, ECHO))


def test_library_hero_built_for_world(client, worlds):
    h = signup(client, "Гимли")
    names = [w["name"] for w in ok(client.get("/api/me/worlds", headers=h))]
    assert names == ["Базовые правила D&D 5e", "Эхо Левиафанов"]
    opts = ok(client.get("/api/me/character-options?pack=echo-leviathans", headers=h))
    assert not {o["id"] for o in opts["origins"]} & SRD_RACES
    prev = ok(client.post("/api/me/character-preview", json={**ECHO_FIGHTER, "pack_id": "echo-leviathans"}, headers=h))
    assert prev["errors"] == []
    # мир героя проверяется: происхождение мира в базовых правилах не подходит
    prev = ok(client.post("/api/me/character-preview", json=ECHO_FIGHTER, headers=h))
    assert any("происхождение" in e for e in prev["errors"])
    hero = ok(client.post("/api/me/characters", json={**ECHO_FIGHTER, "pack_id": "echo-leviathans"}, headers=h), 201)
    assert hero["errors"] == [] and hero["world_name"] == "Эхо Левиафанов" and hero["origin_name"] == "Тушевик"
    assert ok(client.get("/api/me/characters", headers=h))[0]["pack_id"] == "echo-leviathans"
    r = client.post("/api/me/characters", json={**ECHO_FIGHTER, "pack_id": "nowhere"}, headers=h)
    assert r.status_code == 404 and "не загружен" in r.json()["detail"]


def test_copy_into_other_world_names_what_to_replace(client, admin, worlds):
    h = signup(client, "Леголас")
    elf = ok(client.post("/api/me/characters", json={**FIGHTER, "origin_id": "origin.elf_high"}, headers=h), 201)
    c = make_campaign(client, admin, players=1, pack_id="echo-leviathans", creation_rules={"review": "auto"})
    ok(client.post(f"/api/invites/{invite(client, admin, c['id'])['token']}/accept", headers=h))
    copy = ok(client.post(f"/api/campaigns/{c['id']}/characters/from-library/{elf['id']}", headers=h), 201)
    # класс в мире есть и переносится, эльфа — нет
    assert copy["sheet"]["class_id"] == "class.fighter" and "origin_id" not in copy["sheet"]
    assert copy["name"] == FIGHTER["name"]
    assert copy["public_bio"] == FIGHTER["public_bio"]
    assert copy["private_backstory"] == FIGHTER["private_backstory"]
    for key in ("abilities", "skills", "equipment_choices", "fighting_style"):
        assert copy["sheet"][key] == FIGHTER[key]
    want = "происхождение «Высший эльф» не из мира этой кампании: выберите происхождение этого мира"
    assert copy["errors"][0] == want
    assert not any(e.startswith("происхождение не выбрано") for e in copy["errors"])
    fixed = ok(
        client.put(
            f"/api/campaigns/{c['id']}/characters/{copy['id']}",
            json={"origin_id": "origin.tushevik", "ability_choice": ["str"]},
            headers=h,
        )
    )
    assert fixed["sheet"]["foreign"] == {}
    assert ok(client.get(f"/api/campaigns/{c['id']}/characters/{copy['id']}", headers=h))["errors"] == []
    sent = ok(client.post(f"/api/campaigns/{c['id']}/characters/{copy['id']}/submit", headers=h))
    assert sent["status"] == "approved" and sent["errors"] == []
    heroes = ok(client.get(f"/api/campaigns/{c['id']}/characters", headers=h))
    assert [(ch["id"], ch["name"]) for ch in heroes] == [(copy["id"], FIGHTER["name"])]
    assert ok(client.get(f"/api/me/characters/{elf['id']}", headers=h))["origin_id"] == "origin.elf_high"


def test_list_worlds_endpoint(client, worlds):
    res = ok(client.get("/api/worlds"))
    assert len(res) >= 2
    ids = [w["id"] for w in res]
    assert "echo-leviathans" in ids and "dnd5e-srd" in ids
    echo = next(w for w in res if w["id"] == "echo-leviathans")
    assert echo["name"] == "Эхо Левиафанов"
    assert "БИОПАНК" in echo["category"]
    assert len(echo["badges"]) >= 3


def test_get_world_detail_endpoint(client, worlds):
    echo = ok(client.get("/api/worlds/echo-leviathans"))
    assert echo["name"] == "Эхо Левиафанов"
    assert len(echo["lore_topics"]) > 0
    assert len(echo["factions"]) >= 5
    assert len(echo["locations"]) >= 5
    assert len(echo["origins"]) >= 5
    assert len(echo["classes"]) >= 10
    assert len(echo["scales"]) >= 3
    assert len(echo["clocks"]) >= 2
    assert len(echo["bestiary"]) >= 5

    # Проверка русской локализации происхождений Эхо Левиафанов
    tushevik = next(o for o in echo["origins"] if o["id"] == "origin.tushevik")
    assert "+2 к Телосложению" in tushevik["formatted_bonuses"]
    assert tushevik["speed_display"] == "30 футов (9 м)"
    assert tushevik["size_display"] == "Средний"
    assert any(f["name"] == "Привычка к газу" for f in tushevik["features"])

    srd = ok(client.get("/api/worlds/dnd5e-srd"))
    assert "SRD" in srd["name"]
    assert len(srd["classes"]) == 12
    assert len(srd["origins"]) == 9
    assert len(srd["bestiary"]) > 0

    # Проверка русской локализации рас D&D 5e SRD
    dwarf = next(o for o in srd["origins"] if o["id"] == "origin.dwarf_hill")
    assert dwarf["formatted_bonuses"] == "+2 к Телосложению, +1 к Мудрости"
    assert dwarf["speed_display"] == "25 футов (7.5 м)"
    assert dwarf["size_display"] == "Средний"
    assert len(dwarf["highlights"]) > 0
    # Черты должны быть русифицированы
    dwarf_feat_names = {f["name"] for f in dwarf["features"]}
    assert "Тёмное зрение" in dwarf_feat_names
    assert "Дварфийская стойкость" in dwarf_feat_names
    assert "Darkvision" not in dwarf_feat_names

    human = next(o for o in srd["origins"] if o["id"] == "origin.human")
    assert human["formatted_bonuses"] == "+1 ко всем характеристикам"

    half_elf = next(o for o in srd["origins"] if o["id"] == "origin.half_elf")
    assert "+2 к Харизме" in half_elf["formatted_bonuses"]
    assert "+1 к двум другим характеристикам на выбор" in half_elf["formatted_bonuses"]


def test_get_unknown_world_404(client, worlds):
    r = client.get("/api/worlds/nonexistent-world")
    assert r.status_code == 404
