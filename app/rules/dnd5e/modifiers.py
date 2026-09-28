"""Интерпретатор модификаторов эффектов для бросков (язык модификаторов пакета, ТЗ, раздел 3.2).

Этап 3 исполняет то, что влияет на бросок, защиту и способность действовать: ``advantage``/``disadvantage``
(свои и ``who: attackers``, с условием дистанции ``within_ft``/``beyond_ft``), ``set`` с ``auto: fail``
для спасбросков, ``hit_is_critical``, ``can_act``, числовой ``add`` к ``ac``/``attack``/``save``/``check``,
``resistance``/``vulnerability``/``immunity`` урона и вложенные ``condition``. Модификатор с условием ``if``,
которое движок пока не умеет проверять, не применяется и попадает в список ``skipped``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from app.rules.base import RollMode


@dataclass
class Modifiers:
    """Плоский список модификаторов существа: собран из всех наложенных на него эффектов."""

    items: list[tuple[str, dict[str, Any]]] = field(default_factory=list)  # (id эффекта, модификатор)
    skipped: list[str] = field(default_factory=list)

    def own(self, op: str) -> Iterable[tuple[str, dict]]:
        return ((src, m) for src, m in self.items if m.get("op") == op and m.get("who") in (None, "self"))

    def vs_attackers(self, op: str) -> Iterable[tuple[str, dict]]:
        return ((src, m) for src, m in self.items if m.get("op") == op and m.get("who") == "attackers")


def collect(effects: Iterable[tuple[str, dict, int]], lookup: Callable[[str], dict | None]) -> Modifiers:
    """``effects``: [(id шаблона эффекта, данные шаблона, стаки)]. ``lookup`` ищет состояние по имени."""
    out = Modifiers()
    seen: set[str] = set()

    def add(src: str, mods: Iterable[dict], depth: int = 0) -> None:
        for m in mods or []:
            if not isinstance(m, dict):
                continue
            if m.get("op") == "condition" and depth < 3:
                name = str(m.get("condition", ""))
                rec = lookup(name)
                key = f"{src}>{name}"
                if rec is not None and key not in seen:
                    seen.add(key)
                    add(rec.get("id", name), rec.get("modifiers") or [], depth + 1)
                continue
            if "if" in m:
                out.skipped.append(f"{src}: {m.get('op')} при условии {m['if']}")
                continue
            out.items.append((src, m))

    for eid, data, stacks in effects:
        add(eid, data.get("modifiers") or [])
        levels = data.get("levels")
        if isinstance(levels, dict):  # истощение: уровни накопительно
            for lvl in range(1, int(stacks) + 1):
                add(eid, levels.get(str(lvl)) or levels.get(lvl) or [])
    return out


def _matches(m: dict, on: str, stat: str | None = None, skill: str | None = None) -> bool:
    if m.get("on") != on:
        return False
    if m.get("stat") and stat and m["stat"] != stat:
        return False
    if m.get("stat") and not stat:
        return False
    return not (m.get("skill") and m["skill"] != skill)


def _distance_ok(m: dict, distance_ft: int) -> bool:
    if "within_ft" in m and distance_ft > int(m["within_ft"]):
        return False
    return not ("beyond_ft" in m and distance_ft <= int(m["beyond_ft"]))


@dataclass(frozen=True)
class AttackMods:
    mode: RollMode
    auto_crit: bool
    bonus: int
    reasons: tuple[str, ...]


def attack_mods(attacker: Modifiers, target: Modifiers, distance_ft: int, extra: Iterable[str] = ()) -> AttackMods:
    """Режим броска атаки: свои эффекты атакующего и эффекты цели «для атакующих». ``extra`` — причины
    помехи от правил боя (дальний выстрел, стрельба вплотную)."""
    adv, dis, reasons = False, False, list(extra)
    if extra:
        dis = True
    for src, m in attacker.own("advantage"):
        if _matches(m, "attack"):
            adv = True
            reasons.append(f"преимущество: {src}")
    for src, m in attacker.own("disadvantage"):
        if _matches(m, "attack"):
            dis = True
            reasons.append(f"помеха: {src}")
    for src, m in target.vs_attackers("advantage"):
        if _matches(m, "attack") and _distance_ok(m, distance_ft):
            adv = True
            reasons.append(f"преимущество: цель {src}")
    for src, m in target.vs_attackers("disadvantage"):
        if _matches(m, "attack") and _distance_ok(m, distance_ft):
            dis = True
            reasons.append(f"помеха: цель {src}")
    crit = any(
        m.get("target") == "hit_is_critical" and m.get("value") is True and _distance_ok(m, distance_ft)
        for _, m in target.vs_attackers("set")
    )
    return AttackMods(RollMode.combine(adv, dis), crit, add_value(attacker, "attack"), tuple(reasons))


def roll_mode(mods: Modifiers, on: str, stat: str | None = None, skill: str | None = None) -> tuple[RollMode, list]:
    adv = dis = False
    reasons = []
    for src, m in mods.own("advantage"):
        if _matches(m, on, stat, skill):
            adv = True
            reasons.append(f"преимущество: {src}")
    for src, m in mods.own("disadvantage"):
        if _matches(m, on, stat, skill):
            dis = True
            reasons.append(f"помеха: {src}")
    return RollMode.combine(adv, dis), reasons


def save_auto_fail(mods: Modifiers, stat: str) -> str | None:
    for src, m in mods.own("set"):
        if m.get("target") == "save_result" and m.get("auto") == "fail" and m.get("stat") in (None, stat):
            return src
    return None


def can_act(mods: Modifiers) -> str | None:
    """Недееспособен: id эффекта, который запрещает действовать, иначе None."""
    for src, m in mods.own("set"):
        if m.get("target") == "can_act" and m.get("value") is False:
            return src
    return None


def add_value(mods: Modifiers, target: str) -> int:
    total = 0
    for _, m in mods.own("add"):
        if m.get("target") == target and isinstance(m.get("value"), int):
            total += m["value"]
    return total


def defenses(mods: Modifiers) -> tuple[set[str], set[str], set[str]]:
    """Сопротивления, уязвимости, иммунитеты к урону от эффектов. ``damage: all`` — ко всем видам."""
    from app.rules.dnd5e.tables import DAMAGE_TYPES

    out: dict[str, set[str]] = {"resistance": set(), "vulnerability": set(), "immunity": set()}
    for op, bucket in out.items():
        for _, m in mods.own(op):
            dmg = m.get("damage")
            if dmg == "all":
                bucket |= set(DAMAGE_TYPES)
            elif isinstance(dmg, str):
                bucket.add(dmg)
            elif isinstance(dmg, list):
                bucket |= {d for d in dmg if isinstance(d, str)}
    return out["resistance"], out["vulnerability"], out["immunity"]


def condition_immunities(mods: Modifiers) -> set[str]:
    return {str(m["condition"]) for _, m in mods.own("immunity") if m.get("condition")}
