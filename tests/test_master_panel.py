# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Панель живого мастера (этап 7, часть 6): формы инструментов со списками значений только месту мастера."""

from tests.game import party
from tests.test_master import admin_g, dice, game_client, llm  # noqa: F401 — фикстуры


def _field(panel, tool, name):
    t = next(t for t in panel["tools"] if t["name"] == tool)
    return next(f for f in t["fields"] if f["name"] == name)


def test_panel_hidden_from_owner_when_ai_masters(game_client, admin_g):
    c, _, _ = party(game_client, admin_g)
    assert game_client.get(f"/api/campaigns/{c['id']}/master-panel", headers=admin_g).status_code == 404
