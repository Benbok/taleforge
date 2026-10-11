"""Каналы озвучки мастера в настройках кампании.

Реплика (короткая реакция мастера на ход) и текст (весь ответ хода) включаются отдельно, у каждого свой источник
синтеза (облачный Gemini или локальный Voice Studio) и голос: ключи ``tts_line_*`` и ``tts_text_*``. Вступление,
знакомство героев и остальная подготовка к игре — свой канал ``tts_intro_*``: включается отдельно, источник всегда
облако, голос свой; не выбран — голос облачного канала кампании, иначе голос Gemini по умолчанию.

``tts_enabled`` в настройках не показывается: им старые кампании выключали весь голос мастера, и он по-прежнему
глушит все каналы. Кампании до раздельных каналов хранят только ``tts_provider`` и ``tts_voice``: реплика звучит
ими, текст выключен.
"""

from __future__ import annotations

from dataclasses import dataclass

LINE, TEXT = "line", "text"
INTRO = "intro"  # подготовка к игре: только облако
CHANNELS = (LINE, TEXT)
CLOUD = "gemini"
PROVIDERS = ("gemini", "voicestudio")
# новая кампания: реплики озвучивает локальный источник, текст выключен
DEFAULTS = {
    "tts_line_enabled": True,
    "tts_line_provider": "voicestudio",
    "tts_text_enabled": False,
    "tts_text_provider": CLOUD,
}
KEYS = (
    *(f"tts_{kind}_{field}" for kind in CHANNELS for field in ("enabled", "provider", "voice")),
    "tts_intro_enabled",
    "tts_intro_voice",
)


@dataclass(frozen=True)
class Channel:
    provider: str | None  # None — источник сервера по умолчанию
    voice: str | None  # None — голос источника по умолчанию


def _source(st: dict, kind: str) -> Channel:
    key = f"tts_{kind}_"
    if key + "provider" in st:
        return Channel(st[key + "provider"], st.get(key + "voice"))
    return Channel(st.get("tts_provider"), st.get("tts_voice"))


def channel(settings: dict | None, kind: str) -> Channel | None:
    """Источник и голос канала; None — канал выключен."""
    st = settings or {}
    if not st.get("tts_enabled", True) or not st.get(f"tts_{kind}_enabled", kind == LINE):
        return None
    return _source(st, kind)


def intro(settings: dict | None) -> Channel | None:
    """Озвучка подготовки к игре: всегда облако. Голос свой, иначе голос облачного канала кампании."""
    st = settings or {}
    if not st.get("tts_enabled", True) or not st.get("tts_intro_enabled", True):
        return None
    if st.get("tts_intro_voice"):
        return Channel(CLOUD, st["tts_intro_voice"])
    for kind in (TEXT, LINE):
        src = _source(st, kind)
        if src.provider == CLOUD and src.voice:
            return Channel(CLOUD, src.voice)
    return Channel(CLOUD, None)
