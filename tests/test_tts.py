"""Тесты синтеза речи мастера (Gemini TTS): очистка разметки, оборачивание PCM в WAV,
изоляция сервиса и интеграция с ходом мастера."""

import base64
import dataclasses
import json
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from app.agents.llm import ScriptedLLM
from app.agents.tts import (
    TextToSpeech,
    clean_narration_text,
    pcm_to_wav,
    wav_duration,
)
from app.core import voice
from app.main import create_app
from tests.game import QueueDice


def test_clean_narration_text():
    raw = (
        "# Вход в подземелье\n\n"
        "Перед вами [[c:orc_boss|Вождь орков]] и [[e:chest_1|Сундук]].\n\n"
        "Он кричит: *«Ни шагу дальше!»* и делает **выпад** топором."
    )
    cleaned = clean_narration_text(raw)
    assert "[[c:orc_boss|Вождь орков]]" not in cleaned
    assert "Вождь орков" in cleaned
    assert "Сундук" in cleaned
    assert "#" not in cleaned
    assert "*" not in cleaned
    assert cleaned.startswith("Вход в подземелье")


def test_pcm_to_wav_and_duration():
    # 1 секунда 24kHz 16-bit mono = 24000 * 2 = 48000 байт
    pcm = b"\x00\x00" * 24000
    wav = pcm_to_wav(pcm, sample_rate=24000)
    assert wav.startswith(b"RIFF")
    assert b"WAVE" in wav
    dur = wav_duration(wav)
    assert dur == 1.0


@pytest.mark.anyio
async def test_tts_disabled_when_no_key():
    tts = TextToSpeech(api_key=None)
    assert not tts.enabled
    res = await tts.synthesize("Привет")
    assert res is None


@pytest.mark.anyio
async def test_tts_synthesize_success():
    fake_pcm = b"\x00\x00" * 24000
    b64_audio = base64.b64encode(fake_pcm).decode("ascii")

    called_requests = []

    def mock_handler(request: httpx.Request) -> httpx.Response:
        called_requests.append(request)
        body = json.loads(request.content)
        assert body["generationConfig"]["responseModalities"] == ["AUDIO"]
        assert body["generationConfig"]["speechConfig"]["voiceConfig"]["prebuiltVoiceConfig"]["voiceName"] == "Fenrir"
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "audio/pcm;rate=24000",
                                        "data": b64_audio,
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    transport = httpx.MockTransport(mock_handler)
    tts = TextToSpeech(api_key="fake-gemini-key", model="gemini-2.0-flash", voice="Fenrir", transport=transport)

    result = await tts.synthesize("В пещере темно и сыро.")
    assert result is not None
    audio_bytes, mime, duration = result
    assert mime == "audio/wav"
    assert audio_bytes.startswith(b"RIFF")
    assert duration == 1.0
    assert len(called_requests) == 1
    assert "key=fake-gemini-key" in str(called_requests[0].url)


@pytest.mark.anyio
async def test_tts_voice_for_narration(tmp_path: Path):
    fake_pcm = b"\x00\x00" * 48000  # 2 секунды
    b64_audio = base64.b64encode(fake_pcm).decode("ascii")

    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "audio/pcm;rate=24000",
                                        "data": b64_audio,
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    tts = TextToSpeech(api_key="key-123", transport=httpx.MockTransport(mock_handler))
    media_dir = tmp_path / "media"
    campaign_id = "camp1"

    data = await tts.voice_for_narration(media_dir, campaign_id, "Текст мастера")
    assert data is not None
    assert "id" in data
    assert data["duration"] == 2.0

    # Проверяем, что файл сохранён в media_dir и читается
    meta, raw_file = voice.read(media_dir, campaign_id, data["id"])
    assert meta["user_id"] == "master"
    assert meta["mime"] == "audio/wav"
    assert raw_file.startswith(b"RIFF")


@pytest.mark.anyio
async def test_tts_api_error_returns_none():
    def mock_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    tts = TextToSpeech(api_key="key-123", transport=httpx.MockTransport(mock_handler))
    res = await tts.synthesize("Текст")
    assert res is None


def test_master_turn_attaches_voice_when_tts_enabled(settings, tmp_path):
    from tests.conftest import login
    from tests.game import import_base, party
    from tests.test_master import act

    import_base(settings)
    settings = dataclasses.replace(
        settings,
        media_dir=tmp_path / "media",
        tts_api_key="test-gemini-key",
    )

    fake_pcm = b"\x00\x00" * 24000  # 1 сек
    b64_audio = base64.b64encode(fake_pcm).decode("ascii")

    def mock_tts_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "audio/pcm;rate=24000",
                                        "data": b64_audio,
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    llm = ScriptedLLM([])

    with TestClient(create_app(settings, llm=llm, dice_factory=lambda: QueueDice([15]))) as client:
        # Подставляем mock transport в tts
        client.app.state.tts._transport = httpx.MockTransport(mock_tts_handler)

        root = login(client, "root", "rootpass")
        client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root)
        admin = login(client, "Arty", "secret1")

        c, (p1,), ch = party(client, admin)
        llm.replies += [
            {
                "tool_calls": [
                    (
                        "roll_check",
                        {"character_id": ch["id"], "stat": "athletics", "difficulty": "dc.medium", "reason": "мост"},
                    )
                ]
            },
            {"tool_calls": []},
            {"text": "Вы ступаете на скрипучие доски моста."},
        ]

        narration_msg = act(client, p1, c["id"], "Осторожно иду по мосту.")

        assert narration_msg["kind"] == "narration"
        assert "data" in narration_msg and narration_msg["data"] is not None
        assert "voice" in narration_msg["data"]
        voice_data = narration_msg["data"]["voice"]
        assert voice_data["duration"] == 1.0
        vid = voice_data["id"]

        # Проверяем, что аудио можно получить через API
        res = client.get(f"/api/campaigns/{c['id']}/voice/{vid}", headers=p1)
        assert res.status_code == 200
        assert res.headers["content-type"] == "audio/wav"
        assert res.content.startswith(b"RIFF")


def test_master_turn_succeeds_when_tts_fails(settings, tmp_path):
    from tests.conftest import login
    from tests.game import import_base, party
    from tests.test_master import act

    import_base(settings)
    settings = dataclasses.replace(
        settings,
        media_dir=tmp_path / "media",
        tts_api_key="test-gemini-key",
    )

    def mock_tts_fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Gemini quota exceeded")

    llm = ScriptedLLM([])

    with TestClient(create_app(settings, llm=llm, dice_factory=lambda: QueueDice([15]))) as client:
        client.app.state.tts._transport = httpx.MockTransport(mock_tts_fail)

        root = login(client, "root", "rootpass")
        client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root)
        admin = login(client, "Arty", "secret1")

        c, (p1,), ch = party(client, admin)
        llm.replies += [
            {
                "tool_calls": [
                    (
                        "roll_check",
                        {"character_id": ch["id"], "stat": "athletics", "difficulty": "dc.medium", "reason": "мост"},
                    )
                ]
            },
            {"tool_calls": []},
            {"text": "Эхо шагов разносится во тьме."},
        ]

        narration_msg = act(client, p1, c["id"], "Прислушиваюсь.")

        assert narration_msg["kind"] == "narration"
        # Сообщение мастера успешно отправлено, несмотря на сбой TTS
        assert narration_msg.get("data") is None or "voice" not in narration_msg.get("data", {})


def test_master_turn_skips_voice_when_tts_disabled_in_campaign(settings, tmp_path):
    from tests.conftest import login
    from tests.game import import_base, party
    from tests.test_master import act

    import_base(settings)
    settings = dataclasses.replace(
        settings,
        media_dir=tmp_path / "media",
        tts_api_key="test-gemini-key",
    )

    fake_pcm = b"\x00\x00" * 24000
    b64_audio = base64.b64encode(fake_pcm).decode("ascii")

    def mock_tts_handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "inlineData": {
                                        "mimeType": "audio/pcm;rate=24000",
                                        "data": b64_audio,
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
        )

    llm = ScriptedLLM([])

    with TestClient(create_app(settings, llm=llm, dice_factory=lambda: QueueDice([15, 18]))) as client:
        client.app.state.tts._transport = httpx.MockTransport(mock_tts_handler)

        root = login(client, "root", "rootpass")
        client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root)
        admin = login(client, "Arty", "secret1")

        c, (p1,), ch = party(client, admin)

        # Выключаем озвучку мастера через PATCH кампании
        patch_res = client.patch(f"/api/campaigns/{c['id']}", json={"tts_enabled": False}, headers=admin)
        assert patch_res.status_code == 200
        assert patch_res.json()["settings"]["tts_enabled"] is False

        llm.replies += [
            {
                "tool_calls": [
                    (
                        "roll_check",
                        {"character_id": ch["id"], "stat": "athletics", "difficulty": "dc.medium", "reason": "выступ"},
                    )
                ]
            },
            {"tool_calls": []},
            {"text": "Вы тихо крадётесь по каменному выступу."},
        ]

        narration_msg = act(client, p1, c["id"], "Иду тихо.")
        assert narration_msg["kind"] == "narration"
        # Озвучки нет, так как tts_enabled выключен в настройках кампании
        assert narration_msg.get("data") is None or "voice" not in narration_msg.get("data", {})

        # Включаем озвучку обратно
        patch_res = client.patch(f"/api/campaigns/{c['id']}", json={"tts_enabled": True}, headers=admin)
        assert patch_res.status_code == 200
        assert patch_res.json()["settings"]["tts_enabled"] is True

        llm.replies += [
            {
                "tool_calls": [
                    (
                        "roll_check",
                        {"character_id": ch["id"], "stat": "perception", "difficulty": "dc.medium", "reason": "зала"},
                    )
                ]
            },
            {"tool_calls": []},
            {"text": "Перед вами открывается просторная зала."},
        ]
        narration_msg_2 = act(client, p1, c["id"], "Осматриваюсь.")
        assert narration_msg_2["kind"] == "narration"
        assert "data" in narration_msg_2 and narration_msg_2["data"] is not None
        assert "voice" in narration_msg_2["data"]


