"""Выгрузка придуманных мастером предметов для ревью после сессии."""

import yaml

from app.content.loader import _core_validators
from tests.game import run
from tests.test_invent_item import _invent, _miss
from tests.test_tools import call, game, play  # noqa: F401
from tools.content_gaps import collect, to_yaml


def test_export_is_valid_pack_yaml(game):  # noqa: F811
    settings, cid, hero = game

    async def fn(ctx):
        await _miss(ctx, hero)
        return await call(ctx, "invent_item", _invent())

    assert play(settings, cid, [], fn)["ok"]
    items = run(settings, lambda s: collect(s, cid))
    assert [i["missing_id"] for i in items] == ["item.goodberry_x"]
    doc = yaml.safe_load(to_yaml(items))
    assert doc["kind"] == "item_template"
    rec = doc["items"][0]
    assert rec["status"] == "proposal" and rec["id"] == "item.goodberry_x"
    assert list(_core_validators().get("item_template").iter_errors(rec)) == []
