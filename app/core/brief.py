"""РђРЅРєРµС‚Р° РєР°РјРїР°РЅРёРё: С‡РµРіРѕ РІР»Р°РґРµР»РµС† Р¶РґС‘С‚ РѕС‚ РёРіСЂС‹ (РїСЂРѕРµРєС‚ В«РџРѕРґРіРѕС‚РѕРІРєР° РєР°РјРїР°РЅРёРёВ», СЂР°Р·РґРµР» 1).

РћС‚РІРµС‚С‹ С…СЂР°РЅСЏС‚СЃСЏ РІ campaigns.brief. РњР°СЃС‚РµСЂ РїРѕР»СѓС‡Р°РµС‚ РёС… С‚РµРєСЃС‚РѕРј РІ СЃРёСЃС‚РµРјРЅРѕР№ РёРЅСЃС‚СЂСѓРєС†РёРё, Р°СЂС…РёС‚РµРєС‚РѕСЂ СЃСЋР¶РµС‚Р° вЂ”
РєР°Рє Р·Р°РґР°РЅРёРµ РЅР° РєР°СЂРєР°СЃ РєР°РјРїР°РЅРёРё.
"""

from __future__ import annotations

LENGTHS = {"oneshot": "РІР°РЅС€РѕС‚, РѕРґРЅР° СЃРµСЃСЃРёСЏ", "short": "РєРѕСЂРѕС‚РєР°СЏ, 3вЂ“5 СЃРµСЃСЃРёР№", "long": "РґР»РёРЅРЅР°СЏ, 10 Рё Р±РѕР»СЊС€Рµ СЃРµСЃСЃРёР№"}
PILLARS = {
    "combat": "Р±РѕРё",
    "exploration": "РёСЃСЃР»РµРґРѕРІР°РЅРёРµ",
    "social": "РѕР±С‰РµРЅРёРµ Рё РёРЅС‚СЂРёРіРё",
    "mystery": "РјРёСЃС‚РёРєР° Рё С‚Р°Р№РЅС‹",
    "puzzles": "РіРѕР»РѕРІРѕР»РѕРјРєРё",
}
AMOUNTS = {"low": "РјР°Р»Рѕ", "mid": "СЃСЂРµРґРЅРµ", "high": "РјРЅРѕРіРѕ"}
EMOTIONS = {
    "heroism": "РіРµСЂРѕРёР·Рј",
    "fear": "СЃС‚СЂР°С…",
    "mystery": "С‚Р°Р№РЅР°",
    "tragedy": "С‚СЂР°РіРµРґРёСЏ",
    "humor": "СЋРјРѕСЂ",
    "adventure": "РїСЂРёРєР»СЋС‡РµРЅРёРµ",
    "moral": "РјРѕСЂР°Р»СЊРЅС‹Р№ РІС‹Р±РѕСЂ",
}
THREATS = {"personal": "Р»РёС‡РЅР°СЏ", "regional": "РіРѕСЂРѕРґ РёР»Рё СЂРµРіРёРѕРЅ", "world": "СЃСѓРґСЊР±Р° РјРёСЂР°"}
MAX_EMOTIONS = 3


def options() -> dict:
    """Р’Р°СЂРёР°РЅС‚С‹ РѕС‚РІРµС‚РѕРІ РґР»СЏ РєР»РёРµРЅС‚Р°: РєР»СЋС‡ Рё СЂСѓСЃСЃРєР°СЏ РїРѕРґРїРёСЃСЊ."""
    return {
        "length": LENGTHS,
        "pillars": PILLARS,
        "amounts": AMOUNTS,
        "emotions": EMOTIONS,
        "threat": THREATS,
        "max_emotions": MAX_EMOTIONS,
    }


def brief_text(brief: dict | None) -> str:
    """РђРЅРєРµС‚Р° РѕРґРЅРёРј Р°Р±Р·Р°С†РµРј РґР»СЏ РјР°СЃС‚РµСЂР°. РџСѓСЃС‚Р°СЏ Р°РЅРєРµС‚Р° вЂ” РїСѓСЃС‚Р°СЏ СЃС‚СЂРѕРєР°."""
    if not brief:
        return ""
    lines = []
    if brief.get("length") in LENGTHS:
        lines.append(f"Р”Р»РёС‚РµР»СЊРЅРѕСЃС‚СЊ: {LENGTHS[brief['length']]}.")
    pillars = brief.get("pillars") or {}
    parts = [f"{PILLARS[k]} вЂ” {AMOUNTS[v]}" for k, v in pillars.items() if k in PILLARS and v in AMOUNTS]
    if parts:
        lines.append("РЎРѕРѕС‚РЅРѕС€РµРЅРёРµ: " + ", ".join(parts) + ".")
    emotions = [EMOTIONS[e] for e in brief.get("emotions") or [] if e in EMOTIONS]
    if emotions:
        lines.append("РљР°РєРёРµ СЌРјРѕС†РёРё Р¶РґСѓС‚ РёРіСЂРѕРєРё: " + ", ".join(emotions) + ".")
    if brief.get("threat") in THREATS:
        lines.append(f"РњР°СЃС€С‚Р°Р± СѓРіСЂРѕР·С‹: {THREATS[brief['threat']]}.")
    wishes = (brief.get("wishes") or "").strip()
    if wishes:
        lines.append(f"РџРѕР¶РµР»Р°РЅРёСЏ РІР»Р°РґРµР»СЊС†Р°: {wishes}")
    return "\n".join(lines)
