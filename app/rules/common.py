"""Shared roll and vitality arithmetic; no classes, spell catalogs or level ceiling."""

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
from app.rules.death import apply_death_roll
from app.rules.dice import Dice, parse


class RulesError(ValueError):
    """A numeric operation was not valid."""


class ScalarRules:
    ruleset_id = "universal"
    version = "universal.v1"

    @staticmethod
    def ability_modifier(score):
        return (score - 10) // 2

    @staticmethod
    def proficiency_bonus(level):
        return 2

    @staticmethod
    def roll_d20(dice: Dice, modifier: int, mode: RollMode = RollMode.NORMAL):
        rolls = (dice.d20(),) if mode == RollMode.NORMAL else (dice.d20(), dice.d20())
        natural = min(rolls) if mode == RollMode.DISADVANTAGE else max(rolls)
        return D20Roll(rolls, natural, modifier, mode)

    def check(self, dice, modifier, dc, mode=RollMode.NORMAL, crits=True):
        if dc < 0:
            raise RulesError("Difficulty cannot be negative")
        roll = self.roll_d20(dice, modifier, mode)
        critical = "success" if crits and roll.natural == 20 else "fail" if crits and roll.natural == 1 else None
        success = critical == "success" if critical else roll.total >= dc
        return CheckResult(roll, dc, success, critical)

    saving_throw = check

    def attack(self, dice, attack_bonus, target_ac, mode=RollMode.NORMAL):
        roll = self.roll_d20(dice, attack_bonus, mode)
        hit = roll.natural == 20 or (roll.natural != 1 and roll.total >= target_ac)
        return AttackResult(roll, target_ac, hit, roll.natural == 20)

    @staticmethod
    def passive_score(modifier, mode=RollMode.NORMAL):
        return 10 + modifier + {RollMode.ADVANTAGE: 5, RollMode.DISADVANTAGE: -5}.get(mode, 0)

    @staticmethod
    def apply_defenses(
        amount, damage_type, resistances=frozenset(), vulnerabilities=frozenset(), immunities=frozenset()
    ):
        if damage_type in immunities or "*" in immunities:
            return 0, ("immunity",)
        applied = []
        if damage_type in resistances or "*" in resistances:
            amount //= 2
            applied.append("resistance")
        if damage_type in vulnerabilities or "*" in vulnerabilities:
            amount *= 2
            applied.append("vulnerability")
        return amount, tuple(applied)

    def damage(
        self,
        dice,
        expr,
        damage_type,
        critical=False,
        resistances=frozenset(),
        vulnerabilities=frozenset(),
        immunities=frozenset(),
    ):
        expression = parse(expr)
        roll = dice.roll(expression.doubled_dice() if critical else expression)
        raw = max(0, roll.total)
        final, applied = self.apply_defenses(raw, damage_type, resistances, vulnerabilities, immunities)
        return DamageResult(roll, damage_type, raw, final, applied)

    @staticmethod
    def apply_damage(hp: HitPoints, amount, critical=False):
        if amount < 0:
            raise RulesError("Damage cannot be negative")
        before, temp_before = hp.current, hp.temp
        if hp.dead:
            return HpChange(before, before, temp_before, temp_before, False, False, 0, True)
        absorbed = min(hp.temp, amount)
        hp.temp -= absorbed
        remaining = amount - absorbed
        failures = 0
        instant = False
        if remaining and not hp.dead:
            if hp.current == 0:
                if remaining >= hp.maximum:
                    instant = True
                    hp.dead = True
                else:
                    failures = 2 if critical else 1
                    ds = hp.death_saves
                    hp.death_saves = DeathSaves(0 if ds.stable else ds.successes, ds.failures + failures)
                    hp.dead = hp.death_saves.dead
            else:
                excess = max(0, remaining - hp.current)
                hp.current = max(0, hp.current - remaining)
                if hp.current == 0:
                    hp.death_saves = DeathSaves()
                    instant = excess >= hp.maximum
                    hp.dead = instant
        return HpChange(
            before, hp.current, temp_before, hp.temp, before > 0 and hp.current == 0, instant, failures, hp.dead
        )

    @staticmethod
    def heal(hp: HitPoints, amount):
        if amount < 0:
            raise RulesError("Healing cannot be negative")
        before = hp.current
        if not hp.dead:
            hp.current = min(hp.maximum, hp.current + amount)
            if hp.current > 0:
                hp.death_saves = DeathSaves()
        return HpChange(before, hp.current, hp.temp, hp.temp, False, False, 0, hp.dead)

    @staticmethod
    def add_temp_hp(hp: HitPoints, amount):
        hp.temp = max(hp.temp, amount)

    def death_save(self, dice, hp: HitPoints, mode=RollMode.NORMAL):
        if not hp.dying:
            raise RulesError("Only an unconscious dying actor makes a rescue roll")
        roll = self.roll_d20(dice, 0, mode)
        regained = apply_death_roll(hp, roll.natural)
        return DeathSaveResult(roll, hp.death_saves, regained)
