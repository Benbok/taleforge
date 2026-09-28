# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Главная нового клиента: карточки кампаний, тема пакета и раздача клиента (этап 7, документ дизайна)."""

import pytest
import yaml
from pydantic import ValidationError

from app.content import theme
from app.content.manifest import PackManifest
from tests.game import ok, party
from tests.test_api import make_campaign
from tests.test_master import admin_g, dice, game_client, llm  # noqa: F401 — фикстуры


def test_theme_merge_and_contrast():
    base = theme.merge([])
    assert base["dark"]["bg"] == theme.DEFAULT["dark"]["bg"] and theme.contrast_problems(base) == []
    t = theme.merge([{"dark": {"accent": "#112233"}}, {"dark": {"accent": "#445566"}, "labels": {"origin": "Род"}}])
    assert t["dark"]["accent"] == "#445566" and t["dark"]["bg"] == base["dark"]["bg"] and t["labels"]["origin"] == "Род"
    assert "master_status.rolling" in t["labels"]
    assert round(theme.contrast("#000000", "#ffffff"), 1) == 21.0

    with pytest.raises(ValidationError, match="контраст"):
        theme.Theme(dark={"text": "#333333", "bg": "#222222"})
    with pytest.raises(ValidationError, match="#rrggbb"):
        theme.Theme(light={"bg": "white"})
    with pytest.raises(ValidationError, match="fonts.googleapis.com"):
        theme.Theme(font_css="https://evil.example/f.css")
    with pytest.raises(ValidationError):
        theme.Theme(layout={"columns": 2})  # раскладку пакет не меняет


def test_echo_pack_theme_is_readable():
    raw = yaml.safe_load(open("content/echo-leviathans/pack.yaml", encoding="utf-8"))
    m = PackManifest(**raw)
    assert m.theme and m.theme.dark.accent == "#b87333"
    assert theme.contrast_problems(theme.merge([m.theme.model_dump(exclude_none=True)])) == []


def test_default_theme_and_campaign_theme(game_client, admin_g):
    assert ok(game_client.get("/api/theme"))["fonts"]["narration"]
    c = make_campaign(game_client, admin_g)
    t = ok(game_client.get(f"/api/campaigns/{c['id']}/theme", headers=admin_g))
    assert t["dark"] == theme.DEFAULT["dark"]  # у базового пакета SRD своей темы нет
    assert game_client.get(f"/api/campaigns/{c['id']}/theme").status_code == 401


def test_campaign_cards(game_client, admin_g):
    c, (p1, p2), hero = party(game_client, admin_g, players=2)
    cards = ok(game_client.get("/api/me/campaigns", headers=p1))
    (card,) = cards
    assert card["id"] == c["id"] and card["status"] == "active" and card["session_live"]
    assert card["my_role"] == "player" and not card["is_owner"]
    assert card["hero"] == {"id": hero["id"], "name": "Бран", "status": "approved", "level": 1}
    players = [m for m in card["party"] if m["role"] == "player"]
    assert [m["user_name"] for m in players] == ["Арагорн", "Гимли"] and players[0]["hero_name"] == "Бран"
    assert card["party"][0]["role"] == "master" and card["waiting_players"] == 0
    assert "brief" not in card and "settings" not in card

    (own,) = ok(game_client.get("/api/me/campaigns", headers=admin_g))
    assert own["is_owner"] and own["my_role"] is None and own["hero"] is None

    ok(game_client.post(f"/api/campaigns/{c['id']}/session/pause", headers=admin_g))
    (card,) = ok(game_client.get("/api/me/campaigns", headers=p2))
    assert card["status"] == "paused" and not card["session_live"] and card["last_session_at"]


def test_spa_and_legacy_routes(game_client):
    # без сборки нового клиента прежний отдаётся и на /, и на /legacy
    assert "<html" in game_client.get("/").text.lower()
    assert game_client.get("/legacy").status_code == 200
    for name in ("profile", "heroes", "masterlog", "preparation"):  # все скрипты прежнего клиента
        assert game_client.get(f"/static/{name}.js").status_code == 200, name
    assert game_client.get("/c/c_1").status_code == 200
    assert game_client.get("/api/nope").status_code == 404
    assert game_client.get("/assets/..%2Fmain.py").status_code == 404
    assert game_client.get("/assets/nope.js").status_code == 404
