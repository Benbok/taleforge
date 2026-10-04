"""Отдых и перезарядка по SRD 5.1 (просьба Arty 2026-10-04): умения с ограниченным числом использований, что
возвращает короткий и продолжительный отдых, «Магическое восстановление» волшебника, кости хитов, опасность места
для ночлега и проверка засады. Чистые функции: числа — из записи класса и листа героя, кубики передаёт сервер.
"""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from typing import Any

SHORT, LONG = "short_rest", "long_rest"
PER_RU = {SHORT: "короткий или продолжительный отдых", LONG: "продолжительный отдых"}
UNLIMITED = 9999  # так таблица SRD пишет «без ограничений» (ярость варвара 20-го уровня)


class RestError(Exception):
    """Отказ с понятной причиной: она уходит мастеру и игроку."""


@dataclass(frozen=True)
class Pool:
    """Умение с ограниченным числом использований: ``max`` раз (или единиц запаса) до отдыха ``per``."""

    key: str
    name: str
    max: int
    per: str  # short_rest | long_rest
    unit: str = "раз"  # «очков ци», «хитов» — у запасов, которые тратят частями

    def as_dict(self, spent: int = 0) -> dict[str, Any]:
        return {
            "key": self.key,
            "name": self.name,
            "max": self.max,
            "left": max(0, self.max - spent),
            "per": self.per,
            "per_ru": PER_RU.get(self.per, self.per),
            "unit": self.unit,
        }


def _owned(class_data: dict, level: int) -> set[str]:
    out: set[str] = set()
    for row in class_data.get("levels") or []:
        if int(row.get("level", 99)) <= level:
            out |= set(row.get("features") or [])
    return out


def _row(class_data: dict, level: int) -> dict:
    rows = [r for r in class_data.get("levels") or [] if int(r.get("level", 99)) <= level]
    return (max(rows, key=lambda r: int(r["level"])) if rows else {}).get("class_specific") or {}


def _has(owned: set[str], *prefixes: str) -> bool:
    return any(k.startswith(p) for k in owned for p in prefixes)


def srd_pools(class_data: dict, level: int, mods: dict[str, int]) -> list[Pool]:
    """Умения классов SRD с ограниченными использованиями. Какие есть у героя — по ключам умений его уровня."""
    owned = _owned(class_data, level)
    cs = _row(class_data, level)
    out: list[Pool] = []

    def add(key: str, name: str, n: int, per: str, unit: str = "раз") -> None:
        if 0 < n < UNLIMITED:
            out.append(Pool(key, name, n, per, unit))

    if "rage" in owned:
        add("rage", "Ярость", int(cs.get("rage_count") or 0), LONG)
    if _has(owned, "bardic_inspiration"):
        per = SHORT if "font_of_inspiration" in owned else LONG
        add("bardic_inspiration", "Вдохновение барда", max(1, mods.get("cha", 0)), per)
    if _has(owned, "channel_divinity"):
        n = int(cs.get("channel_divinity_charges") or 0) or 1
        add("channel_divinity", "Божественный канал", n, SHORT)
    if _has(owned, "wild_shape") and "archdruid" not in owned:
        add("wild_shape", "Дикий облик", 2, SHORT)
    if "second_wind" in owned:
        add("second_wind", "Второе дыхание", 1, SHORT)
    if _has(owned, "action_surge"):
        add("action_surge", "Всплеск действий", int(cs.get("action_surges") or 1), SHORT)
    if _has(owned, "indomitable"):
        add("indomitable", "Упорный", int(cs.get("indomitable_uses") or 1), LONG)
    if "ki" in owned:
        add("ki", "Ци", int(cs.get("ki_points") or level), SHORT, "очков")
    if "divine_sense" in owned:
        add("divine_sense", "Божественное чувство", 1 + mods.get("cha", 0), LONG)
    if "lay_on_hands" in owned:
        add("lay_on_hands", "Наложение рук", 5 * level, LONG, "хитов")
    if "cleansing_touch" in owned:
        add("cleansing_touch", "Очищающее касание", max(1, mods.get("cha", 0)), LONG)
    if "font_of_magic" in owned:
        add("sorcery_points", "Чародейские очки", int(cs.get("sorcery_points") or level), LONG, "очков")
    if "stroke_of_luck" in owned:
        add("stroke_of_luck", "Удача", 1, SHORT)
    for lvl in (6, 7, 8, 9):
        if f"mystic_arcanum_{lvl}th_level" in owned:
            add(f"mystic_arcanum_{lvl}", f"Таинственный арканум {lvl}-го круга", 1, LONG)
    if "arcane_recovery" in owned:
        add("arcane_recovery", "Магическое восстановление", 1, LONG)
    return out


def _count(spec: Any, level: int, pb: int, mods: dict[str, int]) -> int:
    """Число использований из данных пакета: 1, «pb», «int_mod», «level»."""
    if isinstance(spec, int):
        return spec
    s = str(spec or "").strip()
    if s.isdigit():
        return int(s)
    if s == "pb":
        return pb
    if s == "level":
        return level
    if s.endswith("_mod") and s[:3] in mods:
        return max(1, mods[s[:3]])
    return 0


def data_pools(class_data: dict, level: int, pb: int, mods: dict[str, int]) -> list[Pool]:
    """Умения пакета мира с полем ``uses: {count, per}`` (классы сеттинга): берутся, если герой их уже получил."""
    owned = _owned(class_data, level)
    out = []
    for f in class_data.get("features") or []:
        uses = f.get("uses")
        if not isinstance(uses, dict) or uses.get("per") not in (SHORT, LONG) or uses.get("per_target"):
            continue
        if f.get("key") not in owned and int(f.get("level") or 99) > level:
            continue
        n = _count(uses.get("count"), level, pb, mods)
        if n > 0:
            out.append(Pool(str(f["key"]), str(f.get("name") or f["key"]), n, uses["per"]))
    return out


def pools(class_data: dict, level: int, pb: int, mods: dict[str, int]) -> list[Pool]:
    seen: dict[str, Pool] = {}
    for p in [*srd_pools(class_data, level, mods), *data_pools(class_data, level, pb, mods)]:
        seen.setdefault(p.key, p)
    return list(seen.values())


def use(pool: Pool, spent: dict[str, int], amount: int = 1) -> dict[str, int]:
    """Тратит ``amount`` использований. Не хватает — отказ с тем, когда умение вернётся."""
    if amount < 1:
        raise RestError("тратится хотя бы одно использование")
    left = pool.max - int(spent.get(pool.key, 0))
    if left < amount:
        when = "после короткого или продолжительного отдыха" if pool.per == SHORT else "после продолжительного отдыха"
        have = f"осталось {left} {pool.unit}" if left else "использований не осталось"
        raise RestError(f"«{pool.name}»: {have}, нужно {amount}. Вернётся {when}")
    return {**spent, pool.key: int(spent.get(pool.key, 0)) + amount}


def restore(spent: dict[str, int], all_pools: list[Pool], kind: str) -> dict[str, int]:
    """Что возвращает отдых: короткий — умения «до короткого отдыха», продолжительный — всё."""
    if kind == "long":
        return {}
    short = {p.key for p in all_pools if p.per == SHORT}
    return {k: v for k, v in spent.items() if k not in short}


def hit_dice_back(level: int, left: int) -> int:
    """Продолжительный отдых возвращает половину костей хитов от уровня (минимум одну)."""
    return min(level, left + max(1, level // 2))


def arcane_recovery(slots: list[int], slots_used: dict[str, int], wizard_level: int) -> tuple[dict[str, int], list]:
    """«Магическое восстановление» на коротком отдыхе: ячейки суммой кругов до половины уровня волшебника (вверх),
    ни одной 6-го круга и выше. Возвращает старшие потраченные ячейки первыми."""
    budget = ceil(wizard_level / 2)
    used = {str(k): int(v) for k, v in (slots_used or {}).items()}
    back = []
    for lvl in range(min(5, len(slots)), 0, -1):
        while used.get(str(lvl), 0) > 0 and lvl <= budget:
            used[str(lvl)] -= 1
            budget -= lvl
            back.append(lvl)
    return {k: v for k, v in used.items() if v > 0}, back


# --- место для отдыха ---

SAFE, RISKY, DANGEROUS = "safe", "risky", "dangerous"
SAFETY_RU = {SAFE: "безопасное", RISKY: "ненадёжное", DANGEROUS: "опасное"}
DANGER_TAGS = {"danger", "lair", "nest", "hive", "brood", "infested", "warzone"}
RISKY_TAGS = {"wild", "underground", "hazard", "ruins", "ancient", "crime", "slums", "travel", "mine", "swamp"}
SAFE_TAGS = {"settlement", "social", "sacred", "city", "capital", "inn", "tavern", "shelter", "haven", "home"}


def place_safety(explicit: str | None, tags: set[str], watch: dict | None) -> str:
    """Насколько место годится для ночлега. Отметка мастера или пакета — главнее; дальше теги места: опасные,
    дикие, жилые. Частые встречи по расписанию места (два и больше исхода на d6 или чаще раза в 2 часа) делают
    место опасным. Место без признаков — ненадёжное: под открытым небом засада возможна."""
    if explicit in (SAFE, RISKY, DANGEROUS):
        return explicit
    if tags & DANGER_TAGS:
        return DANGEROUS
    rule = watch or {}
    hits = len(rule.get("on_d6") or [])
    every = int(rule.get("every_hours") or 4)
    if watch is not None and (hits >= 2 or every <= 2):
        return DANGEROUS
    if tags & RISKY_TAGS:
        return RISKY
    if tags & SAFE_TAGS:
        return SAFE
    return RISKY


def ambush_rolls(safety: str, hours: int, watch: dict | None) -> tuple[int, set[int]]:
    """Сколько раз за отдых проверять засаду и какие грани d6 её дают. Безопасное место — ни разу. Опасное — не
    реже чем 1–2 на d6. Короткий отдых (час) — одна проверка."""
    if safety == SAFE:
        return 0, set()
    rule = watch or {}
    every = max(1, int(rule.get("every_hours") or 4))
    hits = {int(x) for x in rule.get("on_d6") or [1]}
    if safety == DANGEROUS:
        hits |= {1, 2}
    return max(1, ceil(hours / every)), hits
