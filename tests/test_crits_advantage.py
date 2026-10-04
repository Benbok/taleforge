"""Криты 20 и 1 в бою и вне боя, преимущество и помеха по обстоятельствам, инициатива с эффектами."""

import pytest
from sqlalchemy import select

from app.core.rolls import card
from app.db.models import Event
from app.rules import FixedDice, RollMode
from app.rules.dnd5e import Dnd5eEngine
from app.rules.dnd5e import modifiers as mod
from tests.game import import_base, party, run
from tests.test_tools import call, play

E = Dnd5eEngine()


@pytest.fixture
def game(client, admin, settings):
    import_base(settings)
    c, _, ch = party(client, admin)
    return settings, c["id"], ch["id"]


def test_check_crits_only_by_campaign_rule():
    assert not E.check(FixedDice([20]), 0, 25).success  # SRD как есть
    r = E.check(FixedDice([20]), 0, 25, crits=True)
    assert r.success and r.critical == "success"
    r = E.saving_throw(FixedDice([1]), 15, 10, crits=True)
    assert not r.success and r.critical == "fail"
    assert E.check(FixedDice([12]), 0, 10, crits=True).critical is None


def test_circumstance_combines_with_effects():
    adv, dis = RollMode.ADVANTAGE, RollMode.DISADVANTAGE
    assert mod.with_circumstance(RollMode.NORMAL, [], "advantage", "удачный замысел")[0] is adv
    assert mod.with_circumstance(adv, ["преимущество: x"], "disadvantage", "темно")[0] is RollMode.NORMAL
    # эффекты уже погасили друг друга: новое преимущество помеху не перебивает
    mode, reasons = mod.with_circumstance(RollMode.NORMAL, ["преимущество: a", "помеха: b"], "advantage", "c")
    assert mode is RollMode.NORMAL and reasons[-1] == "преимущество: c"
    assert mod.with_circumstance(dis, ["помеха: b"], "none", None) == (dis, ["помеха: b"])


def test_roll_check_edge_needs_reason_and_picks_die(game):
    settings, cid, hero = game
    base = {"character_id": hero, "stat": "athletics", "difficulty": "dc.medium", "reason": "сорвать решётку"}

    async def fn(ctx):
        bare = await call(ctx, "roll_check", {**base, "edge": "advantage"})
        good = await call(ctx, "roll_check", {**base, "edge": "advantage", "edge_reason": "рычаг из ножки койки"})
        return bare, good

    bare, good = play(settings, cid, [3, 17], fn)
    assert not bare["ok"] and "edge_reason" in bare["error"]
    r = good["result"]
    assert r["natural"] == 17 and "преимущество: рычаг из ножки койки" in r["reasons"]


def test_roll_check_crit_success_and_fail(game):
    settings, cid, hero = game
    args = {"character_id": hero, "stat": "athletics", "difficulty": "dc.nearly_impossible", "reason": "x"}

    async def fn(ctx):
        hi = await call(ctx, "roll_check", args, key="k1")
        lo = await call(ctx, "roll_check", {**args, "difficulty": "dc.very_easy"}, key="k2")
        ctx.campaign.settings = {**(ctx.campaign.settings or {}), "critical_checks": False}
        off = await call(ctx, "roll_check", args, key="k3")
        return hi, lo, off

    hi, lo, off = play(settings, cid, [20, 1, 20], fn)
    assert hi["result"]["success"] and hi["result"]["critical"] == "success"
    assert not lo["result"]["success"] and lo["result"]["critical"] == "fail"
    assert not off["result"]["success"] and "critical" not in off["result"]

    async def cards(s):
        evs = (await s.scalars(select(Event).where(Event.tool == "roll_check").order_by(Event.idempotency_key))).all()
        return [card(e, {hero})["outcome"] for e in evs]

    assert run(settings, cards) == ["crit_success", "crit_fail", "fail"]


def test_attack_fumble_and_edge(game):
    settings, cid, hero = game

    async def fn(ctx):
        sp = await call(
            ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин", "zone": "melee"}
        )
        gob = sp["result"]["spawned"][0]["id"]
        a = {"attacker_id": hero, "target_id": gob, "attack": "item.longsword"}
        fumble = await call(ctx, "resolve_attack", a, key="a1")
        dis = await call(ctx, "resolve_attack", {**a, "edge": "disadvantage", "edge_reason": "скользкий пол"}, key="a2")
        return fumble, dis

    fumble, dis = play(settings, cid, [1, 18, 4], fn)
    assert fumble["result"]["fumble"] and not fumble["result"]["hit"]
    r = dis["result"]
    assert r["mode"] == "disadvantage" and r["natural"] == 4 and "помеха: скользкий пол" in r["reasons"]

    async def cards(s):
        q = select(Event).where(Event.tool == "resolve_attack").order_by(Event.idempotency_key)
        return card((await s.scalars(q)).first(), {hero})["outcome"]

    assert run(settings, cards) == "fumble"


def test_initiative_is_dex_check_with_effects(game):
    settings, cid, hero = game

    async def fn(ctx):
        await call(ctx, "apply_effect", {"target_id": hero, "effect_template_id": "condition.poisoned"})
        await call(ctx, "spawn_entity", {"creature_template_id": "creature.goblin", "name": "Гоблин"})
        return await call(ctx, "set_scene_mode", {"mode": "combat"})

    r = play(settings, cid, [], fn)
    assert r["ok"], r

    async def dice(s):
        ev = (await s.scalars(select(Event).where(Event.tool == "set_scene_mode"))).one()
        return {d["who"]: d for d in ev.dice}

    d = run(settings, dice)[hero]
    assert d["mode"] == "disadvantage" and len(d["d20"]) == 2 and d["reasons"]
