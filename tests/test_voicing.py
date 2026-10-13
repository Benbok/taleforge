"""Каналы озвучки мастера: реплика и текст настраиваются отдельно, подготовка к игре всегда в облаке."""

from app.agents import voicing
from app.agents.voicing import Channel
from app.core.campaigns import DEFAULT_SETTINGS


def test_new_campaign_voices_line_locally_and_keeps_text_silent():
    assert voicing.channel(DEFAULT_SETTINGS, voicing.LINE) == Channel("voicestudio", None)
    assert voicing.channel(DEFAULT_SETTINGS, voicing.TEXT) is None


def test_channels_have_own_provider_and_voice():
    st = {
        "tts_line_provider": "voicestudio",
        "tts_line_voice": "clone01",
        "tts_text_enabled": True,
        "tts_text_provider": "gemini",
        "tts_text_voice": "Aoede",
    }
    assert voicing.channel(st, voicing.LINE) == Channel("voicestudio", "clone01")
    assert voicing.channel(st, voicing.TEXT) == Channel("gemini", "Aoede")
    assert voicing.channel({**st, "tts_line_enabled": False}, voicing.LINE) is None


def test_master_switch_silences_every_channel():
    st = {"tts_enabled": False, "tts_text_enabled": True}
    assert voicing.channel(st, voicing.LINE) is None
    assert voicing.channel(st, voicing.TEXT) is None
    assert voicing.intro(st) is None


def test_campaign_before_channels_keeps_line_voice_and_text_off():
    st = {"tts_enabled": True, "tts_provider": "gemini", "tts_voice": "Kore"}
    assert voicing.channel(st, voicing.LINE) == Channel("gemini", "Kore")
    assert voicing.channel(st, voicing.TEXT) is None


def test_intro_always_cloud_with_cloud_channel_voice():
    assert voicing.intro({"tts_line_provider": "voicestudio", "tts_line_voice": "clone01"}) == Channel("gemini", None)
    st = {
        "tts_line_provider": "gemini",
        "tts_line_voice": "Puck",
        "tts_text_provider": "gemini",
        "tts_text_voice": "Aoede",
    }
    assert voicing.intro(st) == Channel("gemini", "Aoede")  # голос текста ближе к вступлению, чем голос реплики


def test_intro_has_own_switch_and_voice():
    assert voicing.intro({"tts_intro_enabled": False}) is None
    st = {"tts_intro_voice": "Charon", "tts_text_provider": "gemini", "tts_text_voice": "Aoede"}
    assert voicing.intro(st) == Channel("gemini", "Charon")
