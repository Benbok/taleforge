# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Отдых отряда и перезарядка по SRD (просьба Arty 2026-10-04): ячейки тратятся при любом исходе заклинания,
отдыхает только вся группа по голосованию, стража не отдыхает, засада в ненадёжном месте, умения с перезарядкой."""

import pytest

from app.rules.dnd5e import rest as rules
from app.tools import rest as rest_tools
from tests.game import ok
from tests.test_master import admin_g, dice, game_client, llm  # noqa: F401 — фикстуры
from tests.test_spells import WIZARD
from tests.test_spells import wizard_game as wizard_game  # noqa: F401 — фикстура
from tests.test_tools import call, play

FIGHTER_DATA = {
    "levels": [
        {"level": 1, "features": ["fighting_style", "second_wind"]},
        {"level": 2, "features": ["action_surge_1_use"], "class_specific": {"action_surges": 1}},
    ]
}
BARBARIAN_DATA = {"levels": [{"level": 1, "features": ["rage"], "class_specific": {"rage_count": 2}}]}


def test_pools_restore_and_arcane_recovery():
    pools = {p.key: p for p in rules.pools(FIGHTER_DATA, 2, 2, {"cha": 0})}
    assert pools["second_wind"].max == 1 and pools["second_wind"].per == rules.SHORT
    assert pools["action_surge"].max == 1
    rage = rules.pools(BARBARIAN_DATA, 1, 2, {})[0]
    assert (rage.key, rage.max, rage.per) == ("rage", 2, rules.LONG)
    spent = rules.use(rage, rules.use(rage, {}))
    with pytest.raises(rules.RestError, match="Вернётся после продолжительного отдыха"):
        rules.use(rage, spent)
    # короткий отдых возвращает только «до короткого отдыха», продолжительный — всё
    both = {"rage": 2, "second_wind": 1}
    assert rules.restore(both, [rage, pools["second_wind"]], "short") == {"rage": 2}
    assert rules.restore(both, [rage, pools["second_wind"]], "long") == {}
    # волшебник 5-го уровня: до 3 кругов, старшие ячейки первыми
    used, back = rules.arcane_recovery([4, 3, 2], {"1": 2, "2": 1, "3": 1}, 5)
    assert back == [3] and used == {"1": 2, "2": 1}
    used, back = rules.arcane_recovery([4, 3], {"1": 2, "2": 1}, 5)
    assert back == [2, 1] and used == {"1": 1}
    # пакет мира: умение с uses
    spot = {"key": "weak_spot", "name": "Слабое место", "uses": {"count": "int_mod", "per": "long_rest"}}
    data = {"levels": [{"level": 1, "features": ["weak_spot"]}], "features": [spot]}
    assert rules.pools(data, 1, 2, {"int": 3})[0].max == 3


def test_place_safety():
    assert rules.place_safety(None, {"settlement", "social"}, None) == rules.SAFE
    assert rules.place_safety(None, {"wild"}, None) == rules.RISKY
    assert rules.place_safety(None, {"underground", "sacred"}, None) == rules.RISKY
    assert rules.place_safety(None, {"underground", "danger"}, None) == rules.DANGEROUS
    assert rules.place_safety(None, {"settlement"}, {"every_hours": 4, "on_d6": [1, 2]}) == rules.DANGEROUS
    assert rules.place_safety("safe", {"danger"}, None) == rules.SAFE
    assert rules.ambush_rolls(rules.SAFE, 8, None) == (0, set())
    assert rules.ambush_rolls(rules.RISKY, 8, None) == (2, {1})
    assert rules.ambush_rolls(rules.DANGEROUS, 1, None) == (1, {1, 2})


@pytest.fixture
def battle_wizard(client, admin, settings):
    """Волшебник с «Огненными ладонями» среди подготовленных и воин."""
    from tests.game import import_base, party

    import_base(settings)
    c, heads, fighter = party(client, admin, players=2)
    cid = c["id"]
    hero = {**WIZARD, "prepared": ["spell.magic_missile", "spell.shield", "spell.burning_hands", "spell.mage_armor"]}
    ch = ok(client.post(f"/api/campaigns/{cid}/characters", json=hero, headers=heads[1]), 201)
    ok(client.post(f"/api/campaigns/{cid}/characters/{ch['id']}/submit", headers=heads[1]))
    return settings, cid, ch["id"], fighter["id"], heads[1], client


def test_slots_spent_whatever_the_outcome(battle_wizard):
    settings, cid, wiz, fighter, head, client = battle_wizard

    async def fn(ctx):
        sp = await call(
            ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин", "zone": "melee"}
        )
        gob = sp["result"]["spawned"][0]["id"]
        # заговор мимо (натуральная 1): ячейка не тратится
        fb = await call(ctx, "cast_spell", {"caster_id": wiz, "spell_id": "spell.fire_bolt", "target_ids": [gob]})
        # вне боя, гоблин спасся (20 на d20): ячейка всё равно потрачена
        out = await call(ctx, "cast_spell", {"caster_id": wiz, "spell_id": "spell.burning_hands", "target_ids": [gob]})
        heroes = list(ctx.world.characters)
        assert (await call(ctx, "set_scene_mode", {"mode": "combat", "participants": [*heroes, gob]}))["ok"]
        # в бою спасся снова: вторая ячейка тоже ушла
        inb = await call(ctx, "cast_spell", {"caster_id": wiz, "spell_id": "spell.burning_hands", "target_ids": [gob]})
        empty = await call(
            ctx, "cast_spell", {"caster_id": wiz, "spell_id": "spell.magic_missile", "target_ids": [gob]}
        )
        return fb, out, inb, empty

    # 2d20 атаки (помеха вплотную); d20 спасброска и 3d6 урона; инициатива трёх участников; снова спасбросок и урон
    fb, out, inb, empty = play(settings, cid, [1, 1, 20, 2, 2, 2, 10, 10, 10, 20, 2, 2, 2], fn)
    assert fb["ok"] and not fb["result"]["outcomes"][0]["hit"] and "slot" not in fb["result"]
    assert out["ok"] and out["result"]["outcomes"][0]["success"] and out["result"]["slot"]["level"] == 1, out
    assert inb["ok"] and inb["result"]["slot"]["level"] == 1, inb
    assert not empty["ok"] and "потрачены" in empty["error"]
    sheet = ok(client.get(f"/api/campaigns/{cid}/characters/{wiz}", headers=head))
    assert sheet["spellbook"]["slots_left"] == {"1": 0}


def _tired(ctx, *ids):
    for hid in ids:
        ch = ctx.world.characters[hid]
        act = ctx.world.actor(hid)
        ch.resources = {**ch.resources, "hp": max(1, act.hp.maximum - 5), "slots_used": {"1": 2},
                        "uses_spent": {"second_wind": 1}}  # fmt: skip
        ctx.world.invalidate(hid)


async def _place(ctx, template):
    r = await call(ctx, "create_location", {"name": "Стоянка", "template_id": template, "make_current": True})
    assert r["ok"], r


def test_group_vote_watch_and_restore(battle_wizard):
    settings, cid, wiz, fighter, head, client = battle_wizard

    async def fn(ctx):
        await _place(ctx, "location.forest")
        _tired(ctx, wiz, fighter)
        r = await call(ctx, "rest", {"character_ids": [wiz], "kind": "long"})
        res = r["result"]
        vid = res["vote_id"]
        assert "засада" in res["warning"] and res["safety"] == "ненадёжное"
        # второе предложение, пока решают, — отказ
        again = await call(ctx, "rest", {"character_ids": [fighter], "kind": "short"})
        # один герой проголосовал: отдыха ещё нет
        await rest_tools.ballot(ctx, vid, wiz, "sleep", None)
        half = dict(ctx.world.characters[wiz].resources)
        done = await rest_tools.ballot(ctx, vid, fighter, "watch", None)
        return again, half, done["outcome"], ctx.world.characters[wiz].resources, ctx.world.characters[fighter]

    again, half, out, wres, fch = play(settings, cid, [3, 3], fn)
    assert not again["ok"] and "уже решает" in again["error"]
    assert half["slots_used"] == {"1": 2}
    assert out["sleepers"] == [WIZARD["name"]] and out["watchers"] == ["Бран"] and "ambush" not in out
    assert "slots_used" not in wres and wres["hp"] == wres["hp_max"]
    # страж не отдыхал: хиты и умения прежние
    assert fch.resources["hp"] < fch.resources["hp_max"] and fch.resources["uses_spent"] == {"second_wind": 1}


def test_declined_all_watch_and_safe_place(battle_wizard):
    settings, cid, wiz, fighter, head, client = battle_wizard

    async def fn(ctx):
        await _place(ctx, "location.forest")
        _tired(ctx, wiz)
        vid = (await call(ctx, "rest", {"character_ids": [wiz], "kind": "short"}))["result"]["vote_id"]
        await rest_tools.ballot(ctx, vid, wiz, "sleep", None)
        no = await rest_tools.ballot(ctx, vid, fighter, "no", None)
        t0 = ctx.world.scene.game_time
        vid = (await call(ctx, "rest", {"character_ids": [wiz], "kind": "long"}))["result"]["vote_id"]
        await rest_tools.ballot(ctx, vid, wiz, "watch", None)
        watch = await rest_tools.ballot(ctx, vid, fighter, "watch", None)
        took = ctx.world.scene.game_time - t0
        slots = ctx.world.characters[wiz].resources.get("slots_used")
        await _place(ctx, "location.tavern")
        vid = (await call(ctx, "rest", {"character_ids": [wiz], "kind": "short"}))["result"]["vote_id"]
        try:
            await rest_tools.ballot(ctx, vid, wiz, "watch", None)
            safe_watch = None
        except rest_tools.ToolError as e:
            safe_watch = str(e)
        return no["outcome"], watch["outcome"], took, slots, safe_watch

    no, watch, took, slots, safe_watch = play(settings, cid, [3, 3], fn)
    assert no["declined"] == ["Бран"]
    assert watch["no_rest"] and took == 8 * 3600 and slots == {"1": 2}
    assert "безопасное" in safe_watch


def test_ambush_interrupts_rest(battle_wizard):
    settings, cid, wiz, fighter, head, client = battle_wizard

    async def fn(ctx):
        await _place(ctx, "location.lair")
        _tired(ctx, wiz)
        r = await call(ctx, "rest", {"character_ids": [wiz], "kind": "long"})
        assert r["result"]["safety"] == "опасное"
        vid = r["result"]["vote_id"]
        await rest_tools.ballot(ctx, vid, wiz, "sleep", None)
        out = (await rest_tools.ballot(ctx, vid, fighter, "sleep", None))["outcome"]
        surprised = [r.id for _, r in ctx.world.actor(wiz).effects]
        return out, ctx.world.scene.mode, ctx.world.characters[wiz].resources, surprised

    # первая проверка засады — 2 на d6 (опасное место: 1–2), остальное — средние значения
    out, mode, res, effects = play(settings, cid, [2], fn)
    assert out["ambush"]["creatures"] and out["ambush"]["surprised"] and out["ambush"]["hour"] == 4
    assert mode == "combat" and res["slots_used"] == {"1": 2} and "condition.surprised" in effects
    assert not out["results"]


def test_hostiles_block_rest_and_features(battle_wizard):
    settings, cid, wiz, fighter, head, client = battle_wizard

    async def fn(ctx):
        await call(ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин"})
        near = await call(ctx, "rest", {"character_ids": [wiz], "kind": "short"})
        sw = await call(ctx, "use_feature", {"character_id": fighter, "feature": "second_wind"})
        again = await call(ctx, "use_feature", {"character_id": fighter, "feature": "Второе дыхание"})
        none = await call(ctx, "use_feature", {"character_id": wiz, "feature": "rage"})
        return near, sw, again, none

    near, sw, again, none = play(settings, cid, [], fn)
    assert not near["ok"] and "рядом враги" in near["error"]
    assert sw["ok"] and sw["result"]["left"] == 0
    assert not again["ok"] and "после короткого или продолжительного отдыха" in again["error"]
    assert not none["ok"] and "arcane_recovery" in none["error"]
    sheet = ok(client.get(f"/api/campaigns/{cid}/characters/{wiz}", headers=head))
    assert any(f["key"] == "arcane_recovery" for f in sheet["features"])


def test_ballots_over_socket(game_client, admin_g, settings):
    from tests.test_offline import two_players
    from tests.test_ws import connect, next_of

    c, p1, p2, hero = two_players(game_client, admin_g, settings)
    cid = c["id"]

    async def propose(ctx):
        r = await call(ctx, "rest", {"character_ids": [hero["id"]], "kind": "short"})
        assert r["ok"], r
        return r["result"]["vote_id"]

    vid = play(settings, cid, [], propose)
    with connect(game_client, p1, cid) as (w1, snap1), connect(game_client, p2, cid) as (w2, snap2):
        votes = snap2["payload"]["rest_votes"]
        assert [v["vote_id"] for v in votes] == [vid] and len(votes[0]["heroes"]) == 2
        other = next(h["id"] for h in votes[0]["heroes"] if h["id"] != hero["id"])
        # за чужого героя не голосуют: причина приходит сразу
        w2.send_json({"type": "rest.ballot", "payload": {"vote_id": vid, "character_id": hero["id"], "choice": "no"}})
        err = next_of(w2, "error")["payload"]
        assert err["code"] == "rest_rejected" and "не ваш" in err["message"]
        w1.send_json(
            {"type": "rest.ballot", "payload": {"vote_id": vid, "character_id": hero["id"], "choice": "sleep"}}
        )
        upd = next_of(w2, "rest.vote")["payload"]
        assert next(h for h in upd["heroes"] if h["id"] == hero["id"])["choice"] == "sleep"
        w2.send_json({"type": "rest.ballot", "payload": {"vote_id": vid, "character_id": other, "choice": "sleep"}})
        seen, said = False, ""
        for _ in range(30):  # итог в чате приходит раньше, чем карточка голосования закрывается
            e = w1.receive_json()
            if e["type"] == "message.new" and "отдых" in e["payload"]["content"].lower():
                said = e["payload"]["content"]
            seen = seen or (e["type"] == "rest.ended" and e["payload"]["vote_id"] == vid)
            if seen and said:
                break
        m = {"content": said}
        assert "позади" in m["content"], m
