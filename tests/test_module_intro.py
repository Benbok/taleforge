# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Общее вступление готового приключения: одно на все кампании по модулю; приветствие мастера перед первой игрой."""

import base64
import dataclasses
import json

import httpx
from fastapi.testclient import TestClient

from app.agents import module_intro
from app.agents.llm import ScriptedLLM
from app.core import voice
from app.db.models import Message
from app.main import create_app
from tests.conftest import login
from tests.game import FIGHTER, QueueDice, import_base, ok
from tests.test_adventure import publish_sample
from tests.test_api import invite, make_campaign, register
from tests.test_master import rows

STORY = "Скелеты бродят по кладбищу Давоса.\n\nПеред вами — ворота склепа."


def party(client, admin, n: int, **kw):
    """Кампания по модулю с одним одобренным героем и начатой сессией; игрок у каждой кампании свой."""
    c = make_campaign(client, admin, players=1, creation_rules={"review": "auto"}, collect_window_sec=0, **kw)
    head = register(client, invite(client, admin, c["id"])["token"], f"Игрок{n}")
    ch = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=head), 201)
    ok(client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/submit", headers=head))
    ok(client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin))
    return c


def _app(settings, tmp_path):
    import_base(settings)
    settings = dataclasses.replace(settings, media_dir=tmp_path / "media", gemini_tts_api_key="test-gemini-key")
    spoken: list[str] = []

    def tts(request: httpx.Request) -> httpx.Response:
        spoken.append(json.loads(request.content)["contents"][0]["parts"][0]["text"])
        pcm = base64.b64encode(b"\x00\x00" * 2400).decode("ascii")
        part = {"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": pcm}}
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [part]}}]})

    llm = ScriptedLLM([])
    client = TestClient(create_app(settings, llm=llm, dice_factory=lambda: QueueDice([15] * 20)))
    return settings, client, llm, spoken, tts


def test_module_intro_written_once_for_all_campaigns(settings, tmp_path):
    settings, client, llm, spoken, tts = _app(settings, tmp_path)
    with client:
        client.app.state.tts.engines["gemini"]._transport = httpx.MockTransport(tts)
        root = login(client, "root", "rootpass")
        client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root)
        admin = login(client, "Arty", "secret1")
        mid = publish_sample(settings)
        master = client.app.state.master
        llm.replies.append({"text": STORY, "campaign_intro": True})

        # публикация готовит вступление сама: текст и голос лежат у модуля
        assert client.portal.call(module_intro.prepare_module, master, mid) is True
        assert len(llm.intro_requests) == 1
        assert "Ты — мастер" in llm.intro_requests[0]["messages"][0]["content"]
        voiced = len(spoken)
        assert voiced >= 1

        out = []
        for n in range(2):
            c = party(client, admin, n, module_id=mid)
            client.portal.call(master.wait_idle, None)
            cid = c["id"]
            msgs = rows(settings, Message, Message.campaign_id == cid)
            intro = next(m for m in msgs if "Скелеты бродят" in m.content)
            greeting = next(m for m in msgs if (m.data or {}).get("greeting"))
            assert greeting.seq < intro.seq  # мастер сперва приветствует игроков, потом вступление
            for v in intro.data["voices"]:  # записи модуля скопированы в кампанию: игрок их слышит
                assert voice.read(settings.media_dir, cid, v["id"])[1]
            out.append(intro.data["voices"])

        # ни новых вызовов модели на вступление, ни нового синтеза: обе кампании взяли копию
        assert len(llm.intro_requests) == 1
        assert out[0] == out[1]
        assert len(llm.greeting_requests) == 2  # приветствие у каждой кампании своё — к её героям
        assert not any("Скелеты" in x for x in spoken[voiced:])


def test_new_hook_or_voice_fills_the_module_cache(settings, tmp_path):
    """Нет вступления для зацепки — его пишет первая кампания и кладёт в кэш для следующих."""
    settings, client, llm, spoken, tts = _app(settings, tmp_path)
    with client:
        client.app.state.tts.engines["gemini"]._transport = httpx.MockTransport(tts)
        root = login(client, "root", "rootpass")
        client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root)
        admin = login(client, "Arty", "secret1")
        mid = publish_sample(settings)
        master = client.app.state.master
        llm.replies.append({"text": STORY, "campaign_intro": True})
        for n in range(2):
            party(client, admin, n, module_id=mid, module_hook="board")
            client.portal.call(master.wait_idle, None)
        assert len(llm.intro_requests) == 1
        text, voices = module_intro.cached(settings.media_dir, mid, "1.0.0", "board", "gemini", None)
        assert text == STORY and voices

        # новая версия модуля сбрасывает кэш
        assert module_intro.cached(settings.media_dir, mid, "1.0.1", "board", "gemini", None) == ("", None)
