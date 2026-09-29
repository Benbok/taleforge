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


def test_campaign_builder_offers_only_world_origins(client, admin, worlds):
    c = make_campaign(client, admin, players=1, pack_id="echo-leviathans")
    opts = ok(client.get(f"/api/campaigns/{c['id']}/character-options", headers=admin))
    origins = {o["id"] for o in opts["origins"]}
    assert "origin.tushevik" in origins and not origins & SRD_RACES
    classes = {x["id"]: x["name"] for x in opts["classes"]}
    assert classes["class.diagnost"] == "Диагност" and classes["class.cleric"] == "Жрец Церкви Исполинов"
    # кампания по базовым правилам по-прежнему видит расы SRD
    base = make_campaign(client, admin, players=1)
    opts = ok(client.get(f"/api/campaigns/{base['id']}/character-options", headers=admin))
    assert SRD_RACES <= {o["id"] for o in opts["origins"]}


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
    c = make_campaign(client, admin, players=1, pack_id="echo-leviathans")
    ok(client.post(f"/api/invites/{invite(client, admin, c['id'])['token']}/accept", headers=h))
    copy = ok(client.post(f"/api/campaigns/{c['id']}/characters/from-library/{elf['id']}", headers=h), 201)
    # класс в мире есть и переносится, эльфа — нет
    assert copy["sheet"]["class_id"] == "class.fighter" and "origin_id" not in copy["sheet"]
    assert copy["errors"][0] == "происхождение «Высший эльф» не из мира этой кампании: выберите происхождение этого мира"
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


def test_threshold_gives_second_race_and_caste(client, admin, worlds, settings):
    from app.db.models import Campaign
    from app.tools.registry import execute
    from app.tools.runtime import flush_outbox, open_context
    from tests.game import QueueDice
    from tests.test_api import register

    c = make_campaign(client, admin, players=1, pack_id="echo-leviathans", creation_rules={"review": "auto"})
    h = register(client, invite(client, admin, c["id"])["token"], "Арагорн")
    ch = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=ECHO_FIGHTER, headers=h), 201)
    assert ok(client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/submit", headers=h))["status"] == "approved"
    before = ok(client.get(f"/api/campaigns/{c['id']}/characters/{ch['id']}", headers=h))

    async def go(s):
        ctx = await open_context(s, await s.get(Campaign, c["id"]), QueueDice([]), turn_id="t_test", seat_id=None)
        found = await execute(ctx, "lookup_template", {"kind": "lineage", "query": "Сохранивший себя"})
        bad = await execute(
            ctx, "cross_threshold", {"character_id": ch["id"], "lineage_id": "lineage.kept_self", "caste": "deep"}
        )
        good = await execute(
            ctx,
            "cross_threshold",
            {"character_id": ch["id"], "lineage_id": "lineage.kept_self", "caste": "warrior", "variant": "kept_self"},
        )
        again = await execute(
            ctx, "cross_threshold", {"character_id": ch["id"], "lineage_id": "lineage.kept_heart", "caste": "voice"}
        )
        await flush_outbox(s, ctx)
        await s.commit()
        return found, bad, good, again

    found, bad, good, again = run(settings, go)
    kept_self = next(x for x in found["result"]["results"] if x["id"] == "lineage.kept_self")
    castes = [x["id"] for x in kept_self["castes"]]
    assert castes == ["herald", "warrior", "weaver"]
    assert not bad["ok"] and "нет касты deep" in bad["error"]
    assert good["ok"] and good["result"]["caste"] == "Воитель"
    assert not again["ok"] and "уже прошёл Порог" in again["error"]
    after = ok(client.get(f"/api/campaigns/{c['id']}/characters/{ch['id']}", headers=h))
    assert after["lineage"]["name"] == "Сохранивший себя" and after["lineage"]["caste"] == "Воитель"
    assert "Панцирь воителя" in after["lineage"]["features"]
    # класс и происхождение на месте; «Панцирь воителя» +1 к КД, Атлетикой воин уже владел
    assert after["sheet"]["class_id"] == "class.fighter" and after["sheet"]["origin_id"] == "origin.tushevik"
    assert after["derived"]["ac"] >= before["derived"]["ac"] + 1
    assert after["derived"]["skills"]["athletics"] == before["derived"]["skills"]["athletics"]
