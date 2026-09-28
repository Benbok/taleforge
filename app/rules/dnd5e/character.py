"""Персонаж по SRD 5.1: способы генерации характеристик, проверка листа и производные величины (ТЗ, раздел 5.1).

Функции чистые: получают записи класса, происхождения и предметов как словари из пакета и ничего не читают сами.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any

from app.rules.dice import Dice
from app.rules.dnd5e.engine import Dnd5eEngine, RulesError
from app.rules.dnd5e.tables import ABILITIES, SKILLS

STANDARD_ARRAY = (15, 14, 13, 12, 10, 8)
POINT_BUY_BUDGET = 27
POINT_BUY_COST = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
ABILITY_METHODS = ("standard_array", "point_buy", "roll")
WEAPON_GROUPS = {
    "simple": ("simple_melee", "simple_ranged"),
    "martial": ("martial_melee", "martial_ranged"),
    "simple_melee": ("simple_melee",),
    "simple_ranged": ("simple_ranged",),
    "martial_melee": ("martial_melee",),
    "martial_ranged": ("martial_ranged",),
}

engine = Dnd5eEngine()


def roll_ability_scores(dice: Dice) -> tuple[list[int], list[list[int]]]:
    """4d6 без меньшего, шесть раз. Сервер бросает один раз и пишет броски в журнал."""
    totals, rolls = [], []
    for _ in range(6):
        r = sorted((dice.die(6) for _ in range(4)), reverse=True)
        rolls.append(r)
        totals.append(sum(r[:3]))
    return totals, rolls


def hit_die(class_data: dict) -> int:
    hd = class_data.get("hit_die")
    return int(str(hd).lstrip("d")) if hd is not None else 8


def final_abilities(sheet: dict, origin: dict | None) -> dict[str, int]:
    base = {a: int((sheet.get("abilities") or {}).get(a, 10)) for a in ABILITIES}
    if origin:
        for a, b in (origin.get("ability_bonuses") or {}).items():
            if a in base:
                base[a] += int(b)
        choose = origin.get("ability_choose")
        if choose:
            for a in sheet.get("ability_choice") or []:
                if a in base:
                    base[a] += int(choose.get("bonus", 1))
    return {a: min(20, v) for a, v in base.items()}


def _bundle(option: Any) -> list[dict]:
    if isinstance(option, dict):
        return [option]
    return [o for o in option or [] if isinstance(o, dict)]


def starting_items(class_data: dict, choices: list[dict], items: dict[str, dict]) -> tuple[list[dict], list[str]]:
    """Стартовое снаряжение класса: обязательные предметы и выбранные варианты.
    ``choices``: [{choice: i, option: j, items: [id для вариантов «любое оружие группы»]}]."""
    errors: list[str] = []
    out: list[dict] = []
    se = class_data.get("starting_equipment") or {}
    if isinstance(se, list):  # формат пакетов мира: [{choose: [...]}, "item"] — только описание
        return [], []
    for f in se.get("fixed") or []:
        if f.get("item") in items:
            out.append({"item": f["item"], "qty": int(f.get("qty", 1))})
    groups = se.get("choices") or []
    picked = {int(c.get("choice", -1)): c for c in choices or [] if isinstance(c, dict)}
    for i, alternatives in enumerate(groups):
        c = picked.get(i)
        if c is None:
            errors.append(f"снаряжение: не выбран вариант {i + 1}")
            continue
        j = int(c.get("option", -1))
        if not 0 <= j < len(alternatives):
            errors.append(f"снаряжение: в варианте {i + 1} нет пункта {j + 1}")
            continue
        extra = list(c.get("items") or [])
        for entry in _bundle(alternatives[j]):
            qty = int(entry.get("qty", 1))
            if "item" in entry:
                if entry["item"] in items:
                    out.append({"item": entry["item"], "qty": qty})
            elif "any" in entry:
                allowed = WEAPON_GROUPS.get(entry["any"], (entry["any"],))
                for _ in range(qty):
                    pick = extra.pop(0) if extra else None
                    rec = items.get(pick) if pick else None
                    if rec is None or rec.get("weapon_group") not in allowed:
                        errors.append(f"снаряжение: в варианте {i + 1} нужно оружие группы {entry['any']}")
                        break
                    out.append({"item": pick, "qty": 1})
    return out, errors


def validate_character(
    sheet: dict,
    class_data: dict | None,
    origin: dict | None,
    rules: dict,
    items: dict[str, dict],
) -> list[str]:
    """Ошибки листа по правилам. Пустой список — лист собран по правилам кампании."""
    errors: list[str] = []
    if class_data is None:
        errors.append("класс не выбран или его нет в пакете")
    if origin is None:
        errors.append("происхождение не выбрано или его нет в пакете")
    level = int(sheet.get("level") or 1)
    cap = int(rules.get("level_cap") or 20)
    if not 1 <= level <= cap:
        errors.append(f"уровень вне 1..{cap}")
    if level != int(rules.get("start_level") or 1):
        errors.append(f"стартовый уровень кампании — {rules.get('start_level') or 1}")

    method = sheet.get("ability_method")
    allowed = rules.get("ability_methods") or ["standard_array"]
    scores = sheet.get("abilities") or {}
    values = [scores.get(a) for a in ABILITIES]
    if method not in allowed:
        errors.append(f"способ характеристик кампании: {', '.join(allowed)}")
    elif any(not isinstance(v, int) for v in values):
        errors.append("нужны все шесть характеристик целыми числами")
    elif method == "standard_array" and Counter(values) != Counter(STANDARD_ARRAY):
        errors.append("стандартный набор: 15, 14, 13, 12, 10, 8 — каждое значение один раз")
    elif method == "point_buy":
        if any(v not in POINT_BUY_COST for v in values):
            errors.append("покупка очков: значения от 8 до 15")
        elif sum(POINT_BUY_COST[v] for v in values) > POINT_BUY_BUDGET:
            errors.append(f"покупка очков: не больше {POINT_BUY_BUDGET} очков")
    elif method == "roll":
        rolled = sheet.get("ability_rolls")
        if not rolled:
            errors.append("броски характеристик делает сервер: сначала бросьте")
        elif Counter(values) != Counter(rolled):
            errors.append("характеристики должны совпадать с выпавшими значениями")

    if origin and origin.get("ability_choose"):
        ch = origin["ability_choose"]
        picked = sheet.get("ability_choice") or []
        if len(picked) != int(ch.get("count", 0)) or len(set(picked)) != len(picked):
            errors.append(f"происхождение: выберите {ch.get('count')} разные характеристики")
        elif any(a not in ABILITIES or a in (ch.get("exclude") or []) for a in picked):
            errors.append("происхождение: недопустимая характеристика для прибавки")

    if class_data:
        sc = class_data.get("skills_choose") or {}
        chosen = sheet.get("skills") or []
        pool = sc.get("from") or list(SKILLS)
        if len(chosen) != int(sc.get("count", 0)) or len(set(chosen)) != len(chosen):
            errors.append(f"навыки класса: выберите {sc.get('count', 0)} разных")
        elif any(s not in pool for s in chosen):
            errors.append("навыки класса: навык не из списка класса")
        _, eq_errors = starting_items(class_data, sheet.get("equipment_choices") or [], items)
        errors += eq_errors
    return errors


@dataclass
class Attack:
    key: str
    name: str
    attack_bonus: int
    damage: str
    damage_type: str
    kind: str  # melee | ranged
    reach_ft: int = 5
    normal_ft: int | None = None
    long_ft: int | None = None
    inventory_id: str | None = None

    def as_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class Derived:
    level: int
    abilities: dict[str, int]
    mods: dict[str, int]
    pb: int
    hp_max: int
    ac: int
    speed: int
    saves: dict[str, int]
    skills: dict[str, int]
    passive_perception: int
    initiative: int
    attacks: list[Attack] = field(default_factory=list)
    resistances: list[str] = field(default_factory=list)
    senses: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict:
        d = dict(self.__dict__)
        d["attacks"] = [a.as_dict() for a in self.attacks]
        return d


def _proficient_weapon(item: dict, profs: list[str]) -> bool:
    group = item.get("weapon_group", "")
    return (
        item.get("id") in profs
        or (group.startswith("simple") and "simple" in profs)
        or (group.startswith("martial") and "martial" in profs)
    )


def weapon_attack(item: dict, mods: dict[str, int], pb: int, proficient: bool, inv_id: str | None, name: str) -> Attack:
    props = item.get("properties") or []
    ranged = item.get("weapon_group", "").endswith("ranged")
    if "finesse" in props:
        mod = max(mods["str"], mods["dex"])
    else:
        mod = mods["dex"] if ranged else mods["str"]
    dmg = item.get("damage") or {"dice": "1", "type": "bludgeoning"}
    expr = dmg["dice"] + (f"+{mod}" if mod > 0 else (f"-{-mod}" if mod < 0 else ""))
    rng = item.get("range") or {}
    return Attack(
        key=item["id"],
        name=name,
        attack_bonus=mod + (pb if proficient else 0),
        damage=expr,
        damage_type=dmg["type"],
        kind="ranged" if ranged else "melee",
        reach_ft=10 if "reach" in props else 5,
        normal_ft=rng.get("normal"),
        long_ft=rng.get("long"),
        inventory_id=inv_id,
    )


def derive(
    sheet: dict,
    class_data: dict | None,
    origin: dict | None,
    inventory: list[tuple[str, dict, bool, str]],
) -> Derived:
    """Производные величины. ``inventory``: [(inventory_id, запись предмета, надет ли, отображаемое имя)]."""
    class_data = class_data or {}
    level = int(sheet.get("level") or 1)
    abil = final_abilities(sheet, origin)
    mods = {a: engine.ability_modifier(v) for a, v in abil.items()}
    pb = engine.proficiency_bonus(level)
    hp_max = engine.hit_points_max(hit_die(class_data), mods["con"], level)

    armor = shield = None
    for _, item, equipped, _ in inventory:
        if equipped and item.get("category") == "armor":
            if item.get("armor_type") == "shield":
                shield = item
            else:
                armor = item
    shield_bonus = int(shield.get("ac_bonus", 2)) if shield else 0
    ac = engine.armor_class(mods["dex"], armor, shield_bonus)

    save_profs = set(class_data.get("saving_throws") or [])
    saves = {a: mods[a] + (pb if a in save_profs else 0) for a in ABILITIES}
    origin_skills = ((origin or {}).get("proficiencies") or {}).get("skills") or []
    skill_profs = set(sheet.get("skills") or []) | set(origin_skills)
    skills = {s: mods[a] + (pb if s in skill_profs else 0) for s, a in SKILLS.items()}

    wprofs = list(((class_data.get("proficiencies") or {}).get("weapons")) or [])
    wprofs += list((((origin or {}).get("proficiencies") or {}).get("weapons")) or [])
    attacks = [
        weapon_attack(item, mods, pb, _proficient_weapon(item, wprofs), inv_id, name)
        for inv_id, item, _, name in inventory
        if item.get("category") == "weapon"
    ]
    attacks.append(
        Attack("unarmed", "Безоружный удар", mods["str"] + pb, str(max(1, 1 + mods["str"])), "bludgeoning", "melee")
    )
    senses = {}
    if (origin or {}).get("darkvision"):
        senses["darkvision"] = int(origin["darkvision"])
    return Derived(
        level=level,
        abilities=abil,
        mods=mods,
        pb=pb,
        hp_max=hp_max,
        ac=ac,
        speed=int((origin or {}).get("speed") or 30),
        saves=saves,
        skills=skills,
        passive_perception=10 + skills["perception"],
        initiative=mods["dex"],
        attacks=attacks,
        resistances=list((origin or {}).get("damage_resistances") or []),
        senses=senses,
    )


def creation_options(classes: list[dict], origins: list[dict], rules: dict) -> dict:
    return {
        "ability_methods": rules.get("ability_methods") or ["standard_array"],
        "standard_array": list(STANDARD_ARRAY),
        "point_buy": {"budget": POINT_BUY_BUDGET, "cost": POINT_BUY_COST},
        "start_level": int(rules.get("start_level") or 1),
        "skills": SKILLS,
        "classes": classes,
        "origins": origins,
    }


__all__ = [
    "ABILITY_METHODS",
    "Attack",
    "Derived",
    "RulesError",
    "creation_options",
    "derive",
    "roll_ability_scores",
    "starting_items",
    "validate_character",
]
