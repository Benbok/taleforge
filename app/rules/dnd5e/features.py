"""Умения классов SRD 5.1 на уровне героя (просьба Arty 2026-10-06: «есть ли способности для не магов героев»).

Чистые функции: какие умения герой уже получил, их русские имена и числа из таблицы класса (кость скрытой атаки,
урон ярости, кость боевых искусств), выборы класса (боевой стиль, компетентность) и формы Дикого облика.
Мастер видит этот список в листе героя; сервер по нему считает КД, скорость, навыки и боевые прибавки.
"""

from __future__ import annotations

import re
from typing import Any

# Не умения, а выбор или заголовки: заклинательство показано строкой книги заклинаний, подклассы героям пока не
# выбираются, увеличение характеристик ещё не делается при росте уровня, стиль боя и компетентность — своими полями.
SKIP = re.compile(
    r"(^spellcasting(_|$)|^pact_magic$|ability_score_improvement|^specialization|_improvement_\d+$|^primal_path$|^martial_archetype$|"
    r"^roguish_archetype$|^monastic_tradition$|^sacred_oath$|^ranger_archetype$|^bard_college$|^divine_domain$|"
    r"^druid_circle$|^sorcerous_origin$|^otherworldly_patron$|^arcane_tradition$|^domain_spells_|^oath_spells$|"
    r"^pact_boon$|_fighting_style$|_expertise_\d+$|^metamagic_(?!\d))"
)

# Стили боя SRD: ключ варианта без префикса класса → имя и что даёт.
FIGHTING_STYLES: dict[str, tuple[str, str]] = {
    "archery": ("Стрельба", "+2 к броскам атаки дальнобойным оружием."),
    "defense": ("Оборона", "+1 к КД, пока на герое доспех."),
    "dueling": ("Дуэль", "+2 к урону оружием в одной руке, если в другой нет оружия."),
    "great_weapon_fighting": (
        "Сражение большим оружием",
        "1 или 2 на кости урона двуручного или полуторного оружия в двух руках можно перебросить.",
    ),
    "protection": (
        "Защита",
        "Реакцией со щитом: помеха на атаку по союзнику в 5 футах от героя.",
    ),
    "two_weapon_fighting": (
        "Сражение двумя оружиями",
        "Удар второй рукой получает модификатор характеристики к урону.",
    ),
}

SEE_DESCRIPTION = 400  # столько знаков описания SRD уходит мастеру в листе героя


def owned(class_data: dict, level: int) -> set[str]:
    """Ключи умений, полученных к уровню (по таблице уровней класса)."""
    out: set[str] = set()
    for row in class_data.get("levels") or []:
        if isinstance(row, dict) and int(row.get("level", 99)) <= level:
            out |= set(row.get("features") or [])
    return out


def numbers(class_data: dict, level: int) -> dict[str, Any]:
    """Числа класса из таблицы на уровне героя: ``sneak_attack``, ``rage_damage_bonus``, ``martial_arts``…"""
    rows = [r for r in class_data.get("levels") or [] if isinstance(r, dict) and int(r.get("level", 99)) <= level]
    return dict((max(rows, key=lambda r: int(r["level"])) if rows else {}).get("class_specific") or {})


def has(keys: set[str] | frozenset[str], *prefixes: str) -> bool:
    return any(k.startswith(p) for k in keys for p in prefixes)


def times(n: int) -> str:
    """«1 раз», «2 раза», «5 раз»."""
    if n % 10 in (2, 3, 4) and n % 100 not in (12, 13, 14):
        return f"{n} раза"
    return f"{n} раз"


def _detail(key: str, nums: dict[str, Any], level: int) -> str:
    """Число умения на этом уровне, если таблица класса его знает."""
    if key == "sneak_attack" and nums.get("sneak_attack"):
        return str(nums["sneak_attack"])
    if key == "rage":
        n, dmg = nums.get("rage_count"), nums.get("rage_damage_bonus")
        return f"урон +{dmg}" + (f", {times(int(n))} до долгого отдыха" if n and int(n) < 9999 else ", без ограничений")
    if key.startswith("brutal_critical") and nums.get("brutal_critical_dice"):
        return f"+{nums['brutal_critical_dice']} к костям оружия при крите"
    if key == "martial_arts" and nums.get("martial_arts"):
        return f"кость {nums['martial_arts']}"
    if key == "ki" and nums.get("ki_points"):
        return f"{nums['ki_points']} очков"
    if key.startswith("unarmored_movement") and nums.get("unarmored_movement"):
        return f"+{nums['unarmored_movement']} фт"
    if key.startswith("bardic_inspiration"):
        return key.rsplit("_", 1)[-1]
    if key.startswith("song_of_rest"):
        return key.rsplit("_", 1)[-1]
    if key == "lay_on_hands":
        return f"запас {5 * level} хитов"
    if key.startswith("action_surge") and nums.get("action_surges"):
        return times(int(nums["action_surges"]))
    if key.startswith("indomitable") and not key.startswith("indomitable_might") and nums.get("indomitable_uses"):
        return times(int(nums["indomitable_uses"]))
    if key.startswith("extra_attack") or key.endswith("_extra_attack"):
        n = int(nums.get("extra_attacks") or 1)
        return f"{n + 1} удара за действие «Атака»"
    if key.startswith("wild_shape"):
        return wild_shape_rules(level)["text"]
    return ""


def class_features(class_data: dict, level: int, sheet: dict | None = None) -> list[dict[str, Any]]:
    """Умения героя на его уровне для мастера: имя по-русски, уровень, число на уровне и текст SRD.
    Ступени одного умения («Дополнительная атака (2)», «Вдохновение барда (d8)») сливаются в одну запись."""
    have = owned(class_data, level)
    nums = numbers(class_data, level)
    by_key = {str(f.get("key")): f for f in class_data.get("features") or [] if isinstance(f, dict)}
    out: dict[str, dict[str, Any]] = {}
    for key in sorted(have, key=lambda k: (int((by_key.get(k) or {}).get("level") or 0), k)):
        if SKIP.search(key):
            continue
        f = by_key.get(key) or {}
        name = str(f.get("name_ru") or f.get("name") or key)
        text = str(f.get("description") or "").strip()
        if len(text) > SEE_DESCRIPTION:
            text = text[:SEE_DESCRIPTION].rsplit(" ", 1)[0] + "…"
        row = {"key": key, "name": name, "level": int(f.get("level") or 1), "text": text, **player_texts(f, name)}
        detail = _detail(key, nums, level)
        if detail:
            row["detail"] = detail
        out[name] = {**row, "level": out.get(name, row)["level"]}
    rows = list(out.values())
    sheet = sheet or {}
    style = fighting_style_options(class_data, level)
    if style:
        pick = sheet.get("fighting_style")
        if pick in style:
            name, text = FIGHTING_STYLES[pick]
            rows.append(
                {"key": f"fighting_style_{pick}", "name": f"Боевой стиль: {name}", "level": 1, "text": text,
                 "text_ru": text, "mode": "master" if pick in ("great_weapon_fighting", "protection") else "auto"}
            )  # fmt: skip
        else:
            rows.append(
                {
                    "key": "fighting_style",
                    "name": "Боевой стиль",
                    "level": 1,
                    "text": "",
                    "detail": "не выбран",
                    "text_ru": "Стиль ещё не выбран: назовите мастеру один из стилей класса.",
                    "mode": "master",
                }
            )
    need = expertise_count(class_data, level)
    if need:
        got = [s for s in sheet.get("expertise") or [] if isinstance(s, str)][:need]
        rows.append(
            {
                "key": "expertise",
                "name": "Компетентность",
                "level": 1,
                "text": "Удвоенный бонус мастерства к проверкам выбранных навыков.",
                "text_ru": "Удвоенный бонус мастерства к проверкам выбранных навыков.",
                "mode": "auto",
                "skills": got,
                "detail": ", ".join(got) + ("" if len(got) == need else f" (не выбрано: {need - len(got)})")
                if got
                else f"не выбрано: {need}",
            }
        )
    return rows


def player_texts(f: dict, name: str) -> dict[str, str]:
    """Тексты умения для игрока: что даёт, как применить, кто исполняет и фраза для заявки. Умения пакетов мира
    без этих полей пишут описание по-русски — оно и идёт игроку; заявляются те, у которых есть действие."""
    mode = f.get("mode")
    if mode not in ("auto", "declare", "master"):
        mode = "declare" if f.get("action") else "master"
    out = {"mode": mode}
    desc = str(f.get("description") or "")
    text = f.get("text_ru") or (desc if re.search("[а-яё]", desc, re.I) else "")
    if text:
        out["text_ru"] = str(text)
    if f.get("how_ru"):
        out["how"] = str(f["how_ru"])
    if mode == "declare":
        out["say"] = str(f.get("say") or name)
    return out


def fighting_style_options(class_data: dict, level: int) -> list[str]:
    """Стили боя, из которых герой выбирает на этом уровне (пусто — стиля у класса пока нет)."""
    have = owned(class_data, level)
    heads = [k for k in have if k.endswith("_fighting_style")]
    if not heads:
        return []
    out = []
    for f in class_data.get("features") or []:
        if isinstance(f, dict) and f.get("parent") in heads:
            m = re.search(r"fighting_style_(\w+)$", str(f.get("key")))
            if m and m.group(1) in FIGHTING_STYLES and m.group(1) not in out:
                out.append(m.group(1))
    return out


def expertise_count(class_data: dict, level: int) -> int:
    """Сколько навыков с компетентностью у героя: по два за каждое умение «Компетентность»."""
    return 2 * sum(1 for k in owned(class_data, level) if re.search(r"_expertise_\d+$", k))


def summary(rows: list[dict[str, Any]]) -> str:
    """Короткая строка умений для таблицы сцены."""
    return ", ".join(r["name"] + (f" ({r['detail']})" if r.get("detail") else "") for r in rows)


# --- Дикий облик (SRD 5.1, Druid: Wild Shape) ---


def wild_shape_rules(level: int) -> dict[str, Any]:
    """Предел формы по уровню друида: наибольший ПО и запрет полёта или плавания."""
    if level >= 8:
        return {"max_cr": 1.0, "fly": True, "swim": True, "text": "звери с ПО до 1"}
    if level >= 4:
        return {"max_cr": 0.5, "fly": False, "swim": True, "text": "звери с ПО до 1/2, без полёта"}
    return {"max_cr": 0.25, "fly": False, "swim": False, "text": "звери с ПО до 1/4, без полёта и плавания"}


def _cr(v: Any) -> float:
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v or "").strip()
    if "/" in s:
        a, b = s.split("/", 1)
        return int(a) / int(b)
    try:
        return float(s)
    except ValueError:
        return 99.0


def wild_shape_forms(level: int, beasts: list[tuple[str, str, dict]]) -> list[dict[str, Any]]:
    """Звери бестиария, в которых друид может обернуться: ``beasts`` — [(id, имя, данные шаблона)]."""
    r = wild_shape_rules(level)
    out = []
    for bid, name, d in beasts:
        if d.get("creature_type") != "beast" and "beast" not in (d.get("tags") or []):
            continue
        cr = _cr(d.get("cr"))
        speed = d.get("speed") or {}
        speed = speed if isinstance(speed, dict) else {}
        if cr > r["max_cr"] or (speed.get("fly") and not r["fly"]) or (speed.get("swim") and not r["swim"]):
            continue
        out.append({"id": bid, "name": name, "cr": d.get("cr")})
    out.sort(key=lambda x: (_cr(x["cr"]), x["name"]))
    return out
