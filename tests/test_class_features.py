# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Умения классов SRD (просьба Arty 2026-10-06: «есть ли способности для не магов героев»): мастер видит все умения
героя, сервер считает защиту без доспехов, боевой стиль, компетентность, ярость, скрытую атаку, сильный крит,
безрассудство, оглушающий удар, невероятное уклонение и увёртливость; друиду видны формы Дикого облика."""

import yaml

from app.core.world import Actor
from app.rules.base import HitPoints
from app.rules.dnd5e import features as cf
from app.rules.dnd5e.character import class_choice_errors, derive
from app.tools.spells import save_damage
from tests.game import BASE
from tests.test_tools import call, game, play  # noqa: F401 — фикстура

CLASSES = {c["id"]: c for c in yaml.safe_load((BASE / "data" / "classes.yaml").read_text("utf-8"))["items"]}
ARMOR = {a["id"]: a for a in yaml.safe_load((BASE / "data" / "armor.yaml").read_text("utf-8"))["items"]}
WEAPONS = {w["id"]: w for w in yaml.safe_load((BASE / "data" / "weapons.yaml").read_text("utf-8"))["items"]}
ABIL = {"str": 14, "dex": 16, "con": 14, "int": 10, "wis": 14, "cha": 8}


def _sheet(cls: str, level: int, **kw) -> dict:
    return {"class_id": cls, "level": level, "abilities": ABIL, **kw}


def _inv(*ids: str, equipped: bool = True) -> list:
    out = []
    for i in ids:
        rec = ARMOR.get(i) or WEAPONS[i]
        out.append((f"inv_{i}", {"id": i, **rec}, equipped, rec["name"]))
    return out


def test_feature_list_names_numbers_and_choices():
    rogue = cf.class_features(CLASSES["class.rogue"], 5, {"expertise": ["stealth"]})
    line = cf.summary(rogue)
    assert "Скрытая атака (3d6)" in line and "Хитрое действие" in line and "Невероятное уклонение" in line
    assert "Компетентность (stealth (не выбрано: 1))" in line
    assert not any("Spellcasting" in r["name"] or "Archetype" in r["name"] for r in rogue)
    barb = cf.summary(cf.class_features(CLASSES["class.barbarian"], 9))
    assert "Ярость (урон +3, 4 раза до долгого отдыха)" in barb
    assert "Дополнительная атака (2 удара за действие «Атака»)" in barb and barb.count("Дополнительная атака") == 1
    fighter = cf.class_features(CLASSES["class.fighter"], 1, {"fighting_style": "archery"})
    assert any(r["name"] == "Боевой стиль: Стрельба" for r in fighter)
    assert cf.fighting_style_options(CLASSES["class.paladin"], 1) == []
    assert "archery" not in cf.fighting_style_options(CLASSES["class.paladin"], 2)
    assert cf.expertise_count(CLASSES["class.rogue"], 6) == 4 and cf.expertise_count(CLASSES["class.bard"], 2) == 0


def test_wild_shape_forms_follow_druid_level():
    beasts = [
        ("creature.wolf", "Волк", {"creature_type": "beast", "cr": 0.25, "speed": {"walk": 40}}),
        ("creature.eagle", "Орёл", {"creature_type": "beast", "cr": 0, "speed": {"walk": 10, "fly": 60}}),
        ("creature.shark", "Акула", {"creature_type": "beast", "cr": 0.5, "speed": {"swim": 40}}),
        ("creature.bear", "Медведь", {"creature_type": "beast", "cr": 1, "speed": {"walk": 40}}),
        ("creature.goblin", "Гоблин", {"creature_type": "humanoid", "cr": 0.25, "speed": {"walk": 30}}),
    ]
    ids = lambda lvl: [f["id"] for f in cf.wild_shape_forms(lvl, beasts)]  # noqa: E731
    assert ids(2) == ["creature.wolf"]
    assert ids(4) == ["creature.wolf", "creature.shark"]
    assert ids(8) == ["creature.eagle", "creature.wolf", "creature.shark", "creature.bear"]


def test_sheet_counts_unarmored_defense_style_expertise_and_martial_arts():
    # варвар без доспеха: 10 + Лов 3 + Тел 2, со щитом +2; быстрое передвижение с 5-го уровня
    barb = derive(_sheet("class.barbarian", 5), CLASSES["class.barbarian"], None, _inv("item.shield"))
    assert barb.ac == 17 and barb.speed == 40
    # монах: 10 + Лов 3 + Мдр 2, движение без доспехов, безоружный удар костью боевых искусств и Ловкостью
    monk = derive(_sheet("class.monk", 5), CLASSES["class.monk"], None, _inv("item.quarterstaff"))
    assert monk.ac == 15 and monk.speed == 40
    unarmed = next(a for a in monk.attacks if a.key == "unarmed")
    assert unarmed.damage == "1d6+3" and unarmed.attack_bonus == 6 and unarmed.ability == "dex"
    staff = next(a for a in monk.attacks if a.key == "item.quarterstaff")
    assert staff.ability == "dex" and staff.damage == "1d6+3"
    # монах со щитом теряет защиту без доспехов
    assert derive(_sheet("class.monk", 1), CLASSES["class.monk"], None, _inv("item.shield")).ac == 15
    # стиль «Стрельба» +2 к дальним атакам, «Оборона» +1 к КД в доспехе
    archer = derive(
        _sheet("class.fighter", 1, fighting_style="archery"), CLASSES["class.fighter"], None, _inv("item.longbow")
    )
    assert next(a for a in archer.attacks if a.key == "item.longbow").attack_bonus == 3 + 2 + 2
    guard = derive(
        _sheet("class.fighter", 1, fighting_style="defense"), CLASSES["class.fighter"], None, _inv("item.chain_mail")
    )
    assert guard.ac == 17
    # компетентность плута: удвоенный бонус мастерства, только во владеемых навыках
    rogue = derive(
        _sheet("class.rogue", 1, skills=["stealth", "perception"], expertise=["stealth", "arcana"]),
        CLASSES["class.rogue"],
        None,
        [],
    )
    assert rogue.skills["stealth"] == 3 + 4 and rogue.skills["perception"] == 2 + 2 and rogue.skills["arcana"] == 0
    # мастер на все руки барда: половина бонуса мастерства к навыкам без владения
    bard = derive(_sheet("class.bard", 2, skills=["performance"]), CLASSES["class.bard"], None, [])
    assert bard.skills["arcana"] == 0 + 1 and bard.skills["performance"] == -1 + 2


def test_builder_requires_class_choices():
    rogue = CLASSES["class.rogue"]
    sheet = _sheet("class.rogue", 1, skills=["stealth", "perception"])
    assert class_choice_errors(sheet, rogue, None, 1) == ["компетентность: выберите 2 разных навыка"]
    sheet["expertise"] = ["stealth", "insight"]
    assert class_choice_errors(sheet, rogue, None, 1) == ["компетентность: только навыки, которыми герой владеет"]
    sheet["expertise"] = ["stealth", "perception"]
    assert class_choice_errors(sheet, rogue, None, 1) == []
    fighter = CLASSES["class.fighter"]
    assert class_choice_errors(_sheet("class.fighter", 1), fighter, None, 1) == [
        "боевой стиль: выберите один из стилей класса"
    ]
    assert class_choice_errors(_sheet("class.ranger", 1), CLASSES["class.ranger"], None, 1) == []


def test_evasion_halves_or_cancels_dex_save_damage():
    a = Actor("h", "Тень", "character", None, HitPoints(10, 10), 12, {}, {}, {}, {}, 2, [])
    rogue = Actor("h", "Тень", "character", None, HitPoints(10, 10), 12, {}, {}, {}, {}, 2, [],
                  features=frozenset({"rogue_evasion"}))  # fmt: skip
    assert save_damage(a, "dex", True, True, {}) == (True, True)
    assert save_damage(a, "dex", False, True, {}) == (True, False)
    assert save_damage(rogue, "dex", True, True, {}) == (False, True)
    assert save_damage(rogue, "dex", False, True, {}) == (True, True)
    assert save_damage(rogue, "con", True, True, {}) == (True, True)


def _become(ctx, hero, cls, level, **kw):
    ch = ctx.world.characters[hero]
    ch.sheet = {**ch.sheet, "class_id": cls, "level": level, **kw}
    ctx.world.invalidate(hero)


async def _ogre(ctx):
    sp = await call(ctx, "spawn_entity", {"creature_template_id": "creature.ogre", "name": "Огр"})
    assert sp["ok"], sp
    oid = sp["result"]["spawned"][0]["id"]
    assert (await call(ctx, "update_entity", {"entity_id": oid, "zone": "melee"}))["ok"]
    return oid


def test_rage_reckless_and_brutal_critical(game):
    settings, cid, hero = game

    async def fn(ctx):
        _become(ctx, hero, "class.barbarian", 9)
        ogre = await _ogre(ctx)
        rage = await call(ctx, "use_feature", {"character_id": hero, "feature": "rage"})
        act = ctx.world.actor(hero)
        swing = {"attacker_id": hero, "target_id": ogre, "attack": "item.longsword", "reckless": True}
        hit = await call(ctx, "resolve_attack", swing)
        spell = await call(ctx, "cast_spell", {"caster_id": hero, "spell_id": "spell.fire_bolt", "target_ids": [ogre]})
        return rage, act, hit, spell, ctx.world.actor(hero)

    # безрассудство: два d20 (20 и 3) → крит; урон 2d8 (4, 4) + Сил + ярость 3, сильный крит 1d8 (4) без удвоения
    rage, act, hit, spell, after = play(settings, cid, [20, 3, 4, 4, 4], fn)
    assert rage["ok"] and rage["result"]["rage_damage"] == 3 and "Ярость" in rage["result"]["effect"], rage
    assert {"slashing", "piercing", "bludgeoning"} <= act.resistances
    r = hit["result"]
    assert hit["ok"] and r["critical"] and r["mode"] == "advantage", hit
    assert any("Безрассудная атака" in x for x in r["reasons"])
    assert r["rage_bonus"] == 3 and r["brutal_critical"] == "1d8"
    assert r["damage"] == 4 + 4 + act.mods["str"] + 3 + 4
    assert not spell["ok"] and "в ярости" in spell["error"]
    assert any(rec.id == "effect.feature_reckless" for _, rec in after.effects)


def test_sneak_attack_and_uncanny_dodge(game):
    settings, cid, hero = game

    async def fn(ctx):
        _become(ctx, hero, "class.rogue", 5, expertise=["athletics", "perception"])
        ogre = await _ogre(ctx)
        await call(ctx, "give_item", {"character_id": hero, "item_template_id": "item.dagger", "reason": "тест"})
        dagger = next(x for x in ctx.world.actor(hero).attacks if x["key"] == "item.dagger")
        plain = await call(ctx, "resolve_attack", {"attacker_id": hero, "target_id": ogre, "attack": "item.dagger"})
        sneaky = await call(
            ctx,
            "resolve_attack",
            {
                "attacker_id": hero,
                "target_id": ogre,
                "attack": "item.dagger",
                "edge": "advantage",
                "edge_reason": "огр отвлёкся",
            },  # fmt: skip
        )
        before = ctx.world.actor(hero).hp.current
        club = await call(ctx, "resolve_attack", {"attacker_id": ogre, "target_id": hero, "attack": "greatclub"})
        return dagger, plain, sneaky, before, club

    # обычный удар: 15, урон 1d4 = 2; с преимуществом: 15 и 10, урон 2 + скрытая атака 3d6 (1, 2, 3);
    # огр: 18 по КД плута, 2d8 = 6 и 6 (+4) → 16, невероятное уклонение — 8
    dagger, plain, sneaky, before, club = play(settings, cid, [15, 2, 15, 10, 2, 1, 2, 3, 18, 6, 6], fn)
    assert dagger["properties"] and "finesse" in dagger["properties"]
    assert plain["ok"] and "sneak_attack" not in plain["result"], plain
    r = sneaky["result"]
    assert r["sneak_attack"] == "3d6" and r["damage"] == 2 + int(dagger["damage"].split("+")[1]) + 6, r
    c = club["result"]
    assert club["ok"] and c["hit"] and c["uncanny_dodge"] and c["damage"] == 8, club


def test_stunning_strike_and_second_wind(game):
    settings, cid, hero = game

    async def fn(ctx):
        _become(ctx, hero, "class.monk", 5)
        ogre = await _ogre(ctx)
        hit = await call(
            ctx,
            "resolve_attack",
            {"attacker_id": hero, "target_id": ogre, "attack": "unarmed", "stunning_strike": True},
        )
        stunned = [rec.id for _, rec in ctx.world.actor(ogre).effects]
        feats = (await call(ctx, "get_character", {"character_id": hero}))["result"]
        _become(ctx, hero, "class.fighter", 3)
        act = ctx.world.actor(hero)
        act.hp.current = 1
        act.save_hp()
        wind = await call(ctx, "use_feature", {"character_id": hero, "feature": "second_wind"})
        return hit, stunned, feats, wind

    # удар 15, урон 1d6 = 3; спасбросок Телосложения огра 2 (+3) против Сл 8 + 3 + Мдр; второе дыхание 1d10 = 6 + 3
    hit, stunned, feats, wind = play(settings, cid, [15, 3, 2, 6], fn)
    r = hit["result"]
    assert r["stunning_strike"]["success"] is False and r["stunning_strike"]["ki_left"] == 4, r
    assert "condition.stunned" in stunned
    ki = next(f for f in feats["features"] if f["key"] == "ki")
    assert ki["left"] == 4
    names = [f["name"] for f in feats["class_features"]]
    assert "Боевые искусства" in names and "Оглушающий удар" in names
    assert wind["ok"] and wind["result"]["healed"] == 9, wind


def test_master_sees_druid_forms_and_records_choices(game):
    settings, cid, hero = game

    async def fn(ctx):
        _become(ctx, hero, "class.druid", 2)
        druid = (await call(ctx, "get_character", {"character_id": hero}))["result"]
        table = ctx.world.scene_table()
        _become(ctx, hero, "class.rogue", 1)
        bad = await call(ctx, "set_class_choice", {"character_id": hero, "expertise": ["insight"]})
        good = await call(ctx, "set_class_choice", {"character_id": hero, "expertise": ["athletics"]})
        more = await call(ctx, "set_class_choice", {"character_id": hero, "expertise": ["perception", "stealth"]})
        style = await call(ctx, "set_class_choice", {"character_id": hero, "fighting_style": "archery"})
        return druid, table, bad, good, more, style

    druid, table, bad, good, more, style = play(settings, cid, [], fn)
    forms = {f["id"] for f in druid["wild_shape_forms"]}
    assert "creature.wolf" in forms and "creature.eagle" not in forms and "creature.brown_bear" not in forms
    assert "формы Дикого облика: " in table and "creature.wolf" in table and "умения класса: " in table
    assert not bad["ok"] and "владеет" in bad["error"]
    assert good["ok"] and good["result"]["expertise"] == ["athletics"], good
    assert not more["ok"] and "ещё 1" in more["error"]
    assert not style["ok"] and "боевого стиля" in style["error"]


def test_monk_flurry_and_ki_moves_in_combat(client, admin, settings):
    from tests.game import import_base, party
    from tests.test_map import _ok

    import_base(settings)
    c, _, hero = party(client, admin)
    cid, hid = c["id"], hero["id"]

    async def turn(ctx):
        _become(ctx, hid, "class.monk", 5)
        await _ok(ctx, "create_location", {"name": "Двор", "make_current": True})
        spawn = {"creature_template_id": "creature.ogre", "name": "Огр", "cell": [1, 0]}
        ogre = (await _ok(ctx, "spawn_entity", spawn))["spawned"][0]["id"]
        await _ok(ctx, "set_scene_mode", {"mode": "combat", "participants": [hid, ogre]})
        sc = ctx.world.scene
        sc.state = {**sc.state, "turn": [x["id"] for x in sc.turn_order].index(hid)}
        flurry = await call(ctx, "use_feature", {"character_id": hid, "feature": "flurry_of_blows"})
        strike = {"attacker_id": hid, "target_id": ogre, "attack": "unarmed", "as_bonus": True}
        one, two, three = [await call(ctx, "resolve_attack", strike) for _ in range(3)]
        patient = await call(ctx, "take_action", {"character_id": hid, "action": "dodge", "bonus": True})
        return flurry, one, two, three, patient

    flurry, one, two, three, patient = play(settings, cid, [10, 10], turn)
    assert flurry["ok"] and flurry["result"]["left"] == 4 and flurry["result"]["feature"] == "Шквал ударов", flurry
    assert one["ok"] and two["ok"], (one, two)
    assert not three["ok"] and "бонусное действие этого хода уже потрачено" in three["error"]
    assert not patient["ok"] and "бонусное действие этого хода уже потрачено" in patient["error"]


def test_every_srd_feature_has_russian_text_for_player():
    """Новичку (вопрос Arty 2026-10-06): у каждого умения SRD, которое видит игрок, есть русское имя, текст и метка."""
    for cid, cls in CLASSES.items():
        for f in cls.get("features") or []:
            if cf.SKIP.search(f["key"]) or f.get("parent"):
                continue
            assert f.get("name_ru") and f.get("text_ru"), (cid, f["key"])
            assert f.get("mode") in ("auto", "declare", "master"), (cid, f["key"])
            if f["mode"] == "declare":
                assert f.get("say"), (cid, f["key"])


def test_player_texts_modes_and_world_pack_fallback():
    rage = next(r for r in cf.class_features(CLASSES["class.barbarian"], 2) if r["key"] == "rage")
    assert rage["mode"] == "declare" and rage["say"] and rage["text_ru"] and rage["how"]
    ward = cf.class_features(CLASSES["class.fighter"], 1, {"fighting_style": "defense"})
    assert next(r for r in ward if r["key"] == "fighting_style_defense")["mode"] == "auto"
    pack = cf.player_texts({"description": "Чует ложь собеседника.", "action": "action"}, "Диагностика")
    assert pack == {"mode": "declare", "text_ru": "Чует ложь собеседника.", "say": "Диагностика"}
    assert cf.player_texts({"description": "Sees the truth."}, "X") == {"mode": "master"}


def test_player_sheet_shows_features_with_uses_left(game):
    from app.core.characters import full_view

    settings, cid, hero = game

    async def fn(ctx):
        _become(ctx, hero, "class.barbarian", 3)
        ch = ctx.world.characters[hero]
        ch.resources = {**(ch.resources or {}), "uses_spent": {"rage": 1}}
        barb = full_view(ch, ctx.world.catalog, [], [])
        _become(ctx, hero, "class.druid", 2)
        druid = full_view(ch, ctx.world.catalog, [], [])
        return barb, druid

    barb, druid = play(settings, cid, [], fn)
    rage = next(r for r in barb["class_features"] if r["key"] == "rage")
    assert rage["uses"] == {"left": 2, "max": 3, "per_ru": rage["uses"]["per_ru"], "unit": "раз"}
    assert "text" not in rage and rage["say"]
    shape = next(r for r in druid["class_features"] if r["key"].startswith("wild_shape"))
    assert shape["uses"]["max"] == 2 and any(f["id"] == "creature.wolf" for f in druid["wild_shape_forms"])
