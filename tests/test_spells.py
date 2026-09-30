"""Заклинания: заклинатель класса, выбор в конструкторе, ячейки, сотворение в бою и вне боя, концентрация, отдых."""

import pytest

from app.rules.dnd5e import spells as rules
from app.rules.dnd5e.spells import Choice
from tests.game import import_base, ok, party
from tests.test_tools import call, play

WIZARD = {
    "name": "Ильва",
    "class_id": "class.wizard",
    "origin_id": "origin.human",
    "ability_method": "standard_array",
    "abilities": {"str": 8, "dex": 14, "con": 13, "int": 15, "wis": 12, "cha": 10},
    "skills": ["arcana", "history"],
    "equipment_choices": [{"choice": 0, "option": 0}, {"choice": 1, "option": 0}, {"choice": 2, "option": 0}],
    "cantrips": ["spell.fire_bolt", "spell.light", "spell.ray_of_frost"],
    "spells": [
        "spell.magic_missile",
        "spell.shield",
        "spell.detect_magic",
        "spell.fog_cloud",
        "spell.mage_armor",
        "spell.burning_hands",
    ],
    "prepared": ["spell.magic_missile", "spell.shield", "spell.fog_cloud", "spell.mage_armor"],
    "public_bio": "Худая, в чернильных пятнах.",
    "private_backstory": "Сожгла чужую книгу.",
}

SPELLS = {
    "spell.fire_bolt": {"level": 0, "class_refs": ["class.wizard"], "name": "Огненный снаряд"},
    "spell.magic_missile": {"level": 1, "class_refs": ["class.wizard"], "name": "Волшебная стрела"},
    "spell.cure_wounds": {"level": 1, "class_refs": ["class.cleric"], "name": "Лечение ран"},
    "spell.fireball": {"level": 3, "class_refs": ["class.wizard"], "name": "Огненный шар"},
    "spell.wish": {"level": 9, "class_refs": ["class.wizard"], "name": "Исполнение желаний"},
}
WIZ_DATA = {
    "srd_ref": {"type": "class", "name": "Wizard"},
    "spellcasting": {"ability": "int"},
    "levels": [
        {"level": 1, "cantrips": 3, "slots": [2, 0, 0, 0, 0, 0, 0, 0, 0]},
        {"level": 5, "cantrips": 4, "slots": [4, 3, 2, 0, 0, 0, 0, 0, 0]},
    ],
}


def test_caster_numbers_and_choice_rules():
    c = rules.caster(WIZ_DATA, "class.wizard", 1, {"int": 16})
    assert (c.save_dc, c.attack, c.cantrips, c.known, c.prepared, c.top_level) == (13, 5, 3, 6, 4, 1)
    # список класса — до потолка мира; выучить сейчас можно только круги, на которые есть ячейки
    assert rules.class_list(c, SPELLS, forbidden={"spell.wish"}) == [
        "spell.fire_bolt",
        "spell.magic_missile",
        "spell.fireball",
    ]
    fb = Choice(["spell.fire_bolt"] * 0, ["spell.fireball"], [])
    assert any("3-го круга, вам пока доступен 1-й" in e for e in rules.validate(c, fb, SPELLS, exact=False))
    errs = rules.validate(c, Choice(["spell.fire_bolt"], ["spell.cure_wounds"], []), SPELLS)
    assert any("заговоры: выберите 3" in e for e in errs)
    assert any("«Лечение ран» нет в списке" in e for e in errs)
    # на 5-м уровне открыт 3-й круг, а 9-й мир закрывает для героев
    c5 = rules.caster(WIZ_DATA, "class.wizard", 5, {"int": 16})
    assert c5.top_level == 3
    # ячейки: сначала низший подходящий круг, потом выше, и понятная причина, когда всё потрачено
    res: dict = {}
    assert rules.pick_slot(c5, res, 1, None) == ("slot", 1)
    res = rules.spend(rules.spend(rules.spend(rules.spend(res, "slot", 1), "slot", 1), "slot", 1), "slot", 1)
    assert rules.pick_slot(c5, res, 1, None) == ("slot", 2)
    with pytest.raises(rules.SpellError, match="свободны: 2-й круг ×3"):
        rules.pick_slot(c5, res, 1, 1)
    assert rules.dice_at({1: "1d10", 5: "2d10", 11: "3d10"}, 7) == "2d10"


@pytest.fixture
def wizard_game(client, admin, settings):
    import_base(settings)
    c, heads, _ = party(client, admin, players=2)
    cid = c["id"]
    opts = ok(client.get(f"/api/campaigns/{cid}/character-options", headers=heads[1]))
    wiz = next(x for x in opts["classes"] if x["id"] == "class.wizard")
    assert wiz["spells"]["cantrips"] == 3 and wiz["spells"]["known"] == 6
    names = {s["id"]: s for s in wiz["spells"]["spells"]}
    assert names["spell.magic_missile"]["name"] == "Волшебная стрела" and names["spell.magic_missile"]["level"] == 1
    assert not any(s["level"] > 1 for s in wiz["spells"]["spells"])
    # живой лист называет, чего не хватает
    bad = ok(client.post(f"/api/campaigns/{cid}/character-preview", json={**WIZARD, "prepared": []}, headers=heads[1]))
    assert any("подготовленные: выберите 4" in e for e in bad["errors"]), bad["errors"]
    pv = ok(client.post(f"/api/campaigns/{cid}/character-preview", json=WIZARD, headers=heads[1]))
    assert pv["errors"] == [] and pv["derived"]["spellcasting"]["save_dc"] == 13
    ch = ok(client.post(f"/api/campaigns/{cid}/characters", json=WIZARD, headers=heads[1]), 201)
    res = ok(client.post(f"/api/campaigns/{cid}/characters/{ch['id']}/submit", headers=heads[1]))
    assert res["status"] == "approved", res
    return settings, cid, ch["id"], heads[1], client


def test_cast_in_combat_and_out(wizard_game):
    settings, cid, wiz, head, client = wizard_game
    sheet = ok(client.get(f"/api/campaigns/{cid}/characters/{wiz}", headers=head))
    book = sheet["spellbook"]
    assert book["slots_left"] == {"1": 2} and book["save_dc"] == 13 and book["attack"] == 5
    assert {s["id"] for s in book["spells"] if s["prepared"]} >= {"spell.fire_bolt", "spell.magic_missile"}

    async def fight(ctx):
        sp = await call(ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин"})
        gob = sp["result"]["spawned"][0]["id"]
        # «Волшебная стрела» бьёт без броска: 3d4+3 = 2+2+2+3 = 9 ≥ 7 хитов гоблина
        mm = await call(ctx, "cast_spell", {"caster_id": wiz, "spell_id": "spell.magic_missile", "target_ids": [gob]})
        unknown = await call(ctx, "cast_spell", {"caster_id": wiz, "spell_id": "spell.burning_hands"})
        return mm, unknown

    mm, unknown = play(settings, cid, [2, 2, 2], fight)
    assert mm["ok"], mm
    r = mm["result"]
    assert r["slot"] == {"kind": "slot", "level": 1} and r["outcomes"][0]["damage"] == 9 and r["outcomes"][0]["killed"]
    assert not unknown["ok"] and "не подготовлено" in unknown["error"]

    async def more(ctx):
        sp = await call(ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Второй"})
        gob = sp["result"]["spawned"][0]["id"]
        # «Огненный снаряд» — заговор: бросок атаки 15 + 5 против КД 15, урон 1d10 = 6
        fb = await call(ctx, "cast_spell", {"caster_id": wiz, "spell_id": "spell.fire_bolt", "target_ids": [gob]})
        sh = await call(ctx, "cast_spell", {"caster_id": wiz, "spell_id": "spell.shield"})
        empty = await call(
            ctx, "cast_spell", {"caster_id": wiz, "spell_id": "spell.magic_missile", "target_ids": [gob]}
        )
        return fb, sh, empty, ctx.world.actor(wiz).ac

    fb, sh, empty, ac = play(settings, cid, [15, 6], more)
    assert fb["ok"] and fb["result"]["outcomes"][0]["hit"] and fb["result"]["outcomes"][0]["damage"] == 6
    assert "slot" not in fb["result"]
    assert sh["ok"] and ac == 12 + 5  # Лов 14 без доспеха (12) и «Щит» +5
    assert not empty["ok"] and "потрачены" in empty["error"]

    async def rest(ctx):
        return await call(ctx, "rest", {"character_ids": [wiz], "kind": "long"})

    assert play(settings, cid, [], rest)["ok"]
    sheet = ok(client.get(f"/api/campaigns/{cid}/characters/{wiz}", headers=head))
    assert sheet["spellbook"]["slots_left"] == {"1": 2}


def test_ritual_concentration_and_combat_limits(wizard_game):
    settings, cid, wiz, head, client = wizard_game

    async def fn(ctx):
        t0 = ctx.world.scene.game_time
        rit = await call(ctx, "cast_spell", {"caster_id": wiz, "spell_id": "spell.detect_magic", "ritual": True})
        fog = await call(ctx, "cast_spell", {"caster_id": wiz, "spell_id": "spell.fog_cloud"})
        return rit, fog, ctx.world.scene.game_time - t0

    rit, fog, took = play(settings, cid, [], fn)
    assert rit["ok"] and rit["result"]["ritual"] and "slot" not in rit["result"], rit
    assert took == 606  # ритуал — на 10 минут дольше действия, ячейка не тратится
    assert fog["ok"] and fog["result"]["concentration_ended"]["spell"] == "Обнаружение магии"
    sheet = ok(client.get(f"/api/campaigns/{cid}/characters/{wiz}", headers=head))
    assert sheet["spellbook"]["concentration"]["name"] == "Туманное облако"
    assert sheet["spellbook"]["slots_left"] == {"1": 1}

    async def combat(ctx):
        sp = await call(ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин"})
        gob = sp["result"]["spawned"][0]["id"]
        heroes = list(ctx.world.characters)
        assert (await call(ctx, "set_scene_mode", {"mode": "combat", "participants": [*heroes, gob]}))["ok"]
        return await call(ctx, "cast_spell", {"caster_id": wiz, "spell_id": "spell.detect_magic", "ritual": True})

    r = play(settings, cid, [], combat)
    assert not r["ok"] and "в бою" in r["error"]


def test_spellbook_grows_in_game(wizard_game):
    settings, cid, wiz, head, client = wizard_game
    url = f"/api/campaigns/{cid}/characters/{wiz}/spells"
    # выученное не забывается
    r = client.put(url, json={"cantrips": ["spell.fire_bolt"]}, headers=head)
    assert r.status_code == 409 and "не забывается" in r.json()["detail"]
    # подготовленные меняют один раз до отдыха
    ok(
        client.put(
            url,
            json={"prepared": ["spell.magic_missile", "spell.shield", "spell.detect_magic", "spell.mage_armor"]},
            headers=head,
        )
    )
    r = client.put(
        url,
        json={"prepared": ["spell.magic_missile", "spell.shield", "spell.burning_hands", "spell.mage_armor"]},
        headers=head,
    )
    assert r.status_code == 409 and "после продолжительного отдыха" in r.json()["detail"]
    opts = ok(client.get(f"{url}/options", headers=head))
    assert any(s["id"] == "spell.sleep" for s in opts["spells"])


def test_spell_scrolls(wizard_game):
    settings, cid, wiz, head, client = wizard_game

    async def give(ctx, tpl):
        r = await call(ctx, "give_item", {"character_id": wiz, "item_template_id": tpl, "qty": 1, "reason": "тест"})
        return r["result"]["inventory_id"]

    async def fn(ctx):
        sp = await call(ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин"})
        gob = sp["result"]["spawned"][0]["id"]
        mm = await call(
            ctx,
            "use_item",
            {"character_id": wiz, "inventory_id": await give(ctx, "item.scroll_magic_missile"), "target_id": gob},
        )
        cure = await give(ctx, "item.scroll_cure_wounds")
        foreign = await call(ctx, "use_item", {"character_id": wiz, "inventory_id": cure})
        kept = any(i.id == cure for i in ctx.world.inventory[wiz])
        fb1 = await give(ctx, "item.scroll_fireball")
        fail = await call(ctx, "use_item", {"character_id": wiz, "inventory_id": fb1, "target_id": gob})
        gone = not any(i.id == fb1 for i in ctx.world.inventory[wiz])
        return mm, foreign, kept, fail, gone, ctx.world.characters[wiz].resources

    # «Волшебная стрела» со свитка: 3d4+3 = 9, ячейка не тратится; проверка «Огненного шара» 5 + 3 < 13
    mm, foreign, kept, fail, gone, res = play(settings, cid, [2, 2, 2, 5], fn)
    assert mm["ok"], mm
    assert mm["result"]["source"] == "Свиток: Волшебная стрела" and mm["result"]["outcomes"][0]["damage"] == 9
    assert not (res or {}).get("slots_used")
    assert not foreign["ok"] and "не из списка вашего класса" in foreign["error"] and kept
    assert fail["ok"] and fail["result"]["fizzled"] and fail["result"]["scroll_check"]["dc"] == 13 and gone

    async def win(ctx):
        sp = await call(ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Второй"})
        gob = sp["result"]["spawned"][0]["id"]
        inv = await give(ctx, "item.scroll_fireball")
        return await call(ctx, "use_item", {"character_id": wiz, "inventory_id": inv, "target_id": gob})

    r = play(settings, cid, [15, 1], win)
    assert r["ok"], r
    out = r["result"]
    assert out["scroll_check"]["success"] and out["outcomes"][0]["dc"] == 15 and not out["outcomes"][0]["success"]
