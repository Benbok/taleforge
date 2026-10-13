"""Мастер придумывает недостающий предмет с ограниченной механикой (спецификация 2026-10-13, §3–§4)."""

import logging

import pytest

from app.db.models import Campaign, Event
from app.tools.master.invented import power_errors
from tests.game import run
from tests.test_tools import call, game, play  # noqa: F401

HEAL = [{"op": "resource", "stat": "hp", "delta": 2}]


def _invent(missing="item.goodberry_x", **kw):
    return {
        "missing_id": missing,
        "name": "Добрая ягода",
        "description": "Лечит 2 хита.",
        "category": "consumable",
        "modifiers": HEAL,
        "reason": "ягоды от заклинания",
        **kw,
    }


async def _miss(ctx, hero, rid="item.goodberry_x", qty=3):
    return await call(ctx, "give_item", {"character_id": hero, "item_template_id": rid, "qty": qty, "reason": "-"})


@pytest.mark.parametrize(
    "category, mods, text",
    [
        ("consumable", [{"op": "resource", "stat": "hp", "delta": "3d8"}], "лечение"),
        ("consumable", [{"op": "resource", "stat": "hp", "delta": -3}], "лечение"),
        ("consumable", [{"op": "add", "target": "temp_hp", "value": 9}], "временных"),
        ("consumable", [{"op": "remove_condition", "condition": "paralyzed"}], "снять"),
        ("consumable", [{"op": "extra_damage", "dice": "1d6"}], "операция"),
        ("consumable", [{"op": "custom", "draft": "x"}], "операция"),
        ("consumable", [{"op": "resource", "stat": "hp", "delta": 1, "if": {"x": 1}}], "условия"),
        ("trinket", HEAL, "consumable"),
    ],
)
def test_power_ceiling(category, mods, text):
    errors = power_errors(category, mods)
    assert errors and any(text in e for e in errors), errors


def test_power_ceiling_accepts_srd_like_items():
    assert power_errors("consumable", [{"op": "resource", "stat": "hp", "delta": "2d4+2"}]) == []
    assert power_errors("consumable", [{"op": "add", "target": "temp_hp", "value": 5}]) == []
    assert power_errors("consumable", [{"op": "remove_condition", "any_of": ["poisoned"]}]) == []
    assert power_errors("trinket", []) == []


def test_invent_after_miss_then_give_and_use_heals(game, caplog):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        a = ctx.world.actor(hero)
        a.hp.current = a.hp.maximum - 5
        a.save_hp()
        assert not (await _miss(ctx, hero))["ok"]
        with caplog.at_level(logging.WARNING):
            made = await call(ctx, "invent_item", _invent())
        given = await call(ctx, "give_item", {"character_id": hero, "item_template_id": "item.goodberry_x",
                                              "qty": 3, "reason": "ягоды"})  # fmt: skip
        inv = next(i for i in ctx.world.inventory[hero] if i.item_template_id == "item.goodberry_x")
        used = await call(ctx, "use_item", {"character_id": hero, "inventory_id": inv.id})
        return made, given, used, ctx.world.actor(hero).hp.current, ctx.world.actor(hero).hp.maximum

    made, given, used, hp, hp_max = play(settings, cid, [], fn)
    assert made["ok"] and made["result"]["item_template_id"] == "item.goodberry_x", made
    assert given["ok"] and used["ok"], (given, used)
    assert hp == hp_max - 3
    line = next(x.getMessage() for x in caplog.records if "invented=" in x.getMessage())
    assert line.startswith("CONTENT_GAP") and "missing=item.goodberry_x" in line and "resource:hp:2" in line
    ev = next(e for e in run(settings, lambda s: _events(s, cid)) if e.tool == "invent_item")
    assert ev.hidden and ev.payload["record"]["modifiers"] == HEAL and ev.payload["missing_id"] == "item.goodberry_x"


async def _events(s, cid):
    from sqlalchemy import select

    return (await s.scalars(select(Event).where(Event.campaign_id == cid))).all()


def test_invent_without_miss_is_refused(game):  # noqa: F811
    settings, cid, hero = game
    r = play(settings, cid, [], lambda ctx: call(ctx, "invent_item", _invent()))
    assert not r["ok"] and r["failure"]["code"] == "no_content_gap"


def test_invent_refused_in_combat_and_modules(game):  # noqa: F811
    settings, cid, hero = game

    async def combat(ctx):
        await _miss(ctx, hero)
        ctx.world.scene.mode, ctx.world.scene.turn_order = "combat", [hero]
        out = await call(ctx, "invent_item", _invent())
        ctx.world.scene.mode, ctx.world.scene.turn_order = "normal", []
        return out

    assert "бою" in play(settings, cid, [], combat)["error"]

    async def module(s):
        c = await s.get(Campaign, cid)
        c.settings = {**(c.settings or {}), "module": "m_1"}
        await s.commit()

    run(settings, module)

    async def again(ctx):
        await _miss(ctx, hero)
        return await call(ctx, "invent_item", _invent())

    assert "модул" in play(settings, cid, [], again)["error"]


def test_modifiers_only_on_consumables(game):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        await _miss(ctx, hero)
        return await call(ctx, "invent_item", _invent(category="trinket"))

    r = play(settings, cid, [], fn)
    assert not r["ok"] and "consumable" in r["error"]


def test_per_turn_limit(game):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        out = []
        for i in range(3):
            rid = f"item.gap_{i}"
            await _miss(ctx, hero, rid)
            out.append(await call(ctx, "invent_item", _invent(missing=rid, name=f"Ягода {i}")))
        return out

    a, b, c = play(settings, cid, [], fn)
    assert a["ok"] and b["ok"] and not c["ok"] and "за ход" in c["error"]


def test_give_invented_item_qty_capped(game):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        await _miss(ctx, hero)
        await call(ctx, "invent_item", _invent())
        return await call(ctx, "give_item", {"character_id": hero, "item_template_id": "item.goodberry_x",
                                             "qty": 50, "reason": "-"})  # fmt: skip

    r = play(settings, cid, [], fn)
    assert not r["ok"] and "10" in r["error"]
