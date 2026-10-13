"""Промах каталога предметов: сервер называет его missing_content и пишет CONTENT_GAP (спецификация 2026-10-13)."""

import logging

from tests.test_tools import call, game, play  # noqa: F401


def test_missing_item_template_is_content_gap(game, caplog):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        with caplog.at_level(logging.WARNING):
            r = await call(ctx, "give_item", {"character_id": hero, "item_template_id": "item.goodberry_x",
                                               "qty": 2, "reason": "ягоды"})  # fmt: skip
        return r, set(ctx.content_misses)

    r, misses = play(settings, cid, [], fn)
    assert not r["ok"] and r["failure"]["code"] == "missing_content"
    assert r["failure"]["category"] == "rule_denial"
    assert "invent_item" in r["error"]
    assert misses == {("item_template", "item.goodberry_x")}
    line = next(x.getMessage() for x in caplog.records if x.getMessage().startswith("CONTENT_GAP"))
    assert "missing=item.goodberry_x" in line and "tool=give_item" in line and f"campaign={cid}" in line


def test_other_catalog_errors_stay_unclassified(game):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        r = await call(ctx, "spawn_entity", {"creature_template_id": "creature.nope", "name": "Никто"})
        return r, set(ctx.content_misses)

    r, misses = play(settings, cid, [], fn)
    assert not r["ok"] and r["failure"]["code"] != "missing_content" and misses == set()
