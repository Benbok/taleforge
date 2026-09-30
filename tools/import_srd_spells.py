#!/usr/bin/env python3
"""Заклинания SRD 5.1 в базовый пакет правил: content/dnd5e-srd/data/spells.yaml (kind: spell_template).

Источник чисел — 5e-bits/5e-database (раздел 2014, SRD 5.1, CC BY 4.0), копия JSON лежит в пакете мира:
content/echo-leviathans/tools/sources/5e-SRD-Spells.json. Русские имена — content/echo-leviathans/tools/
spell_names_ru.yaml, русские описания — tools/spell_texts_ru.yaml ({index: {text, higher, material}}).
Сверху — разметка механики, которую движок исполняет сам (MECHANICS ниже): состояния при провале спасброска,
эффекты-усиления, несколько лучей, автоматическое попадание, временные хиты.

Запуск из корня репозитория: python tools/import_srd_spells.py
"""

from __future__ import annotations

import json
import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
ECHO_TOOLS = ROOT / "content/echo-leviathans/tools"
OUT = ROOT / "content/dnd5e-srd/data/spells.yaml"

# Механика сверх того, что даёт база: движок исполняет эти поля в cast_spell (app/tools/spells.py).
# on_fail — состояния или эффекты цели при провале спасброска (при попадании — для атак), на время заклинания;
# effect — эффект на цели без спасброска (усиление); rays — несколько бросков атаки; auto_hit — без броска.
MECHANICS: dict[str, dict] = {
    "magic-missile": {"auto_hit": True},
    "scorching-ray": {"attack": "ranged", "rays": {"count": 3, "per_slot": 1}},
    "eldritch-blast": {"rays_by_char_level": {1: 1, 5: 2, 11: 3, 17: 4}},
    "false-life": {"heal_kind": "temp_hp"},
    "aid": {"heal_kind": "max_hp"},
    "hold-person": {"on_fail": ["paralyzed"]},
    "hold-monster": {"on_fail": ["paralyzed"]},
    "charm-person": {"on_fail": ["charmed"]},
    "dominate-person": {"on_fail": ["charmed"]},
    "dominate-beast": {"on_fail": ["charmed"]},
    "dominate-monster": {"on_fail": ["charmed"]},
    "blindness-deafness": {"on_fail": ["blinded"]},
    "entangle": {"on_fail": ["restrained"]},
    "web": {"on_fail": ["restrained"]},
    "hideous-laughter": {"on_fail": ["prone", "incapacitated"]},
    "fear": {"on_fail": ["frightened"]},
    "hypnotic-pattern": {"on_fail": ["charmed", "incapacitated"]},
    "flesh-to-stone": {"on_fail": ["restrained"]},
    "grease": {"on_fail": ["prone"]},
    "faerie-fire": {"on_fail": ["effect.spell_faerie_fire"]},
    "ray-of-sickness": {"on_fail": ["poisoned"]},
    "contagion": {"on_fail": ["poisoned"]},
    "shield": {"effect": "effect.spell_shield"},
    "shield-of-faith": {"effect": "effect.spell_shield_of_faith"},
    "mage-armor": {"effect": "effect.spell_mage_armor"},
    "blur": {"effect": "effect.spell_blur"},
    "haste": {"effect": "effect.spell_haste"},
    "stoneskin": {"effect": "effect.spell_stoneskin"},
    "barkskin": {"effect": "effect.spell_barkskin"},
    "invisibility": {"effect": "invisible"},
    "greater-invisibility": {"effect": "invisible"},
    "revivify": {"revives": True},
}


def feet(text: str | None) -> int | None:
    m = re.match(r"(\d+) feet", text or "")
    return int(m.group(1)) if m else None


def sid(index: str) -> str:
    return "spell." + index.replace("-", "_").replace("'", "")


def main() -> None:
    src = json.loads((ECHO_TOOLS / "sources/5e-SRD-Spells.json").read_text())
    names = yaml.safe_load((ECHO_TOOLS / "spell_names_ru.yaml").read_text()) or {}
    texts_path = ROOT / "tools/spell_texts_ru.yaml"
    texts = yaml.safe_load(texts_path.read_text()) if texts_path.exists() else {}
    out, missing = [], []
    for s in sorted(src, key=lambda x: (x["level"], x["index"])):
        ru = texts.get(s["index"]) or {}
        if not ru.get("text"):
            missing.append(s["index"])
        rec = {
            "id": sid(s["index"]),
            "name": names.get(s["index"]) or s["name"],
            "status": "canon",
            "doc": "SRD 5.1: Spells",
            "tags": ["spell", "srd"],
            "srd_ref": {"type": "spell", "name": s["name"]},
            "level": s["level"],
            "school": s["school"]["index"],
            "casting_time": s["casting_time"],
            "range": s["range"],
            "range_ft": feet(s["range"]),
            "components": s["components"],
            "material": s.get("material"),
            "material_ru": ru.get("material"),
            "ritual": s["ritual"],
            "concentration": s["concentration"],
            "duration": s["duration"],
            "class_refs": [f"class.{c['index']}" for c in s.get("classes", [])],
            "description": ru.get("text"),
            "higher_levels": ru.get("higher"),
            "srd_text": "\n".join(s["desc"]),
        }
        if s.get("higher_level"):
            rec["srd_text_higher"] = "\n".join(s["higher_level"])
        if s.get("attack_type"):
            rec["attack"] = s["attack_type"]
        if s.get("dc"):
            rec["save"] = {"stat": s["dc"]["dc_type"]["index"], "on_success": s["dc"].get("dc_success", "none")}
        if s.get("area_of_effect"):
            rec["area"] = {"shape": s["area_of_effect"]["type"], "size_ft": s["area_of_effect"]["size"]}
        dparts = []
        for p in s.get("damage") if isinstance(s.get("damage"), list) else ([s["damage"]] if s.get("damage") else []):
            if not p.get("damage_type"):
                continue  # «Усыпление», «Цветной шарик»: кости — запас хитов целей, а не урон
            d = {"type": p["damage_type"]["index"]}
            if p.get("damage_at_slot_level"):
                d["by_slot"] = {int(k): v for k, v in p["damage_at_slot_level"].items()}
            if p.get("damage_at_character_level"):
                d["by_char_level"] = {int(k): v for k, v in p["damage_at_character_level"].items()}
            dparts.append(d)
        if dparts:
            rec["damage"] = dparts
        if s.get("heal_at_slot_level"):
            rec["heal_by_slot"] = {int(k): v for k, v in s["heal_at_slot_level"].items()}
        rec.update(MECHANICS.get(s["index"], {}))
        out.append({k: v for k, v in rec.items() if v is not None})

    header = (
        "# Заклинания SRD 5.1: числа — из базы 5e-bits/5e-database, описания — по-русски (tools/spell_texts_ru.yaml).\n"
        "# Сгенерировано tools/import_srd_spells.py — не править руками.\n"
        "# This work includes material taken from the System Reference Document 5.1 (SRD 5.1) by Wizards of the\n"
        "# Coast LLC, licensed under CC BY 4.0: https://creativecommons.org/licenses/by/4.0/legalcode\n"
    )
    body = yaml.safe_dump({"kind": "spell_template", "items": out}, allow_unicode=True, sort_keys=False, width=120)
    OUT.write_text(header + body)
    print(f"{len(out)} заклинаний; без русского описания: {len(missing)}")
    if missing:
        print("  " + ", ".join(missing[:40]) + (" …" if len(missing) > 40 else ""))


if __name__ == "__main__":
    main()
