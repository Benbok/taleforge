# ruff: noqa: F811
"""Нрав ИИ-мастера (эмоции): выбор из списка в кабинете, хранится в настройках мастера кампании."""

from app.db.models import AgentConfig
from tests.game import ok
from tests.test_master import admin_g, dice, game_client, llm, rows  # noqa: F401


def test_master_temper_pick(game_client, admin_g, settings):
    camp = {"name": "Нрав", "difficulty": "normal", "master": {"type": "agent"}}
    cid = ok(game_client.post("/api/campaigns", json=camp, headers=admin_g), code=201)["id"]
    url = f"/api/campaigns/{cid}/master-temper"

    got = ok(game_client.get(url, headers=admin_g))
    assert got["value"] == "tired_mentor"  # по умолчанию
    assert {o["id"]: o["name"] for o in got["options"]} == {"sadist": "Садист", "tired_mentor": "Уставший наставник"}

    assert ok(game_client.put(url, json={"value": "sadist"}, headers=admin_g))["value"] == "sadist"
    (agent,) = [a for a in rows(settings, AgentConfig) if (a.settings or {}).get("emotion_persona")]
    assert agent.settings["emotion_persona"] == "sadist"

    bad = game_client.put(url, json={"value": "nope"}, headers=admin_g)
    assert bad.status_code == 409 and "nope" in bad.text
