"""Анкета кампании: чего владелец ждёт от игры (проект «Подготовка кампании», раздел 1).

Ответы хранятся в campaigns.brief. Мастер получает их текстом в системной инструкции, архитектор сюжета —
как задание на каркас кампании.
"""

from __future__ import annotations

LENGTHS = {"oneshot": "ваншот, одна сессия", "short": "короткая, 3–5 сессий", "long": "длинная, 10 и больше сессий"}
PILLARS = {
    "combat": "бои",
    "exploration": "исследование",
    "social": "общение и интриги",
    "mystery": "мистика и тайны",
    "puzzles": "головоломки",
}
AMOUNTS = {"low": "мало", "mid": "средне", "high": "много"}
EMOTIONS = {
    "heroism": "героизм",
    "fear": "страх",
    "mystery": "тайна",
    "tragedy": "трагедия",
    "humor": "юмор",
    "adventure": "приключение",
    "moral": "моральный выбор",
}
THREATS = {"personal": "личная", "regional": "город или регион", "world": "судьба мира"}
MAX_EMOTIONS = 3


def options() -> dict:
    """Варианты ответов для клиента: ключ и русская подпись."""
    return {
        "length": LENGTHS,
        "pillars": PILLARS,
        "amounts": AMOUNTS,
        "emotions": EMOTIONS,
        "threat": THREATS,
        "max_emotions": MAX_EMOTIONS,
    }


def brief_text(brief: dict | None) -> str:
    """Анкета одним абзацем для мастера. Пустая анкета — пустая строка."""
    if not brief:
        return ""
    lines = []
    if brief.get("length") in LENGTHS:
        lines.append(f"Длительность: {LENGTHS[brief['length']]}.")
    pillars = brief.get("pillars") or {}
    parts = [f"{PILLARS[k]} — {AMOUNTS[v]}" for k, v in pillars.items() if k in PILLARS and v in AMOUNTS]
    if parts:
        lines.append("Соотношение: " + ", ".join(parts) + ".")
    emotions = [EMOTIONS[e] for e in brief.get("emotions") or [] if e in EMOTIONS]
    if emotions:
        lines.append("Какие эмоции ждут игроки: " + ", ".join(emotions) + ".")
    if brief.get("threat") in THREATS:
        lines.append(f"Масштаб угрозы: {THREATS[brief['threat']]}.")
    wishes = (brief.get("wishes") or "").strip()
    if wishes:
        lines.append(f"Пожелания владельца: {wishes}")
    return "\n".join(lines)
