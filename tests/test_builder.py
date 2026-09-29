# ruff: noqa: F811 — фикстуры импортируются из соседних модулей
"""Живой лист конструктора (этап 7, часть 5): что получится из выбранного, не сохраняя ничего."""

from app.db.models import Character
from app.rules.dnd5e import character as rules_char
from tests.game import FIGHTER, ok, party
from tests.test_master import admin_g, dice, game_client, llm, rows  # noqa: F401 — фикстуры


def test_preview_counts_starting_gear_and_saves_nothing(game_client, admin_g, llm, settings):
    c, (p1,), hero = party(game_client, admin_g)
    before = len(rows(settings, Character))
    r = ok(game_client.post(f"/api/campaigns/{c['id']}/character-preview", headers=p1, json=FIGHTER))
    assert r["errors"] == []
    d = r["derived"]
    assert d["ac"] == 18 and d["hp_max"] == 12 and d["abilities"]["str"] == 16  # кольчуга 16 + щит, человек +1
    assert any(a["name"] == "Длинный меч" for a in d["attacks"])
    assert {"Кольчуга", "Щит"} <= {i["name"] for i in r["inventory"] if i["equipped"]}
    assert len(rows(settings, Character)) == before


def test_preview_explains_what_is_missing(game_client, admin_g, llm, settings):
    c, (p1,), _ = party(game_client, admin_g)
    bad = {**FIGHTER, "skills": ["athletics"], "abilities": {**FIGHTER["abilities"], "str": 18}}
    r = ok(game_client.post(f"/api/campaigns/{c['id']}/character-preview", headers=p1, json=bad))
    assert r["errors"] and r["derived"] is not None
    empty = ok(game_client.post(f"/api/campaigns/{c['id']}/character-preview", headers=p1, json={}))
    assert empty["derived"] is None and "нужно имя" in empty["errors"]


def test_library_preview(game_client, admin_g, llm, settings):
    r = ok(game_client.post("/api/me/character-preview", headers=admin_g, json=FIGHTER))
    assert r["errors"] == [] and r["derived"]["ac"] == 18


# --- прибавки происхождений в формате пакетов мира ---

KROVNIK = {
    "ability_bonuses": [
        {"choose": 1, "from": ["str", "con"], "value": 2},
        {"choose": 1, "from": "any", "value": 1, "distinct_from_fixed": True},
    ]
}
TUSHEVIK = {
    "ability_bonuses": [
        {"ability": "con", "value": 2},
        {"choose": 1, "from": "any", "value": 1, "distinct_from_fixed": True},
    ]
}
BASE = {"str": 15, "dex": 14, "con": 13, "int": 12, "wis": 10, "cha": 8}


def _origin_errors(origin: dict, choice: list[str]) -> list[str]:
    sheet = {"abilities": BASE, "ability_method": "standard_array", "ability_choice": choice, "level": 1}
    errs = rules_char.validate_character(sheet, None, origin, {"ability_methods": ["standard_array"]}, {})
    return [e for e in errs if e.startswith("происхождение:")]


def test_pack_origin_bonuses():
    fixed, groups = rules_char.origin_bonuses(TUSHEVIK)
    assert fixed == {"con": 2}
    assert groups[0]["count"] == 1 and "con" not in groups[0]["from"]
    abil = rules_char.final_abilities({"abilities": BASE, "ability_choice": ["dex"]}, TUSHEVIK)
    assert abil["con"] == 15 and abil["dex"] == 15

    abil = rules_char.final_abilities({"abilities": BASE, "ability_choice": ["con", "str"]}, KROVNIK)
    assert abil["con"] == 15 and abil["str"] == 16
    assert _origin_errors(KROVNIK, ["con", "str"]) == []
    assert _origin_errors(KROVNIK, ["con", "con"]) == ["происхождение: недопустимая характеристика для прибавки"]
    assert _origin_errors(KROVNIK, ["dex", "str"]) == ["происхождение: недопустимая характеристика для прибавки"]
    assert _origin_errors(KROVNIK, ["con"]) == ["происхождение: выберите характеристики для прибавки (2)"]
    assert _origin_errors(TUSHEVIK, ["con"]) == ["происхождение: недопустимая характеристика для прибавки"]


def test_srd_origin_choice_still_works():
    half_elf = {"ability_bonuses": {"cha": 2}, "ability_choose": {"count": 2, "bonus": 1, "exclude": ["cha"]}}
    abil = rules_char.final_abilities({"abilities": BASE, "ability_choice": ["str", "dex"]}, half_elf)
    assert (abil["str"], abil["dex"], abil["cha"]) == (16, 15, 10)
    assert _origin_errors(half_elf, ["cha", "dex"]) == ["происхождение: недопустимая характеристика для прибавки"]


def test_pack_class_skills_in_proficiencies():
    diagnost = {"proficiencies": {"skills_choose": {"count": 2, "from": ["arcana", "medicine"]}}}
    sc = rules_char.class_skills_choose(diagnost)
    assert sc == {"count": 2, "from": ["arcana", "medicine"]}
    assert len(rules_char.class_skills_choose({"skills_choose": {"count": 2, "from": "any"}})["from"]) == 18
