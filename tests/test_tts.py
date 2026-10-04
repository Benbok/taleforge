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
    GeminiTTS,
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
    tts = GeminiTTS(api_key=None)
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
    tts = GeminiTTS(api_key="fake-gemini-key", model="gemini-2.0-flash", voice="Fenrir", transport=transport)

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

    tts = GeminiTTS(api_key="key-123", transport=httpx.MockTransport(mock_handler))
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

    tts = GeminiTTS(api_key="key-123", transport=httpx.MockTransport(mock_handler))
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
        gemini_tts_api_key="test-gemini-key",
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
        client.app.state.tts.engines["gemini"]._transport = httpx.MockTransport(mock_tts_handler)

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
        gemini_tts_api_key="test-gemini-key",
    )

    def mock_tts_fail(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Gemini quota exceeded")

    llm = ScriptedLLM([])

    with TestClient(create_app(settings, llm=llm, dice_factory=lambda: QueueDice([15]))) as client:
        client.app.state.tts.engines["gemini"]._transport = httpx.MockTransport(mock_tts_fail)

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
        gemini_tts_api_key="test-gemini-key",
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
        client.app.state.tts.engines["gemini"]._transport = httpx.MockTransport(mock_tts_handler)

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


def test_master_turn_uses_custom_tts_voice_from_campaign(settings, tmp_path):
    from tests.conftest import login
    from tests.game import import_base, party
    from tests.test_master import act

    import_base(settings)
    settings = dataclasses.replace(
        settings,
        media_dir=tmp_path / "media",
        gemini_tts_api_key="test-gemini-key",
        gemini_tts_voice="Fenrir",
    )

    fake_pcm = b"\x00\x00" * 24000
    b64_audio = base64.b64encode(fake_pcm).decode("ascii")

    requested_voices = []

    def mock_tts_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        v = (
            body.get("generationConfig", {})
            .get("speechConfig", {})
            .get("voiceConfig", {})
            .get("prebuiltVoiceConfig", {})
            .get("voiceName")
        )
        requested_voices.append(v)
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
        client.app.state.tts.engines["gemini"]._transport = httpx.MockTransport(mock_tts_handler)

        root = login(client, "root", "rootpass")
        client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root)
        admin = login(client, "Arty", "secret1")

        c, (p1,), ch = party(client, admin)

        # Меняем голос мастера на "Aoede" через PATCH кампании
        patch_res = client.patch(f"/api/campaigns/{c['id']}", json={"tts_voice": "Aoede"}, headers=admin)
        assert patch_res.status_code == 200
        assert patch_res.json()["settings"]["tts_voice"] == "Aoede"

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
        assert "data" in narration_msg and "voice" in narration_msg["data"]
        # Проверяем, что запрос к Gemini ушёл с голосом Aoede
        assert requested_voices == ["Aoede"]


def test_master_turn_synthesizes_voice_line_instead_of_full_narration(settings, tmp_path):
    from tests.conftest import login
    from tests.game import import_base, party
    from tests.test_master import act

    import_base(settings)
    settings = dataclasses.replace(
        settings,
        media_dir=tmp_path / "media",
        gemini_tts_api_key="test-gemini-key",
        gemini_tts_voice="Fenrir",
    )

    fake_pcm = b"\x00\x00" * 24000
    b64_audio = base64.b64encode(fake_pcm).decode("ascii")

    synthesized_texts = []

    def mock_tts_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        parts = body.get("contents", [{}])[0].get("parts", [{}])
        text = parts[0].get("text", "")
        synthesized_texts.append(text)
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

    with TestClient(create_app(settings, llm=llm, dice_factory=lambda: QueueDice([18]))) as client:
        client.app.state.tts.engines["gemini"]._transport = httpx.MockTransport(mock_tts_handler)

        root = login(client, "root", "rootpass")
        client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root)
        admin = login(client, "Arty", "secret1")

        c, (p1,), ch = party(client, admin)

        # Задаём ответы модели:
        # 1. Решение (roll_check)
        # 2. Решение (готово)
        # 3. Нарратив (длинный текст)
        # 4. Реплика голоса (короткая)
        llm.replies += [
            {
                "tool_calls": [
                    (
                        "roll_check",
                        {"character_id": ch["id"], "stat": "athletics", "difficulty": "dc.medium", "reason": "прыжок"},
                    )
                ]
            },
            {"tool_calls": []},
            {
                "text": (
                    "Длинный текст повествования: вы перепрыгиваете через пропасть, "
                    "камни срываются в бездну, свистит холодный ветер."
                )
            },
            {"text": "«Отличный прыжок, храбрец!»", "voice_line": True},
        ]

        msg = act(client, p1, c["id"], "Прыгаю через пропасть!")
        assert msg["kind"] == "narration"
        assert "Длинный текст повествования" in msg["content"]
        assert "data" in msg and "voice" in msg["data"]
        # Проверяем, что в TTS ушла короткая реплика, а не длинный нарратив
        assert synthesized_texts == ["Отличный прыжок, храбрец!"]
        assert msg["data"]["voice"]["text"] == "Отличный прыжок, храбрец!"


def test_campaign_intro_voiced_in_parts(settings, tmp_path):
    """Вступление кампании без заготовки: текст без служебного заголовка, голос всей вводной по частям,
    каждая часть отдаётся тому, кто видит сообщение."""
    from app.agents import rhythm, voiceover
    from app.db.models import Message
    from tests.conftest import login
    from tests.game import import_base, party
    from tests.test_lead import checked, set_plan
    from tests.test_master import rows

    import_base(settings)
    settings = dataclasses.replace(settings, media_dir=tmp_path / "media", gemini_tts_api_key="test-gemini-key")
    spoken: list[str] = []

    def mock_tts_handler(request: httpx.Request) -> httpx.Response:
        spoken.append(json.loads(request.content)["contents"][0]["parts"][0]["text"])
        pcm = base64.b64encode(b"\x00\x00" * 24000).decode("ascii")
        part = {"inlineData": {"mimeType": "audio/pcm;rate=24000", "data": pcm}}
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [part]}}]})

    para = "Железный Конкордат стоит серым колоссом. Его границы начертаны кровью. Дым литейных висит над шпилями. "
    story = "\n\n".join([para * 2, para, "Перед вами — тёмный коридор и мерцающий фонарь."])
    llm = ScriptedLLM([])
    with TestClient(create_app(settings, llm=llm, dice_factory=lambda: QueueDice([15]))) as client:
        client.app.state.tts.engines["gemini"]._transport = httpx.MockTransport(mock_tts_handler)
        root = login(client, "root", "rootpass")
        client.post("/api/admin/users", json={"name": "Arty", "password": "secret1"}, headers=root)
        admin = login(client, "Arty", "secret1")
        c, (p1,), _ = party(client, admin)
        cid = c["id"]
        idle = lambda: client.portal.call(client.app.state.master.wait_idle, cid)  # noqa: E731
        idle()
        set_plan(settings, cid, checked())
        llm.replies += [
            {"tool_calls": [(rhythm.NEXT_TOOL, {"hook": "Туман зовёт."})]},
            {"text": "*Масштабное вступление к кампании:*\n\n" + story, "campaign_intro": True},
            {"text": "Бран сходит на берег."},
            {"tool_calls": [(rhythm.GOAL_TOOL, {"goal": "Найти корабль."})]},
        ]
        client.post(f"/api/campaigns/{cid}/session/pause", headers=admin)
        idle()
        client.post(f"/api/campaigns/{cid}/session/start", headers=admin)
        idle()

        (intro_req,) = llm.intro_requests
        assert intro_req.get("thinking") is False  # рассуждения не съедают лимит текста
        msg = next(m for m in rows(settings, Message, Message.campaign_id == cid) if "Конкордат" in m.content)
        assert msg.content == story  # служебный заголовок модели игрокам не показан
        parts = voiceover.split(story)
        assert len(parts) > 1 and msg.data["voice_parts"] == len(parts) == len(msg.data["voices"])
        assert msg.data["voice"] == msg.data["voices"][0]
        intro_spoken = sorted(x for x in spoken if "Бран" not in x)
        assert intro_spoken == sorted(" ".join(p.split()) for p in parts)  # озвучена вся вводная
        heroes = next(m for m in rows(settings, Message, Message.campaign_id == cid) if "сходит на берег" in m.content)
        assert heroes.data["voice_parts"] == 1  # знакомство отряда — тоже часть вводной
        for v in msg.data["voices"]:
            res = client.get(f"/api/campaigns/{cid}/voice/{v['id']}", headers=p1)
            assert res.status_code == 200 and res.content.startswith(b"RIFF")
