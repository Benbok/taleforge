"""D&D 5e SRD 5.1: проверки, атаки, урон, хиты, спасброски от смерти, инициатива, производные величины."""

from __future__ import annotations

from dataclasses import replace

from app.rules.base import (
    AttackResult,
    CheckResult,
    D20Roll,
    DamageResult,
    DeathSaveResult,
    DeathSaves,
    HitPoints,
    HpChange,
    RollMode,
)
from app.rules.dice import Dice, parse
from app.rules.dnd5e.tables import DAMAGE_TYPES, HIT_DICE, MAX_LEVEL, SKILLS


class RulesError(ValueError):
    """Недопустимый вызов движка: такой ситуации правила не допускают."""


class Dnd5eEngine:
    ruleset_id = "dnd5e"
    version = "0.1.0"

    # --- Характеристики и уровни ---

    def ability_modifier(self, score: int) -> int:
        if not 1 <= score <= 30:
            raise RulesError(f"значение характеристики вне 1..30: {score}")
        return (score - 10) // 2

    def proficiency_bonus(self, level: int) -> int:
        if not 1 <= level <= MAX_LEVEL:
            raise RulesError(f"уровень вне 1..{MAX_LEVEL}: {level}")
        return 2 + (level - 1) // 4

    def skill_ability(self, skill: str) -> str:
        try:
            return SKILLS[skill]
        except KeyError:
            raise RulesError(f"нет навыка {skill}") from None

    def check_modifier(
        self, ability_score: int, level: int, proficient: bool = False, expertise: bool = False, bonus: int = 0
    ) -> int:
        """Модификатор проверки навыка или спасброска: характеристика + бонус мастерства (×2 при экспертизе)."""
        pb = self.proficiency_bonus(level)
        prof = pb * 2 if expertise else pb if proficient else 0
        return self.ability_modifier(ability_score) + prof + bonus

    def passive_score(self, modifier: int, mode: RollMode = RollMode.NORMAL) -> int:
        """Пассивная проверка: 10 + модификатор, ±5 за преимущество или помеху."""
        return 10 + modifier + {RollMode.ADVANTAGE: 5, RollMode.DISADVANTAGE: -5}.get(mode, 0)

    def spell_save_dc(self, ability_score: int, level: int) -> int:
        return 8 + self.proficiency_bonus(level) + self.ability_modifier(ability_score)

    def spell_attack_bonus(self, ability_score: int, level: int) -> int:
        return self.proficiency_bonus(level) + self.ability_modifier(ability_score)

    # --- Броски d20 ---

    def roll_d20(self, dice: Dice, modifier: int, mode: RollMode = RollMode.NORMAL) -> D20Roll:
        if mode is RollMode.NORMAL:
            n = dice.d20()
            return D20Roll((n,), n, modifier, mode)
        a, b = dice.d20(), dice.d20()
        natural = max(a, b) if mode is RollMode.ADVANTAGE else min(a, b)
        return D20Roll((a, b), natural, modifier, mode)

    def check(
        self, dice: Dice, modifier: int, dc: int, mode: RollMode = RollMode.NORMAL, crits: bool = False
    ) -> CheckResult:
        """Проверка характеристики. В SRD натуральные 1 и 20 на проверках ничего особого не значат; ``crits`` —
        домашнее правило кампании: натуральная 20 — критический успех, натуральная 1 — критический провал,
        какой бы ни была сложность."""
        self._require_dc(dc)
        roll = self.roll_d20(dice, modifier, mode)
        if crits and roll.natural == 20:
            return CheckResult(roll, dc, True, "success")
        if crits and roll.natural == 1:
            return CheckResult(roll, dc, False, "fail")
        return CheckResult(roll, dc, roll.total >= dc)

    def saving_throw(
        self, dice: Dice, modifier: int, dc: int, mode: RollMode = RollMode.NORMAL, crits: bool = False
    ) -> CheckResult:
        return self.check(dice, modifier, dc, mode, crits)

    def attack(self, dice: Dice, attack_bonus: int, target_ac: int, mode: RollMode = RollMode.NORMAL) -> AttackResult:
        """Натуральная 20 — всегда попадание и крит, натуральная 1 — всегда промах."""
        roll = self.roll_d20(dice, attack_bonus, mode)
        if roll.natural == 20:
            return AttackResult(roll, target_ac, hit=True, critical=True)
        if roll.natural == 1:
            return AttackResult(roll, target_ac, hit=False, critical=False)
        return AttackResult(roll, target_ac, hit=roll.total >= target_ac, critical=False)

    def initiative(self, dice: Dice, dex_modifier: int, mode: RollMode = RollMode.NORMAL) -> D20Roll:
        return self.roll_d20(dice, dex_modifier, mode)

    @staticmethod
    def initiative_order(entries: list[tuple[str, D20Roll, int]]) -> list[str]:
        """Порядок хода: (id, бросок инициативы, модификатор Ловкости). При равенстве выше Ловкость, затем id."""
        return [e[0] for e in sorted(entries, key=lambda e: (-e[1].total, -e[2], e[0]))]

    # --- Урон и хиты ---

    def damage(
        self,
        dice: Dice,
        expr: str,
        damage_type: str,
        critical: bool = False,
        resistances: frozenset[str] = frozenset(),
        vulnerabilities: frozenset[str] = frozenset(),
        immunities: frozenset[str] = frozenset(),
    ) -> DamageResult:
        if damage_type not in DAMAGE_TYPES:
            raise RulesError(f"нет вида урона {damage_type}")
        e = parse(expr)
        if critical:
            e = e.doubled_dice()
        roll = dice.roll(e)
        raw = max(0, roll.total)
        final, applied = self.apply_defenses(raw, damage_type, resistances, vulnerabilities, immunities)
        return DamageResult(roll, damage_type, raw, final, applied)

    @staticmethod
    def apply_defenses(
        amount: int,
        damage_type: str,
        resistances: frozenset[str] = frozenset(),
        vulnerabilities: frozenset[str] = frozenset(),
        immunities: frozenset[str] = frozenset(),
    ) -> tuple[int, tuple[str, ...]]:
        """Иммунитет обнуляет; сопротивление делит пополам с округлением вниз; уязвимость удваивает.
        Несколько сопротивлений одного вида считаются как одно; сначала сопротивление, потом уязвимость."""
        if damage_type in immunities:
            return 0, ("immunity",)
        applied = []
        if damage_type in resistances:
            amount //= 2
            applied.append("resistance")
        if damage_type in vulnerabilities:
            amount *= 2
            applied.append("vulnerability")
        return amount, tuple(applied)

    def apply_damage(self, hp: HitPoints, amount: int, critical: bool = False) -> HpChange:
        """Списывает урон: сначала временные хиты, потом обычные. Мгновенная смерть,
        если остаток урона после падения до 0 не меньше максимума хитов. Урон при 0 хитов —
        провал спасброска от смерти (два при крите). Меняет ``hp`` на месте."""
        if amount < 0:
            raise RulesError("урон не бывает отрицательным")
        before, temp_before = hp.current, hp.temp
        if hp.dead:
            return HpChange(before, before, temp_before, temp_before, False, False, 0, True)

        absorbed = min(hp.temp, amount)
        hp.temp -= absorbed
        rest = amount - absorbed
        instant = dropped = False
        failures_added = 0

        if rest > 0 and hp.current == 0:
            if rest >= hp.maximum:
                instant = True
            else:
                failures_added = 2 if critical else 1
                ds = hp.death_saves
                hp.death_saves = DeathSaves(0 if ds.stable else ds.successes, ds.failures + failures_added)
        elif rest > 0:
            if rest >= hp.current:
                overflow = rest - hp.current
                hp.current = 0
                dropped = True
                hp.death_saves = DeathSaves()
                instant = overflow >= hp.maximum
            else:
                hp.current -= rest

        if instant or hp.death_saves.dead:
            hp.dead = True
        return HpChange(before, hp.current, temp_before, hp.temp, dropped, instant, failures_added, hp.dead)

    def heal(self, hp: HitPoints, amount: int) -> HpChange:
        """Лечение не поднимает мёртвых и не выше максимума. С 0 хитов сбрасывает спасброски от смерти."""
        if amount < 0:
            raise RulesError("лечение не бывает отрицательным")
        before = hp.current
        if not hp.dead and amount > 0:
            hp.current = min(hp.maximum, hp.current + amount)
            if before == 0:
                hp.death_saves = DeathSaves()
        return HpChange(before, hp.current, hp.temp, hp.temp, False, False, 0, hp.dead)

    def add_temp_hp(self, hp: HitPoints, amount: int) -> None:
        """Временные хиты не складываются: остаётся большее значение."""
        hp.temp = max(hp.temp, amount)

    def death_save(self, dice: Dice, hp: HitPoints, mode: RollMode = RollMode.NORMAL) -> DeathSaveResult:
        """10 и выше — успех, ниже — провал; 1 — два провала; 20 — встаёт с 1 хитом."""
        if not hp.dying:
            raise RulesError("спасбросок от смерти делает только умирающий")
        roll = self.roll_d20(dice, 0, mode)
        ds = hp.death_saves
        regained = 0
        if roll.natural == 20:
            hp.current = 1
            hp.death_saves = DeathSaves()
            regained = 1
        elif roll.natural == 1:
            hp.death_saves = replace(ds, failures=ds.failures + 2)
        elif roll.natural >= 10:
            hp.death_saves = replace(ds, successes=ds.successes + 1)
        else:
            hp.death_saves = replace(ds, failures=ds.failures + 1)
        if hp.death_saves.dead:
            hp.dead = True
        return DeathSaveResult(roll, hp.death_saves, regained)

    # --- Производные величины ---

    def armor_class(
        self,
        dex_modifier: int,
        armor: dict | None = None,
        shield_bonus: int = 0,
        bonus: int = 0,
    ) -> int:
        """КД по SRD. ``armor`` — поля записи ``item_template`` доспеха: ``ac_base`` и ``dex_cap``
        (``null`` — без предела, ``0`` — тяжёлый доспех). Без доспеха: 10 + Ловкость."""
        if armor is None:
            return 10 + dex_modifier + shield_bonus + bonus
        cap = armor.get("dex_cap")
        dex = dex_modifier if cap is None else min(dex_modifier, cap)
        return int(armor["ac_base"]) + dex + shield_bonus + bonus

    def hit_points_max(self, hit_die: int, con_modifier: int, level: int) -> int:
        """Максимум хитов с фиксированным значением за уровень: на 1-м — максимум кости,
        дальше — среднее по SRD (половина кости + 1). Каждый уровень даёт не меньше 1 хита."""
        if hit_die not in HIT_DICE:
            raise RulesError(f"нет кости хитов d{hit_die}")
        self.proficiency_bonus(level)  # проверка диапазона уровня
        first = max(1, hit_die + con_modifier)
        per_level = max(1, hit_die // 2 + 1 + con_modifier)
        return first + per_level * (level - 1)

    @staticmethod
    def _require_dc(dc: int) -> None:
        if not isinstance(dc, int) or not 0 < dc <= 40:
            raise RulesError(f"сложность должна быть целым числом из данных, получено {dc!r}")
