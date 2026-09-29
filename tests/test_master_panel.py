# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Панель живого мастера (этап 7, часть 6): формы инструментов со списками значений только месту мастера."""

from tests.game import ok, party
from tests.test_master import admin_g, dice, game_client, llm  # noqa: F401 — фикстуры
from tests.test_ws import connect, next_of


def _field(panel, tool, name):
    t = next(t for t in panel["tools"] if t["name"] == tool)
    return next(f for f in t["fields"] if f["name"] == name)


def test_panel_lists_values_and_labels_for_master_seat(game_client, admin_g):
    c, (p1,), hero = party(game_client, admin_g, master={"type": "owner"})
    panel = ok(game_client.get(f"/api/campaigns/{c['id']}/master-panel", headers=admin_g))
    labels = panel["labels"]
    assert labels[hero["id"]] == "Бран"
    assert hero["id"] in _field(panel, "give_item", "character_id")["options"]
    items = _field(panel, "give_item", "item_template_id")["options"]
    assert "item.longsword" in items and labels["item.longsword"]
    stat = _field(panel, "roll_check", "stat")["options"]
    assert "athletics" in stat and labels["athletics"] == "Атлетика"
    assert "dc.medium" in _field(panel, "roll_check", "difficulty")["options"]
    inv = _field(panel, "take_item", "inventory_id")["options"]
    assert inv and all("(Бран)" in labels[i] for i in inv)
    move = _field(panel, "move", "character_ids")
    assert move["many"] and move["required"]
    groups = {t["name"]: t["group"] for t in panel["tools"]}
    assert groups["whisper"] == "players" and groups["advance_plot"] == "plot" and groups["spawn_entity"] == "scene"
    assert not panel["has_plot"]
    # игроку панель не отдаётся
    assert game_client.get(f"/api/campaigns/{c['id']}/master-panel", headers=p1).status_code == 404


def test_panel_hidden_from_owner_when_ai_masters(game_client, admin_g):
    c, _, _ = party(game_client, admin_g)
    assert game_client.get(f"/api/campaigns/{c['id']}/master-panel", headers=admin_g).status_code == 404


def test_live_master_calls_show_in_log(game_client, admin_g):
    c, _, hero = party(game_client, admin_g, master={"type": "owner"})
    with connect(game_client, admin_g, c["id"]) as (ws, _):
        args = {"character_id": hero["id"], "item_template_id": "item.dagger", "reason": "сундук"}
        ws.send_json({"type": "master.tool", "payload": {"tool": "give_item", "args": args, "request_id": "r1"}})
        res = next_of(ws, "master.tool.result")["payload"]
        assert res["ok"] and res["request_id"] == "r1", res
        whisper = {"tool": "whisper", "args": {"character_id": hero["id"], "text": "тсс"}}
        ws.send_json({"type": "master.tool", "payload": whisper})
        assert next_of(ws, "master.tool.result")["payload"]["ok"]
    log = ok(game_client.get(f"/api/campaigns/{c['id']}/master-log", headers=admin_g))
    tools = [x["tool"] for x in log["live"]]
    assert tools[:2] == ["whisper", "give_item"], tools
    assert log["live"][1]["result"]["qty"] == 1
    assert log["live"][0]["secret"] is True
