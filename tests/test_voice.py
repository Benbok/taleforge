"""Голосовые реплики: запись хранится на сервере, расшифровывает её локальная модель, дальше реплика идёт
как обычная — с теми же проверками и видимостью. Запросы к модели встают в очередь, ошибки — по-русски."""

import asyncio
import dataclasses

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents.llm import ScriptedLLM
from app.agents.stt import SpeechToText, STTError
from app.main import create_app
from tests.conftest import login
from tests.game import QueueDice, import_base, ok, party
from tests.test_ws import connect

AUDIO = b"OggS-fake-opus-audio"


def fake_server(seen: list, text: str = "Я открываю дверь.", status: int = 200):
    def handle(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if status != 200:
            return httpx.Response(status, text="boom")
        return httpx.Response(200, json={"text": f" {text} "})

    return httpx.MockTransport(handle)


@pytest.fixture
def seen():
    return []


@pytest.fixture
def client(settings, tmp_path, seen):
    import_base(settings)
    settings = dataclasses.replace(settings, media_dir=tmp_path / "media")
    with TestClient(create_app(settings, llm=ScriptedLLM([]), dice_factory=lambda: QueueDice([]))) as c:
        c.app.state.master.notify = lambda cid: None
        c.app.state.stt = SpeechToText("http://stt:8000/v1/", "whisper-turbo", transport=fake_server(seen))
        yield c


@pytest.fixture
def admin(client):
    root = login(client, "root", "rootpass")
    ok(client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root), 201)
    return login(client, "Arty", "secret1")


def upload(client, headers, cid, audio=AUDIO, ctype="audio/webm;codecs=opus"):
    return client.post(f"/api/campaigns/{cid}/voice", content=audio, headers={**headers, "Content-Type": ctype})


def say_voice(ws, voice_id, kind="auto"):
    ws.send_json({"type": "message.send", "payload": {"kind": kind, "voice": voice_id, "duration": 3.4}})
    for _ in range(20):
        e = ws.receive_json()
        if e["type"] in ("message.new", "message.rejected"):
            return e
    raise AssertionError("нет ответа на реплику")


def test_voice_message_carries_transcript_and_clip(client, admin, seen):
    c, (p1, p2), _ = party(client, admin, players=2)
    assert ok(client.get("/api/voice", headers=p1)) == {"enabled": True}
    vid = ok(upload(client, p1, c["id"]), 201)["voice_id"]
    with connect(client, p1, c["id"]) as (ws, _):
        e = say_voice(ws, vid)
    assert e["type"] == "message.new", e
    m = e["payload"]
    assert m["content"] == "Я открываю дверь." and m["kind"] == "action"
    assert m["data"]["voice"] == {"id": vid, "mime": "audio/webm", "duration": 3.4}
    req = seen[0]
    assert str(req.url) == "http://stt:8000/v1/audio/transcriptions"
    assert b"whisper-turbo" in req.content and b'name="language"' in req.content and AUDIO in req.content
    # запись слышат все, кто видит сообщение, — и мастер тоже
    for who in (p1, p2, admin):
        r = client.get(f"/api/campaigns/{c['id']}/voice/{vid}", headers=who)
        assert r.status_code == 200 and r.content == AUDIO and r.headers["content-type"] == "audio/webm"


def test_whispered_voice_heard_only_by_author_and_master(client, admin):
    c, (p1, p2), _ = party(client, admin, players=2, master={"type": "owner"})
    vid = ok(upload(client, p1, c["id"]), 201)["voice_id"]
    with connect(client, p1, c["id"]) as (ws, _):
        e = say_voice(ws, vid, kind="whisper")
    assert e["type"] == "message.new" and e["payload"]["whisper"]
    assert client.get(f"/api/campaigns/{c['id']}/voice/{vid}", headers=p1).status_code == 200
    assert client.get(f"/api/campaigns/{c['id']}/voice/{vid}", headers=admin).status_code == 200
    assert client.get(f"/api/campaigns/{c['id']}/voice/{vid}", headers=p2).status_code == 404


def test_unsent_or_foreign_recording(client, admin):
    c, (p1, p2), _ = party(client, admin, players=2)
    vid = ok(upload(client, p1, c["id"]), 201)["voice_id"]
    # пока запись не отправлена в чат, слушать нечего
    assert client.get(f"/api/campaigns/{c['id']}/voice/{vid}", headers=p1).status_code == 404
    with connect(client, p2, c["id"]) as (ws, _):
        e = say_voice(ws, vid)
    assert e["type"] == "message.rejected" and e["payload"]["reason"] == "это чужая запись"
    with connect(client, p1, c["id"]) as (ws, _):
        e = say_voice(ws, "v0000000000000000")
    assert e["type"] == "message.rejected" and "запись не найдена" in e["payload"]["reason"]
    assert upload(client, p1, c["id"], ctype="text/plain").status_code == 409
    stranger = ok(client.post("/api/auth/signup", json={"name": "Чужой", "password": "pass123"}))
    assert upload(client, {"Authorization": f"Bearer {stranger['token']}"}, c["id"]).status_code == 404


def test_failed_transcription_is_explained(client, admin):
    c, (p1,), _ = party(client, admin)
    client.app.state.stt = SpeechToText("http://stt/v1", "whisper-turbo", transport=fake_server([], status=404))
    vid = ok(upload(client, p1, c["id"]), 201)["voice_id"]
    with connect(client, p1, c["id"]) as (ws, _):
        e = say_voice(ws, vid)
        assert e["type"] == "message.rejected"
        assert e["payload"]["reason"].startswith("голосовое не расшифровано: сервер расшифровки не знает модель")
        client.app.state.stt = SpeechToText("http://stt/v1", "m", transport=fake_server([], text=""))
        e = say_voice(ws, vid)
        assert e["payload"]["reason"].startswith("речь не распознана")


def test_rejected_voice_returns_transcript(client, admin):
    """Реплику не приняли (первая ещё ждёт мастера): расшифровка возвращается в поле, чтобы не диктовать заново."""
    c, (p1,), _ = party(client, admin)
    with connect(client, p1, c["id"]) as (ws, _):
        assert say_voice(ws, ok(upload(client, p1, c["id"]), 201)["voice_id"])["type"] == "message.new"
        e = say_voice(ws, ok(upload(client, p1, c["id"]), 201)["voice_id"])
    assert e["type"] == "message.rejected" and e["payload"]["text"] == "Я открываю дверь."


def test_voice_off_without_address(client, admin):
    c, (p1,), _ = party(client, admin)
    client.app.state.stt = SpeechToText(None, "m")
    assert ok(client.get("/api/voice", headers=p1)) == {"enabled": False}
    r = upload(client, p1, c["id"])
    assert r.status_code == 409 and "STT_API_BASE" in r.json()["detail"]


def test_admin_status_and_check(client, admin, seen):
    player = ok(client.post("/api/auth/signup", json={"name": "Гимли", "password": "pass123"}))
    assert client.get("/api/admin/voice", headers={"Authorization": f"Bearer {player['token']}"}).status_code == 403
    st = ok(client.get("/api/admin/voice", headers=admin))
    assert st["enabled"] and st["model"] == "whisper-turbo" and st["api_base"] == "http://stt:8000/v1"
    c = ok(client.post("/api/admin/voice/check", headers=admin))
    assert c["ok"] and c["latency_ms"] >= 0
    assert b"RIFF" in seen[0].content  # проверка шлёт секунду тишины в WAV
    assert ok(client.get("/api/admin/voice", headers=admin))["last_check"]["ok"]

    def down(request):
        raise httpx.ConnectError("refused")

    client.app.state.stt = SpeechToText("http://stt:8000/v1", "m", transport=httpx.MockTransport(down))
    c = ok(client.post("/api/admin/voice/check", headers=admin))
    assert not c["ok"] and "не отвечает: он запущен?" in c["error"]


def test_one_recording_at_a_time():
    """Одна видеокарта — одна расшифровка за раз: остальные ждут в очереди, а не падают."""
    running = 0
    peak = 0

    async def handle(request):
        nonlocal running, peak
        running += 1
        peak = max(peak, running)
        await asyncio.sleep(0.02)
        running -= 1
        return httpx.Response(200, json={"text": "ок"})

    stt = SpeechToText("http://stt/v1", "m", transport=httpx.MockTransport(handle))

    async def main():
        return await asyncio.gather(*(stt.transcribe(b"x", "audio/webm") for _ in range(4)))

    results = asyncio.run(main())
    assert peak == 1 and stt.waiting == 0
    assert max(r["queued_ms"] for r in results) >= 40


def test_disabled_raises():
    with pytest.raises(STTError):
        asyncio.run(SpeechToText(None, "m").transcribe(b"x"))
