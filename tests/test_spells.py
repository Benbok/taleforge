"""Заклинания: заклинатель класса, выбор в конструкторе, ячейки, сотворение в бою и вне боя, концентрация, отдых."""

import pytest

from app.rules.dnd5e import spells as rules
from app.rules.dnd5e.spells import Choice
from app.tools import rest as rest_tools
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
        for e in ctx.world.entities.values():
            if e.kind == "creature":
                e.state = {**e.state, "fled": True}  # при врагах рядом не отдыхают
        r = await call(ctx, "rest", {"character_ids": [wiz], "kind": "long"})
        assert r["ok"], r
        for hid in ctx.world.characters:  # отдыхает вся группа: решают оба героя
            await rest_tools.ballot(ctx, r["result"]["vote_id"], hid, "sleep", None)

    play(settings, cid, [], rest)
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


def _spell(ctx, sid):
    from app.core.spells import spell_catalog

    return spell_catalog(ctx.world.catalog).spells[sid]


def _has(ctx, actor_id, cond):
    return any(r.id == f"condition.{cond}" for _, r in ctx.world.actor(actor_id).effects)


def test_repeat_save_auto_crit_and_magic_resistance(wizard_game):
    from app.tools.spells import resolve, turn_end_saves

    settings, cid, wiz, head, client = wizard_game
    nums = {"dc": 13, "attack_bonus": 5, "ability_mod": 3, "char_level": 3}

    async def fn(ctx):
        sp = await call(
            ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин", "zone": "melee"}
        )
        gob = sp["result"]["spawned"][0]["id"]
        hold = await resolve(ctx, ctx.world.actor(wiz), _spell(ctx, "spell.hold_person"), slot=2, targets=[gob], **nums)
        held = _has(ctx, gob, "paralyzed")
        # вплотную по парализованному: попадание — критическое, кости урона удваиваются
        grasp = await resolve(
            ctx, ctx.world.actor(wiz), _spell(ctx, "spell.shocking_grasp"), slot=0, targets=[gob], **nums
        )
        notes: list[str] = []
        await turn_end_saves(ctx, gob, notes)  # конец хода гоблина: повторный спасбросок
        return hold, held, grasp, notes, _has(ctx, gob, "paralyzed"), ctx.world.scene.state.get("spell_saves")

    # спасбросок 1 — паралич; атака с преимуществом 15/15, урон 2к8 → 1+1; повторный спасбросок 20 — свободен
    hold, held, grasp, notes, still, left = play(settings, cid, [1, 15, 15, 1, 1, 20], fn)
    assert not next(r for r in hold["outcomes"] if "save" in r)["success"] and held
    row = grasp["outcomes"][0]
    assert row["hit"] and row["critical"] and row["damage"] == 2, row
    assert not still and left == [] and "сбрасывает «Удержание личности»" in notes[0], notes

    async def archmage(ctx):
        sp = await call(
            ctx, "spawn_entity", {"creature_template_id": "creature.archmage", "name": "Архимаг", "attitude": "neutral"}
        )
        mage = sp["result"]["spawned"][0]["id"]
        return await resolve(
            ctx, ctx.world.actor(wiz), _spell(ctx, "spell.hold_person"), slot=2, targets=[mage], **nums
        )

    r = next(x for x in play(settings, cid, [1, 20], archmage)["outcomes"] if "save" in x)
    assert r["success"] and "преимущество: сопротивление магии" in r["reasons"], r


def test_area_must_fit_and_lingering_zone_ticks(wizard_game):
    from app.tools.registry import ToolError
    from app.tools.spells import resolve, zone_tick

    settings, cid, wiz, head, client = wizard_game
    nums = {"dc": 13, "attack_bonus": 5, "ability_mod": 3, "char_level": 5}

    async def spread(ctx):
        ids = []
        for name, cell in (("Левый", [2, 0]), ("Правый", [12, 0])):
            sp = await call(
                ctx,
                "spawn_entity",
                {"creature_template_id": "creature.goblin", "name": name, "cell": cell, "attitude": "neutral"},
            )
            ids.append(sp["result"]["spawned"][0]["id"])
        try:
            await resolve(ctx, ctx.world.actor(wiz), _spell(ctx, "spell.fireball"), slot=3, targets=ids, **nums)
        except ToolError as e:
            return str(e)
        return None

    err = play(settings, cid, [], spread)
    assert err and "в одну область" in err, err

    async def beam(ctx):
        sp = await call(ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин"})
        gob = sp["result"]["spawned"][0]["id"]
        cast = await resolve(ctx, ctx.world.actor(wiz), _spell(ctx, "spell.moonbeam"), slot=2, targets=[gob], **nums)
        hp0 = ctx.world.actor(gob).hp.current
        notes: list[str] = []
        await zone_tick(ctx, ctx.world.actor(gob), notes)  # начало хода гоблина в луче
        await zone_tick(ctx, ctx.world.actor(gob), notes)  # тот же ход — второй раз не бьёт
        return cast, hp0, ctx.world.actor(gob).hp.current, notes

    # спасбросок 1 — провал, урон 2к10 = 1 + 2
    cast, hp0, hp1, notes = play(settings, cid, [1, 1, 2], beam)
    assert "outcomes" not in cast and cast["zone"]["members"] == ["Гоблин"], cast  # при сотворении не бьёт
    assert hp0 - hp1 == 3 and len(notes) == 1 and "провал" in notes[0], (hp0, hp1, notes)


def test_hostile_spell_opener_waits_for_initiative(wizard_game):
    """A hostile spell is not cast before initiative and consumes a normal slot."""
    from app.agents.master.turn import _targets_hostile_with_spell
    from app.core import combat
    from tests.test_combat import _fight

    settings, cid, wizard, _, _ = wizard_game

    async def fn(ctx):
        goblin = await _fight(ctx, wizard, "creature.goblin", zone="melee", first="hero")
        args = {"caster_id": wizard, "spell_id": "spell.magic_missile", "target_ids": [goblin]}
        assert _targets_hostile_with_spell(ctx, args)
        assert not _targets_hostile_with_spell(ctx, {**args, "spell_id": "spell.shillelagh"})
        assert not [ev for ev in ctx.events if ev.tool == "cast_spell"]
        combat.queue_opening_spell(ctx, args)
        assert combat.state(ctx)["opening_spells"][wizard] == args
        notes = await combat.run_until_hero(ctx, "spell-opener")
        spells = [ev for ev in ctx.events if ev.tool == "cast_spell"]
        assert len(spells) == 1
        assert spells[0].payload["spell_id"] == "spell.magic_missile"
        assert not combat.state(ctx).get("opening_spells")
        return notes

    notes = play(settings, cid, [10, 10, 10, 2, 2, 2], fn)
    assert any("творит" in note for note in notes)


def test_rejected_opening_spell_preserves_caster_turn(wizard_game):
    """An invalid spell fails honestly and does not consume the turn."""
    from app.core import combat
    from tests.test_combat import _fight

    settings, cid, wizard, _, _ = wizard_game

    async def fn(ctx):
        goblin = await _fight(ctx, wizard, "creature.goblin", zone="melee", first="hero")
        combat.queue_opening_spell(ctx, {"caster_id": wizard, "spell_id": "spell.detect_magic", "target_ids": [goblin]})
        notes = await combat.run_until_hero(ctx, "invalid-spell")
        assert not combat.state(ctx).get("opening_spells")
        assert combat.current_id(ctx) == wizard
        assert combat.state(ctx)["deadline"] is not None
        assert not [ev for ev in ctx.events if ev.tool == "cast_spell"]
        return notes

    notes = play(settings, cid, [10, 10, 10], fn)
    assert any("заклинание не выполнено" in note for note in notes)


def test_move_cast_plan_executes_step_before_spell(wizard_game):
    """An opening spell follows a real approach and uses exactly one slot."""
    from app.core import combat
    from app.tools.action_plan import approach_cast
    from tests.test_combat import _fight

    settings, cid, wizard, _, _ = wizard_game

    async def fn(ctx):
        gob = await _fight(ctx, wizard, "creature.goblin", zone="near", first="hero")
        intent = {
            "character_id": wizard,
            "confidence": 0.95,
            "actions": [
                {"verb": "move", "target_id": gob, "zone": "melee"},
                {"verb": "cast", "spell_id": "spell.magic_missile", "target_id": gob},
            ],
        }
        plan = approach_cast(ctx, intent)
        assert plan is not None
        combat.queue_opening_plan(ctx, plan)
        await combat.run_until_hero(ctx, "move-cast")
        ev = [e for e in ctx.events if e.actor_id == wizard and e.tool in ("step", "cast_spell")]
        assert [e.tool for e in ev] == ["step", "cast_spell"]
        assert ev[0].payload["moved_ft"] > 0
        assert ev[1].payload["spell_id"] == "spell.magic_missile"
        assert not combat.state(ctx).get("opening_plans")
        return ctx.world.characters[wizard].resources

    resources = play(settings, cid, [1, 1, 1, 1, 1, 1], fn)
    assert resources["slots_used"]["1"] == 1


def test_move_cast_out_of_reach_does_not_consume_spell_slot(wizard_game):
    """Out-of-range path is not a spellcast and must preserve the caster turn."""
    from app.core import combat
    from app.tools.action_plan import approach_cast
    from tests.test_combat import _fight

    settings, cid, wizard, _, _ = wizard_game

    async def fn(ctx):
        gob = await _fight(ctx, wizard, "creature.goblin", zone="far", first="hero")
        intent = {
            "character_id": wizard,
            "confidence": 0.95,
            "actions": [
                {"verb": "move", "target_id": gob, "zone": "melee"},
                {"verb": "cast", "spell_id": "spell.magic_missile", "target_id": gob},
            ],
        }
        plan = approach_cast(ctx, intent)
        assert plan is not None
        combat.queue_opening_plan(ctx, plan)
        notes = await combat.run_until_hero(ctx, "blocked-cast")
        assert combat.current_id(ctx) == wizard
        assert combat.state(ctx)["deadline"] is not None
        assert not [e for e in ctx.events if e.tool == "cast_spell" and e.actor_id == wizard]
        assert not [e for e in ctx.events if e.tool == "step" and e.actor_id == wizard]
        assert not combat.state(ctx).get("opening_plans")
        return notes, ctx.world.characters[wizard].resources

    notes, resources = play(settings, cid, [], fn)
    assert any("сближение" in note or "подтверждения" in note for note in notes)
    assert not resources.get("slots_used")


def test_move_cast_parser_rejects_ambiguous_combinations(wizard_game):
    from app.tools.action_plan import approach_cast

    settings, cid, wizard, _, _ = wizard_game

    async def fn(ctx):
        ally = next(cid for cid in ctx.world.characters if cid != wizard)
        base = {
            "character_id": wizard,
            "confidence": 0.95,
            "actions": [
                {"verb": "move", "zone": "melee"},
                {"verb": "cast", "spell_id": "spell.magic_missile", "target_id": ally},
            ],
        }
        assert approach_cast(ctx, base) is not None
        self_target = [base["actions"][0], {**base["actions"][1], "target_id": wizard}]
        assert approach_cast(ctx, {**base, "actions": self_target}) is None
        assert approach_cast(ctx, {**base, "actions": list(reversed(base["actions"]))}) is None
        assert approach_cast(ctx, {**base, "confidence": 0.3}) is None
        assert (
            approach_cast(
                ctx, {**base, "actions": [base["actions"][0], {**base["actions"][1], "spell_id": "spell.unknown"}]}
            )
            is None
        )
        assert (
            approach_cast(ctx, {**base, "actions": [base["actions"][0], {**base["actions"][1], "target_id": None}]})
            is None
        )

    play(settings, cid, [], fn)
