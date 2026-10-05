"""Схема контракта для клиента (web/openapi.json) собрана из текущего кода: python -m app.contract."""

from app.contract import SCHEMA_PATH, render
from app.gateway.protocol import SERVER_EVENTS


def test_schema_is_fresh():
    assert SCHEMA_PATH.read_text(encoding="utf-8") == render(), "web/openapi.json устарел: python -m app.contract"


def test_every_event_is_in_schema():
    import json

    events = json.loads(render())["components"]["schemas"]["ServerEvent"]["discriminator"]["mapping"]
    assert sorted(events) == sorted(SERVER_EVENTS)
