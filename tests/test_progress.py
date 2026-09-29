"""Инвентарь и рост героев: подобранные предметы остаются у героя, опыт делится поровну и поднимает уровень."""

import pytest
from sqlalchemy import select

from app.agents.intent import VERBS
from app.db.models import Campaign, Character, Entity, Event, InventoryItem, Message
from app.tools.registry import execute
from app.tools.runtime import flush_outbox, open_context, scene_public
from tests.game import FIGHTER, QueueDice, import_base, ok, party, run


def two_heroes(client, admin, settings, **kw):
    import_base(settings)
    c, heads, ch = party(client, admin, players=2, difficulty="deadly", **kw)
    body = {**FIGHTER, "name": "Ира"}
    ch2 = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=body, headers=heads[1]), 201)
    res = ok(client.post(f"/api/campaigns/{c['id']}/characters/{ch2['id']}/submit", headers=heads[1]))
    assert res["status"] == "approved", res
    return c["id"], ch["id"], ch2["id"], heads


def play(settings, cid, dice, fn):
    async def go(s):
        c = await s.get(Campaign, cid)
        ctx = await open_context(s, c, QueueDice(dice), turn_id="t_test", seat_id=None)
        out = await fn(ctx)
        await flush_outbox(s, ctx)
        await s.commit()
        return out

    return run(settings, go)


def call(ctx, name, args):
    return execute(ctx, name, args)


async def kill(ctx, hero, template="creature.goblin", name="Гоблин"):
    sp = await call(ctx, "spawn_entity", {"creature_template_id": template, "name": name, "zone": "melee"})
    assert sp["ok"], sp
    en = sp["result"]["spawned"][0]["id"]
    for _ in range(4):
        r = await call(ctx, "resolve_attack", {"attacker_id": hero, "target_id": en, "attack": "item.longsword"})
        assert r["ok"], r
        if r["result"].get("killed"):
            return en, r
    raise AssertionError("враг не пал")


def sheets(settings, *ids):
    async def go(s):
        return [(await s.get(Character, i)).sheet for i in ids]

    return run(settings, go)


def system_lines(settings):
    async def go(s):
        return [m.content for m in (await s.scalars(select(Message).where(Message.kind == "system"))).all()]

    return run(settings, go)


# --- предметы ---


def test_picked_up_item_stays_in_inventory(client, admin, settings):
    cid, hero, other, _ = two_heroes(client, admin, settings)

    async def place(ctx):
        r = await call(
            ctx,
            "place_item",
            {"item_template_id": "item.potion_of_healing", "qty": 3, "reason": "в сундуке", "zone": "near"},
        )
        assert r["ok"], r
        public = scene_public(ctx.world)
        return r["result"]["entity_id"], public, ctx.world.scene_table()

    loot, public, table = play(settings, cid, [], place)
    card = next(e for e in public["entities"] if e["id"] == loot)
    assert card["item"] and card["qty"] == 3
    assert "можно подобрать" in table

    async def take(ctx):
        part = await call(ctx, "pick_up_item", {"character_id": hero, "entity_id": loot, "qty": 1})
        too_many = await call(ctx, "pick_up_item", {"character_id": hero, "entity_id": loot, "qty": 5})
        rest = await call(ctx, "pick_up_item", {"character_id": hero, "entity_id": loot})
        return part, too_many, rest

    part, too_many, rest = play(settings, cid, [], take)
    assert part["ok"] and part["result"]["left"] == 2, part
    assert not too_many["ok"] and "только 2" in too_many["error"]
    assert rest["ok"] and rest["result"]["left"] == 0

    # новая сессия БД: предмет остался в инвентаре героя, одной стопкой, а из сцены исчез
    async def check(s):
        inv = (await s.scalars(select(InventoryItem).where(InventoryItem.character_id == hero))).all()
        gone = await s.get(Entity, loot)
        return [(i.item_template_id, i.qty) for i in inv], gone

    inv, gone = run(settings, check)
    assert ("item.potion_of_healing", 3) in inv and gone is None
    assert any("Бран подбирает «Зелье лечения»" in x for x in system_lines(settings))

    async def share(ctx):
        potion = next(i for i in ctx.world.inventory[hero] if i.item_template_id == "item.potion_of_healing")
        given = await call(
            ctx, "pass_item", {"character_id": hero, "to_character_id": other, "inventory_id": potion.id, "qty": 1}
        )
        dropped = await call(ctx, "drop_item", {"character_id": hero, "inventory_id": potion.id, "qty": 1})
        again = await call(ctx, "pick_up_item", {"character_id": other, "entity_id": dropped["result"]["entity_id"]})
        return given, dropped, again

    given, dropped, again = play(settings, cid, [], share)
    assert given["ok"] and dropped["ok"] and again["ok"], (given, dropped, again)

    async def counts(s):
        q = select(InventoryItem).where(InventoryItem.item_template_id == "item.potion_of_healing")
        rows = (await s.scalars(q)).all()
        return {r.character_id: r.qty for r in rows}

    assert run(settings, counts) == {hero: 1, other: 2}


def test_only_items_can_be_picked_up(client, admin, settings):
    cid, hero, _, _ = two_heroes(client, admin, settings)

    async def fn(ctx):
        sp = await call(ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин"})
        gob = sp["result"]["spawned"][0]["id"]
        return await call(ctx, "pick_up_item", {"character_id": hero, "entity_id": gob})

    r = play(settings, cid, [], fn)
    assert not r["ok"] and "entity_id" in r["error"]


# --- опыт ---


def test_kill_gives_xp_split_equally(client, admin, settings):
    cid, hero, other, _ = two_heroes(client, admin, settings)
    _, hit = play(settings, cid, [15, 8], lambda ctx: kill(ctx, hero))
    xp = hit["result"]["xp"]
    assert xp["total"] == 50 and xp["each"] == 25, xp
    assert [s["xp"] for s in sheets(settings, hero, other)] == [25, 25]
    assert any("Опыт отряду: +50" in x and "по 25 каждому" in x for x in system_lines(settings))

    # мёртвый враг приносит опыт один раз
    async def again(ctx):
        return await call(ctx, "advance_time", {"amount": 1, "unit": "minute", "reason": "передышка"})

    assert "xp" not in play(settings, cid, [], again)["result"]
    assert [s["xp"] for s in sheets(settings, hero, other)] == [25, 25]


def test_odd_xp_carries_over(client, admin, settings):
    cid, hero, other, _ = two_heroes(client, admin, settings)
    _, hit = play(settings, cid, [15, 8], lambda ctx: kill(ctx, hero, "creature.kobold", "Кобольд"))
    xp = hit["result"]["xp"]
    assert xp["total"] == 25 and xp["each"] == 12 and xp["carried"] == 1, xp
    _, hit = play(settings, cid, [15, 8], lambda ctx: kill(ctx, hero, "creature.kobold", "Кобольд"))
    assert hit["result"]["xp"]["each"] == 13  # 25 + остаток 1
    assert [s["xp"] for s in sheets(settings, hero, other)] == [25, 25]


def test_quest_levels_up_the_party(client, admin, settings):
    cid, hero, other, _ = two_heroes(client, admin, settings)

    async def fn(ctx):
        before = ctx.world.actor(hero).hp.maximum
        quest = await call(ctx, "award_xp", {"kind": "quest", "difficulty": "deadly", "reason": "спасли деревню"})
        task = await call(ctx, "award_xp", {"kind": "task", "difficulty": "deadly", "reason": "нашли пропавшего"})
        return before, quest, task, ctx.world.actor(hero).hp.maximum

    before, quest, task, after = play(settings, cid, [], fn)
    # квест: порог «смертельной» 1 уровня (100) на героя ×2 = 400 на двоих, по 200; задача — ещё по 100
    assert quest["ok"] and quest["result"]["each"] == 200, quest
    assert task["ok"] and task["result"]["each"] == 100
    ups = task["result"]["level_up"]
    assert {x["character"] for x in ups} == {"Бран", "Ира"} and all(x["level"] == 2 for x in ups)
    assert after > before
    a, b = sheets(settings, hero, other)
    assert a["level"] == b["level"] == 2 and a["xp"] == b["xp"] == 300
    assert any("достигает 2 уровня" in x for x in system_lines(settings))

    async def events(s):
        return [e.tool for e in (await s.scalars(select(Event).where(Event.tool == "level_up"))).all()]

    assert len(run(settings, events)) == 2


def test_fallen_hero_gets_no_xp(client, admin, settings):
    cid, hero, other, _ = two_heroes(client, admin, settings)

    async def bury(s):
        ch = await s.get(Character, other)
        ch.status = "dead"
        ch.resources = {**ch.resources, "dead": True}
        await s.commit()

    run(settings, bury)
    _, hit = play(settings, cid, [15, 8], lambda ctx: kill(ctx, hero))
    assert hit["result"]["xp"]["each"] == 50
    a, b = sheets(settings, hero, other)
    assert a["xp"] == 50 and b.get("xp") is None


def test_defeat_without_kill(client, admin, settings):
    cid, hero, _, _ = two_heroes(client, admin, settings)

    async def fn(ctx):
        sp = await call(ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин"})
        gob = sp["result"]["spawned"][0]["id"]
        assert (await call(ctx, "update_entity", {"entity_id": gob, "fled": True}))["ok"]
        first = await call(ctx, "award_xp", {"kind": "defeat", "entity_ids": [gob], "reason": "гоблин бежал"})
        twice = await call(ctx, "award_xp", {"kind": "defeat", "entity_ids": [gob], "reason": "ещё раз"})
        return first, twice

    first, twice = play(settings, cid, [], fn)
    assert first["ok"] and first["result"]["each"] == 25, first
    assert not twice["ok"] and "уже выдан" in twice["error"]


def test_milestone_campaign_has_no_xp(client, admin, settings):
    import_base(settings)
    c, _, ch = party(client, admin, leveling="milestone", difficulty="deadly")
    cid, hero = c["id"], ch["id"]
    assert c["settings"]["leveling"] == "milestone"
    _, hit = play(settings, cid, [15, 8], lambda ctx: kill(ctx, hero))
    assert "xp" not in hit["result"]

    async def fn(ctx):
        award = await call(ctx, "award_xp", {"kind": "task", "reason": "поручение"})
        level = await call(ctx, "grant_level", {"character_ids": [hero], "reason": "веха"})
        return award, level

    award, level = play(settings, cid, [], fn)
    assert not award["ok"] and "по вехам" in award["error"]
    assert level["ok"] and level["result"]["levels"][0]["level"] == 2
    assert sheets(settings, hero)[0].get("xp") is None


def test_leveling_setting_and_sheet_progress(client, admin, settings):
    import_base(settings)
    c, heads, ch = party(client, admin)
    assert c["settings"]["leveling"] == "xp"
    r = client.patch(f"/api/campaigns/{c['id']}", json={"leveling": "milestone"}, headers=admin)
    assert ok(r)["settings"]["leveling"] == "milestone"
    bad = client.patch(f"/api/campaigns/{c['id']}", json={"leveling": "gold"}, headers=admin)
    assert bad.status_code == 422
    sheet = ok(client.get(f"/api/campaigns/{c['id']}/characters/{ch['id']}", headers=heads[0]))
    assert sheet["progress"] == {"xp": 0, "level_xp": 0, "next_xp": 300}


@pytest.mark.parametrize("verb", ["pick_up", "drop", "give"])
def test_parser_knows_item_verbs(verb):
    assert verb in VERBS


def test_keep_anything_found_in_the_world(client, admin, settings):
    cid, hero, _, _ = two_heroes(client, admin, settings)

    async def fn(ctx):
        sp = await call(
            ctx,
            "spawn_entity",
            {"creature_template_id": "creature.commoner", "name": "Прохожий", "attitude": "neutral"},
        )
        npc = sp["result"]["spawned"][0]["id"]
        rebar = await call(
            ctx,
            "keep_found_item",
            {
                "character_id": hero,
                "name": "Арматура",
                "kind": "improvised_weapon",
                "how": "pried",
                "reason": "вытащил из развалившейся стены",
            },
        )
        hat = await call(
            ctx,
            "keep_found_item",
            {
                "character_id": hero,
                "name": "Шляпа прохожего",
                "kind": "object",
                "from_id": npc,
                "how": "stolen",
                "reason": "стянул незаметно",
            },
        )
        dagger = await call(
            ctx,
            "keep_found_item",
            {
                "character_id": hero,
                "name": "Кинжал",
                "kind": "template",
                "item_template_id": "item.dagger",
                "how": "stolen",
                "reason": "срезал с пояса",
            },
        )
        no_tpl = await call(
            ctx,
            "keep_found_item",
            {"character_id": hero, "name": "Меч", "kind": "template", "how": "found", "reason": "x"},
        )
        use = await call(ctx, "use_item", {"character_id": hero, "inventory_id": hat["result"]["inventory_id"]})
        drop = await call(ctx, "drop_item", {"character_id": hero, "inventory_id": hat["result"]["inventory_id"]})
        back = await call(ctx, "pick_up_item", {"character_id": hero, "entity_id": drop["result"]["entity_id"]})
        attacks = [x["name"] for x in ctx.world.actor(hero).attacks]
        return rebar, hat, dagger, no_tpl, use, back, attacks

    rebar, hat, dagger, no_tpl, use, back, attacks = play(settings, cid, [], fn)
    assert rebar["ok"] and hat["ok"] and dagger["ok"], (rebar, hat, dagger)
    assert hat["result"]["from"] == "Прохожий"
    assert not no_tpl["ok"] and "item_template_id" in no_tpl["error"]
    assert not use["ok"] and "без механики" in use["error"]
    assert back["ok"], back
    assert "Арматура" in attacks  # импровизированное оружие сразу годится для атаки

    async def names(s):
        rows = (await s.scalars(select(InventoryItem).where(InventoryItem.character_id == hero))).all()
        return {r.display_name for r in rows}

    assert {"Арматура", "Шляпа прохожего", "Кинжал"} <= run(settings, names)
    assert any("Бран крадёт «Шляпа прохожего»" in x for x in system_lines(settings))
