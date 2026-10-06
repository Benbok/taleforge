"""Умения классов SRD 5.1 на уровне героя (просьба Arty 2026-10-06: «есть ли способности для не магов героев»).

Чистые функции: какие умения герой уже получил, их русские имена и числа из таблицы класса (кость скрытой атаки,
урон ярости, кость боевых искусств), выборы класса (боевой стиль, компетентность) и формы Дикого облика.
Мастер видит этот список в листе героя; сервер по нему считает КД, скорость, навыки и боевые прибавки.
"""

from __future__ import annotations

import re
from typing import Any

# Имена умений по-русски. Ключ — начало ключа умения в данных SRD: «extra_attack_2» и «monk_extra_attack» найдут
# свою запись. Порядок важен: более точный ключ раньше общего.
RU_NAMES: tuple[tuple[str, str], ...] = (
    ("barbarian_unarmored_defense", "Защита без доспехов"),
    ("monk_unarmored_defense", "Защита без доспехов"),
    ("rage", "Ярость"),
    ("danger_sense", "Чувство опасности"),
    ("reckless_attack", "Безрассудная атака"),
    ("fast_movement", "Быстрое передвижение"),
    ("feral_instinct", "Дикий инстинкт"),
    ("brutal_critical", "Сильный критический удар"),
    ("relentless_rage", "Непреклонная ярость"),
    ("persistent_rage", "Непрерывная ярость"),
    ("indomitable_might", "Неукротимая мощь"),
    ("primal_champion", "Первобытный чемпион"),
    ("barbarian_extra_attack", "Дополнительная атака"),
    ("monk_extra_attack", "Дополнительная атака"),
    ("paladin_extra_attack", "Дополнительная атака"),
    ("ranger_extra_attack", "Дополнительная атака"),
    ("extra_attack", "Дополнительная атака"),
    ("bardic_inspiration", "Вдохновение барда"),
    ("jack_of_all_trades", "Мастер на все руки"),
    ("song_of_rest", "Песнь отдыха"),
    ("font_of_inspiration", "Источник вдохновения"),
    ("countercharm", "Контрочарование"),
    ("magical_secrets", "Тайны магии"),
    ("superior_inspiration", "Превосходное вдохновение"),
    ("channel_divinity_turn_undead", "Божественный канал: изгнание нежити"),
    ("channel_divinity", "Божественный канал"),
    ("destroy_undead", "Уничтожение нежити"),
    ("divine_intervention_improvement", "Божественное вмешательство (улучшенное)"),
    ("divine_intervention", "Божественное вмешательство"),
    ("supreme_healing", "Высшее исцеление"),
    ("druidic", "Друидический язык"),
    ("wild_shape", "Дикий облик"),
    ("beast_spells", "Звериные заклинания"),
    ("druid_timeless_body", "Безвременное тело"),
    ("monk_timeless_body", "Безвременное тело"),
    ("archdruid", "Архидруид"),
    ("second_wind", "Второе дыхание"),
    ("action_surge", "Всплеск действий"),
    ("indomitable", "Упорный"),
    ("martial_arts", "Боевые искусства"),
    ("ki_empowered_strikes", "Удары, усиленные ци"),
    ("ki", "Ци"),
    ("flurry_of_blows", "Шквал ударов"),
    ("patient_defense", "Терпеливая оборона"),
    ("step_of_the_wind", "Поступь ветра"),
    ("unarmored_movement", "Движение без доспехов"),
    ("deflect_missiles", "Отражение снарядов"),
    ("slow_fall", "Замедленное падение"),
    ("stunning_strike", "Оглушающий удар"),
    ("monk_evasion", "Увёртливость"),
    ("rogue_evasion", "Увёртливость"),
    ("stillness_of_mind", "Спокойствие разума"),
    ("purity_of_body", "Чистота тела"),
    ("tongue_of_the_sun_and_moon", "Язык солнца и луны"),
    ("diamond_soul", "Алмазная душа"),
    ("empty_body", "Пустое тело"),
    ("perfect_self", "Совершенство"),
    ("divine_sense", "Божественное чувство"),
    ("lay_on_hands", "Наложение рук"),
    ("improved_divine_smite", "Улучшенная божественная кара"),
    ("divine_smite", "Божественная кара"),
    ("divine_health", "Божественное здоровье"),
    ("aura_of_protection", "Аура защиты"),
    ("aura_of_courage", "Аура отваги"),
    ("aura_improvements", "Улучшенные ауры"),
    ("cleansing_touch", "Очищающее касание"),
    ("favored_enemy", "Избранный враг"),
    ("natural_explorer", "Исследователь природы"),
    ("primeval_awareness", "Первозданная осведомлённость"),
    ("ranger_lands_stride", "Тропы земли"),
    ("hide_in_plain_sight", "Маскировка на виду"),
    ("vanish", "Исчезновение"),
    ("feral_senses", "Дикие чувства"),
    ("foe_slayer", "Убийца врагов"),
    ("sneak_attack", "Скрытая атака"),
    ("thieves_cant", "Воровской жаргон"),
    ("cunning_action", "Хитрое действие"),
    ("uncanny_dodge", "Невероятное уклонение"),
    ("reliable_talent", "Надёжный талант"),
    ("blindsense", "Слепое зрение"),
    ("slippery_mind", "Скользкий разум"),
    ("elusive", "Неуловимость"),
    ("stroke_of_luck", "Удача"),
    ("flexible_casting", "Гибкое колдовство"),
    ("font_of_magic", "Источник магии"),
    ("metamagic", "Метамагия"),
    ("sorcerous_restoration", "Чародейское восстановление"),
    ("eldritch_invocations", "Таинственные воззвания"),
    ("mystic_arcanum", "Таинственный арканум"),
    ("eldritch_master", "Таинственный мастер"),
    ("arcane_recovery", "Магическое восстановление"),
    ("spell_mastery", "Мастерство заклинаний"),
    ("signature_spell", "Фирменное заклинание"),
)

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


def ru_name(key: str, fallback: str = "") -> str:
    for prefix, name in RU_NAMES:
        if key.startswith(prefix):
            return name
    return fallback or key


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
        name = ru_name(key, str(f.get("name") or key))
        text = str(f.get("description") or "").strip()
        if len(text) > SEE_DESCRIPTION:
            text = text[:SEE_DESCRIPTION].rsplit(" ", 1)[0] + "…"
        row = {"key": key, "name": name, "level": int(f.get("level") or 1), "text": text}
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
            rows.append({"key": f"fighting_style_{pick}", "name": f"Боевой стиль: {name}", "level": 1, "text": text})
        else:
            rows.append(
                {"key": "fighting_style", "name": "Боевой стиль", "level": 1, "text": "", "detail": "не выбран"}
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
                "detail": ", ".join(got) + ("" if len(got) == need else f" (не выбрано: {need - len(got)})")
                if got
                else f"не выбрано: {need}",
            }
        )
    return rows


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
