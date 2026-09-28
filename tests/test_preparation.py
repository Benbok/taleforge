# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Подготовка кампании: анкета владельца и персона ИИ-мастера (этап 6, первая часть)."""

from app.core.brief import brief_text
from app.core.personas import compose_style
from app.db.models import AgentConfig
from tests.conftest import login
from tests.game import ok, party
from tests.test_api import invite, make_campaign, register
from tests.test_master import DONE, act, admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры

BRIEF = {
    "length": "short",
    "pillars": {"combat": "low", "mystery": "high"},
    "emotions": ["fear", "moral"],
    "threat": "regional",
    "wishes": "злодей — кто-то из своих",
}
GRIM = {
    "seriousness": 5,
    "humor": "none",
    "darkness": 5,
    "verbosity": "short",
    "manner": "chronicler",
    "notes": "Шёпотом",
}


def test_brief_text():
    text = brief_text(BRIEF)
    assert "короткая, 3–5 сессий" in text
    assert "бои — мало, мистика и тайны — много" in text
    assert "страх, моральный выбор" in text and "город или регион" in text
    assert "злодей — кто-то из своих" in text
    assert brief_text({}) == "" and brief_text(None) == ""


def test_compose_style():
    style = compose_style(GRIM, "Говорит медленно.")
    assert "полная серьёзность" in style and "без юмора" in style and "жёсткий гримдарк" in style
    assert "хроникёр" in style and "Своими словами: Шёпотом" in style and style.endswith("Говорит медленно.")
    assert "механику и сложность задают правила" in style


def test_options_and_personas_crud(game_client, admin_g):
    opts = ok(game_client.get("/api/campaign-options", headers=admin_g))
    assert opts["brief"]["length"]["oneshot"] == "ваншот, одна сессия"
    assert {p["id"] for p in opts["presets"]} >= {"chronicler", "innkeeper", "storyteller", "referee"}
    assert all(p["style"] for p in opts["presets"])

    p = ok(
        game_client.post("/api/me/master-personas", json={"name": "Летописец", "settings": GRIM}, headers=admin_g), 201
    )
    assert p["settings"]["darkness"] == 5 and p["settings"]["pace"] == "even"  # не заданное — по умолчанию
    assert "жёсткий гримдарк" in p["style"]
    r = game_client.post("/api/me/master-personas", json={"name": "Летописец"}, headers=admin_g)
    assert r.status_code == 409
    bad = game_client.post("/api/me/master-personas", json={"name": "X", "settings": {"darkness": 9}}, headers=admin_g)
    assert bad.status_code == 422
    p = ok(game_client.patch(f"/api/me/master-personas/{p['id']}", json={"name": "Хроникёр"}, headers=admin_g))
    assert [x["name"] for x in ok(game_client.get("/api/me/master-personas", headers=admin_g))] == ["Хроникёр"]

    player = ok(game_client.post("/api/auth/signup", json={"name": "Гимли", "password": "pass123"}))
    head = {"Authorization": f"Bearer {player['token']}"}
    assert game_client.get("/api/me/master-personas", headers=head).status_code == 403
    assert game_client.delete(f"/api/me/master-personas/{p['id']}", headers=head).status_code == 403
    assert game_client.delete(f"/api/me/master-personas/{p['id']}", headers=admin_g).status_code == 204
    assert ok(game_client.get("/api/me/master-personas", headers=admin_g)) == []


def test_campaign_brief_and_persona_copy(game_client, admin_g, settings):
    p = ok(
        game_client.post("/api/me/master-personas", json={"name": "Летописец", "settings": GRIM}, headers=admin_g), 201
    )
    master = {"type": "agent", "provider": "claude", "model": "x", "persona_id": p["id"], "style": "Говорит медленно."}
    c = make_campaign(game_client, admin_g, brief=BRIEF, master=master)
    assert c["brief"] == BRIEF

    # игрок анкету не видит: в пожеланиях могут быть спойлеры
    inv = invite(game_client, admin_g, c["id"])
    head = register(game_client, inv["token"], "Гимли")
    assert ok(game_client.get(f"/api/campaigns/{c['id']}", headers=head))["brief"] is None
    assert (
        game_client.put(
            f"/api/campaigns/{c['id']}/master-persona", json={"preset": "referee"}, headers=head
        ).status_code
        == 403
    )

    got = ok(game_client.get(f"/api/campaigns/{c['id']}/master-persona", headers=admin_g))
    assert got["name"] == "Летописец" and got["source"] == "profile" and got["style"] == "Говорит медленно."

    # правка персоны в профиле не трогает кампанию: у неё копия
    ok(game_client.patch(f"/api/me/master-personas/{p['id']}", json={"settings": {"darkness": 1}}, headers=admin_g))
    (agent,) = rows(settings, AgentConfig)
    assert "жёсткий гримдарк" in agent.persona and agent.persona.endswith("Говорит медленно.")

    got = ok(game_client.put(f"/api/campaigns/{c['id']}/master-persona", json={"preset": "innkeeper"}, headers=admin_g))
    assert got["name"] == "Весёлый трактирщик" and got["source"] == "preset"
    got = ok(
        game_client.put(
            f"/api/campaigns/{c['id']}/master-persona", json={"settings": {"humor": "absurd"}}, headers=admin_g
        )
    )
    assert got["source"] == "custom" and got["settings"]["humor"] == "absurd"
    r = game_client.put(f"/api/campaigns/{c['id']}/master-persona", json={"preset": "nope"}, headers=admin_g)
    assert r.status_code == 404

    c = ok(game_client.patch(f"/api/campaigns/{c['id']}", json={"brief": {"length": "oneshot"}}, headers=admin_g))
    assert c["brief"] == {"length": "oneshot"}


def test_someone_elses_persona_is_not_found(game_client, admin_g):
    p = ok(game_client.post("/api/me/master-personas", json={"name": "Мой", "settings": {}}, headers=admin_g), 201)
    root = login(game_client, "root", "rootpass")
    master = {"type": "agent", "provider": "claude", "model": "x", "persona_id": p["id"]}
    r = game_client.post("/api/campaigns", json={"name": "Чужая", "master": master}, headers=root)
    assert r.status_code == 404


def test_master_prompt_has_brief_and_persona(game_client, admin_g, llm):
    master = {"type": "agent", "provider": "claude", "model": "x", "persona_preset": "chronicler"}
    c, (p1,), _ = party(game_client, admin_g, master=master, brief=BRIEF)
    llm.replies += [DONE, {"text": "Тишина."}]
    act(game_client, p1, c["id"], "Осматриваюсь")
    system = llm.requests[0]["messages"][0]["content"]
    assert "Чего ждут от кампании" in system and "злодей — кто-то из своих" in system
    assert "хроникёр" in system and "жёсткий гримдарк" in system
