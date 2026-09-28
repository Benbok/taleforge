#!/usr/bin/env python3
"""Импорт заклинаний SRD 5.1 в data/spells/srd.yaml (kind: spell_template).

Источник: tools/sources/5e-SRD-Spells.json (5e-bits/5e-database, раздел 2014; содержимое — SRD 5.1, CC BY 4.0).
Русские названия: tools/spell_names_ru.yaml ({index: "Название"}). Без перевода — английское имя и тег needs_ru_name.
Заклинания 9-го круга импортируются, но недоступны героям (канон: 9-й круг — сила матерей и Кормчих).
"""

import json
import pathlib
import re

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
src = json.loads((ROOT / "tools/sources/5e-SRD-Spells.json").read_text())
names_path = ROOT / "tools/spell_names_ru.yaml"
names = yaml.safe_load(names_path.read_text()) if names_path.exists() else {}


def feet(text):
    m = re.match(r"(\d+) feet", text or "")
    return int(m.group(1)) if m else None


def sid(index):
    return "spell." + index.replace("-", "_").replace("'", "")


out = []
for s in sorted(src, key=lambda x: (x["level"], x["index"])):
    ru = (names or {}).get(s["index"])
    rec = {
        "id": sid(s["index"]),
        "name": ru or s["name"],
        "status": "canon",
        "doc": "SRD 5.1",
        "tags": ["srd"] + ([] if ru else ["needs_ru_name"]),
        "srd_ref": {"type": "spell", "name": s["name"]},
        "level": s["level"],
        "school": s["school"]["index"],
        "casting_time": s["casting_time"],
        "range": s["range"],
        "range_ft": feet(s["range"]),
        "components": s["components"],
        "material": s.get("material"),
        "ritual": s["ritual"],
        "concentration": s["concentration"],
        "duration": s["duration"],
        "class_refs": [f"class.{c['index']}" for c in s.get("classes", [])],
        "player_available": s["level"] <= 8,
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
    dmg = s.get("damage")
    parts = dmg if isinstance(dmg, list) else ([dmg] if dmg else [])
    dparts = []
    for p in parts:
        d = {}
        if p.get("damage_type"):
            d["type"] = p["damage_type"]["index"]
        if p.get("damage_at_slot_level"):
            d["by_slot"] = {int(k): v for k, v in p["damage_at_slot_level"].items()}
        if p.get("damage_at_character_level"):
            d["by_char_level"] = {int(k): v for k, v in p["damage_at_character_level"].items() if int(k) <= 15}
        if d:
            dparts.append(d)
    if dparts:
        rec["damage"] = dparts
    if s.get("heal_at_slot_level"):
        rec["heal_by_slot"] = {int(k): v for k, v in s["heal_at_slot_level"].items()}
    rec = {k: v for k, v in rec.items() if v is not None}
    out.append(rec)

header = (
    "# Сгенерировано tools/import_srd_spells.py — не править руками.\n"
    "# This work includes material taken from the System Reference Document 5.1 (SRD 5.1)\n"
    "# by Wizards of the Coast LLC,\n"
    "# licensed under CC BY 4.0: https://creativecommons.org/licenses/by/4.0/legalcode\n"
)
(ROOT / "data/spells/srd.yaml").write_text(
    header + yaml.safe_dump({"kind": "spell_template", "items": out}, allow_unicode=True, sort_keys=False, width=120)
)
print(len(out), "spells;", sum(1 for r in out if "needs_ru_name" in r["tags"]), "without ru name")
