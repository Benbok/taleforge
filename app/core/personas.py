"""Персона ИИ-мастера: характер подачи (проект «Подготовка кампании», раздел 6).

Персона меняет только тон и манеру повествования. Механику и сложность задают правила, персона их не трогает.
Admin хранит персоны в профиле; кампания получает копию, поэтому правка персоны в профиле кампанию не меняет.
"""

from __future__ import annotations

SERIOUSNESS = {1: "комедия", 2: "с улыбкой", 3: "поровну", 4: "серьёзно", 5: "полная серьёзность"}
HUMOR = {"none": "без юмора", "dry": "сухая ирония", "light": "лёгкий юмор", "absurd": "абсурдный юмор"}
DARKNESS = {1: "светлая сказка", 2: "светлый тон", 3: "умеренная мрачность", 4: "мрачно", 5: "жёсткий гримдарк"}
VERBOSITY = {"short": "кратко, 2–3 фразы", "medium": "умеренно, один абзац", "long": "подробно, несколько абзацев"}
PACE = {"fast": "быстрый", "even": "ровный", "slow": "неторопливый"}
MANNER = {
    "narrator": "рассказчик",
    "theatrical": "театрал: голоса и прямая речь NPC",
    "chronicler": "хроникёр: взгляд со стороны, как летопись",
    "referee": "сухой рефери: факты и последствия",
}
HARSHNESS = {1: "мягкая", 2: "бережная", 3: "честная", 4: "суровая", 5: "беспощадная"}

DEFAULT = {
    "seriousness": 4,
    "humor": "dry",
    "darkness": 3,
    "verbosity": "medium",
    "pace": "even",
    "manner": "narrator",
    "harshness": 3,
    "notes": "",
}

PRESETS = [
    {
        "id": "chronicler",
        "name": "Мрачный летописец",
        "settings": {
            "seriousness": 5,
            "humor": "none",
            "darkness": 5,
            "verbosity": "long",
            "pace": "slow",
            "manner": "chronicler",
            "harshness": 4,
            "notes": "",
        },
    },
    {
        "id": "innkeeper",
        "name": "Весёлый трактирщик",
        "settings": {
            "seriousness": 2,
            "humor": "light",
            "darkness": 1,
            "verbosity": "medium",
            "pace": "fast",
            "manner": "theatrical",
            "harshness": 2,
            "notes": "",
        },
    },
    {
        "id": "storyteller",
        "name": "Рассказчик у костра",
        "settings": {**DEFAULT},
    },
    {
        "id": "referee",
        "name": "Строгий рефери",
        "settings": {
            "seriousness": 4,
            "humor": "dry",
            "darkness": 3,
            "verbosity": "short",
            "pace": "fast",
            "manner": "referee",
            "harshness": 3,
            "notes": "",
        },
    },
]


def options() -> dict:
    return {
        "seriousness": SERIOUSNESS,
        "humor": HUMOR,
        "darkness": DARKNESS,
        "verbosity": VERBOSITY,
        "pace": PACE,
        "manner": MANNER,
        "harshness": HARSHNESS,
        "default": DEFAULT,
    }


def preset(preset_id: str) -> dict | None:
    return next((p for p in PRESETS if p["id"] == preset_id), None)


def compose_style(settings: dict, extra: str | None = None) -> str:
    """Абзац стиля для системной инструкции мастера."""
    s = {**DEFAULT, **(settings or {})}
    lines = [
        f"Серьёзность: {SERIOUSNESS[s['seriousness']]}. Юмор: {HUMOR[s['humor']]}. "
        f"Мрачность: {DARKNESS[s['darkness']]}.",
        f"Описания: {VERBOSITY[s['verbosity']]}. Темп: {PACE[s['pace']]}. Манера: {MANNER[s['manner']]}.",
        f"Подача последствий: {HARSHNESS[s['harshness']]}. Это только тон: механику и сложность задают правила.",
    ]
    notes = (s.get("notes") or "").strip()
    if notes:
        lines.append(f"Своими словами: {notes}")
    if extra and extra.strip():
        lines.append(extra.strip())
    return "\n".join(lines)
