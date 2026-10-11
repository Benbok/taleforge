# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Общее вступление готового приключения: черновик в карточке, проверка админом, одно сохранённое на все кампании;
приветствие мастера перед первой игрой."""

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


def party(client, admin, n: int, start: bool = True, **kw):
    """Кампания по модулю с одним одобренным героем и начатой сессией; игрок у каждой кампании свой."""
    c = make_campaign(client, admin, players=1, creation_rules={"review": "auto"}, collect_window_sec=0, **kw)
    head = register(client, invite(client, admin, c["id"])["token"], f"Игрок{n}")
    ch = ok(client.post(f"/api/campaigns/{c['id']}/characters", json=FIGHTER, headers=head), 201)
    ok(client.post(f"/api/campaigns/{c['id']}/characters/{ch['id']}/submit", headers=head))
    if start:
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


def _login(client):
    root = login(client, "root", "rootpass")
    client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root)
    return login(client, "Arty", "secret1")


def test_admin_reviews_module_intro_and_campaigns_share_it(settings, tmp_path):
    settings, client, llm, spoken, tts = _app(settings, tmp_path)
    with client:
        client.app.state.tts.engines["gemini"]._transport = httpx.MockTransport(tts)
        admin = _login(client)
        mid = publish_sample(settings)
        master = client.app.state.master
        idle = lambda: client.portal.call(master.wait_idle, None)  # noqa: E731
        url = f"/api/admin/modules/{mid}/intro"
        llm.replies.append({"text": STORY, "campaign_intro": True})

        # публикация готовит черновик сама; без сохранения кампании его не берут
        client.portal.call(module_intro.prepare_module, master, mid)
        st = ok(client.get(url, headers=admin))
        assert [h["id"] for h in st["hooks"]] == ["noble", "board"] and st["saved"] == {}
        d = st["draft"]
        assert d["status"] == "ready" and d["text"] == STORY and d["hook_id"] == "noble" and d["voices"]
        assert "Ты — мастер" in llm.intro_requests[0]["messages"][0]["content"]
        res = client.get(f"{url}/voice/{d['voices'][0]['id']}", headers=admin)  # админ слушает черновик
        assert res.status_code == 200 and res.content.startswith(b"RIFF")

        # пересоздание своим текстом: модель не зовётся, озвучивается текст админа
        mine = "Туман над склепом. Перед вами — ворота."
        ok(client.post(f"{url}/draft", json={"hook_id": "noble", "text": mine}, headers=admin))
        idle()
        d = ok(client.get(url, headers=admin))["draft"]
        assert d["status"] == "ready" and d["text"] == mine and len(llm.intro_requests) == 1
        st = ok(client.post(f"{url}/save", headers=admin))
        assert st["draft"] is None and st["saved"]["noble"]["text"] == mine
        assert client.post(f"{url}/save", headers=admin).status_code == 409  # сохранять больше нечего
        voiced = len(spoken)

        out = []
        for n in range(2):
            c = party(client, admin, n, module_id=mid)
            idle()
            cid = c["id"]
            msgs = rows(settings, Message, Message.campaign_id == cid)
            intro = next(m for m in msgs if "Туман над склепом" in m.content)
            greeting = next(m for m in msgs if (m.data or {}).get("greeting"))
            assert greeting.seq < intro.seq  # мастер сперва приветствует игроков, потом вступление
            for v in intro.data["voices"]:  # записи модуля скопированы в кампанию: игрок их слышит
                assert voice.read(settings.media_dir, cid, v["id"])[1]
            out.append(intro.data["voices"])

        # ни новых вызовов модели на вступление, ни нового синтеза: обе кампании взяли сохранённое
        assert len(llm.intro_requests) == 1
        assert out[0] == out[1] == st["saved"]["noble"]["voices"]
        assert len(llm.greeting_requests) == 2  # приветствие у каждой кампании своё — к её героям
        assert not any("Туман над склепом" in x for x in spoken[voiced:])


def test_campaign_without_saved_intro_writes_its_own(settings, tmp_path):
    """Нет сохранённого вступления для зацепки — кампания пишет своё, общее не трогает."""
    settings, client, llm, spoken, tts = _app(settings, tmp_path)
    with client:
        client.app.state.tts.engines["gemini"]._transport = httpx.MockTransport(tts)
        admin = _login(client)
        mid = publish_sample(settings)
        llm.replies.append({"text": STORY, "campaign_intro": True})
        party(client, admin, 0, module_id=mid, module_hook="board")
        client.portal.call(client.app.state.master.wait_idle, None)
        assert len(llm.intro_requests) == 1
        assert module_intro.load(settings.media_dir, mid)["saved"] == {}


def test_new_campaign_takes_voice_of_saved_intro(settings, tmp_path):
    """Голос вступления не выбран — новая кампания берёт голос сохранённого вступления и его записи, без синтеза."""
    settings, client, llm, spoken, tts = _app(settings, tmp_path)
    with client:
        client.app.state.tts.engines["gemini"]._transport = httpx.MockTransport(tts)
        admin = _login(client)
        mid = publish_sample(settings)
        master = client.app.state.master
        idle = lambda: client.portal.call(master.wait_idle, None)  # noqa: E731
        url = f"/api/admin/modules/{mid}/intro"
        mine = "Туман над склепом. Перед вами — ворота."
        ok(client.post(f"{url}/draft", json={"hook_id": "noble", "text": mine, "voice": "Kore"}, headers=admin))
        idle()
        saved = ok(client.post(f"{url}/save", headers=admin))["saved"]["noble"]
        voiced = len(spoken)

        c = party(client, admin, 0, module_id=mid)
        idle()
        assert c["settings"]["tts_intro_voice"] == "Kore"
        msgs = rows(settings, Message, Message.campaign_id == c["id"])
        intro = next(m for m in msgs if "Туман над склепом" in m.content)
        assert intro.data["voices"] == saved["voices"]
        assert not any("Туман над склепом" in x for x in spoken[voiced:])

        # свой голос вступления владельца не перебивается
        own = party(client, admin, 1, start=False, module_id=mid, tts_intro_voice="Puck")
        assert own["settings"]["tts_intro_voice"] == "Puck"


def test_saved_intro_replaces_one_prepared_by_an_older_campaign(settings, tmp_path):
    """Кампания создана до сохранения: при первом старте играет уже сохранённое вступление, голосом кампании."""
    settings, client, llm, spoken, tts = _app(settings, tmp_path)
    with client:
        client.app.state.tts.engines["gemini"]._transport = httpx.MockTransport(tts)
        admin = _login(client)
        mid = publish_sample(settings)
        master = client.app.state.master
        idle = lambda: client.portal.call(master.wait_idle, None)  # noqa: E731
        llm.replies.append({"text": STORY, "campaign_intro": True})
        c = party(client, admin, 0, start=False, module_id=mid)
        idle()  # кампания заготовила своё вступление
        url = f"/api/admin/modules/{mid}/intro"
        mine = "Туман над склепом. Перед вами — ворота."
        ok(client.post(f"{url}/draft", json={"text": mine, "voice": "Kore"}, headers=admin))
        idle()
        ok(client.post(f"{url}/save", headers=admin))
        ok(client.post(f"/api/campaigns/{c['id']}/session/start", headers=admin))
        idle()
        msgs = rows(settings, Message, Message.campaign_id == c["id"])
        assert not any("Скелеты бродят" in m.content for m in msgs)
        intro = next(m for m in msgs if "Туман над склепом" in m.content)
        # голос админа (Kore) не голос кампании (по умолчанию): текст озвучен заново для кампании
        saved = module_intro.load(settings.media_dir, mid)["saved"]["noble"]["voices"]
        assert intro.data["voices"] and intro.data["voices"] != saved
