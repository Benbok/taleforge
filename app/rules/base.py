"""Интерфейс RulesEngine и результаты бросков.

Движок правил — единственное место, где считаются числа. Мастер вызывает инструменты,
инструменты вызывают движок, результат (со всеми кубиками) пишется в журнал событий.
Реализация под конкретную систему (``dnd5e``) подключается по ``ruleset_id`` кампании.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Protocol

from app.rules.dice import Dice, DiceRoll


class RollMode(StrEnum):
    NORMAL = "normal"
    ADVANTAGE = "advantage"
    DISADVANTAGE = "disadvantage"

    @classmethod
    def combine(cls, advantage: bool, disadvantage: bool) -> RollMode:
        """SRD: преимущество и помеха гасят друг друга, сколько бы источников ни было."""
        if advantage and not disadvantage:
            return cls.ADVANTAGE
        if disadvantage and not advantage:
            return cls.DISADVANTAGE
        return cls.NORMAL


@dataclass(frozen=True)
class D20Roll:
    rolls: tuple[int, ...]  # оба кубика при преимуществе или помехе
    natural: int  # выбранный кубик
    modifier: int
    mode: RollMode

    @property
    def total(self) -> int:
        return self.natural + self.modifier


@dataclass(frozen=True)
class CheckResult:
    """Проверка характеристики или спасбросок против сложности."""

    roll: D20Roll
    dc: int
    success: bool
    critical: str | None = None  # "success" при натуральной 20, "fail" при натуральной 1 — если кампания их считает

    @property
    def margin(self) -> int:
        """На сколько бросок выше (или ниже) сложности. Нужен для исходов «провал на 5 и больше»."""
        return self.roll.total - self.dc


@dataclass(frozen=True)
class AttackResult:
    roll: D20Roll
    target_ac: int
    hit: bool
    critical: bool


@dataclass(frozen=True)
class DamageResult:
    roll: DiceRoll
    damage_type: str
    raw: int  # до сопротивлений
    final: int  # после сопротивлений, уязвимостей и иммунитета
    applied: tuple[str, ...] = ()  # какие защиты сработали


@dataclass
class DeathSaves:
    successes: int = 0
    failures: int = 0

    @property
    def stable(self) -> bool:
        return self.successes >= 3

    @property
    def dead(self) -> bool:
        return self.failures >= 3


@dataclass(frozen=True)
class DeathSaveResult:
    roll: D20Roll
    saves: DeathSaves
    regained_hp: int  # 1 при натуральной 20, иначе 0


@dataclass
class HitPoints:
    current: int
    maximum: int
    temp: int = 0
    death_saves: DeathSaves = field(default_factory=DeathSaves)
    dead: bool = False

    @property
    def dying(self) -> bool:
        return not self.dead and self.current == 0 and not self.death_saves.stable


@dataclass(frozen=True)
class HpChange:
    before: int
    after: int
    temp_before: int
    temp_after: int
    dropped_to_zero: bool
    instant_death: bool
    death_save_failures_added: int
    dead: bool


class RulesEngine(Protocol):
    """Что движок правил обязан уметь. Всё детерминировано при заданных кубиках."""

    ruleset_id: str
    version: str

    def ability_modifier(self, score: int) -> int: ...

    def proficiency_bonus(self, level: int) -> int: ...

    def roll_d20(self, dice: Dice, modifier: int, mode: RollMode = RollMode.NORMAL) -> D20Roll: ...

    def check(
        self, dice: Dice, modifier: int, dc: int, mode: RollMode = RollMode.NORMAL, crits: bool = False
    ) -> CheckResult: ...

    def saving_throw(
        self, dice: Dice, modifier: int, dc: int, mode: RollMode = RollMode.NORMAL, crits: bool = False
    ) -> CheckResult: ...

    def attack(
        self, dice: Dice, attack_bonus: int, target_ac: int, mode: RollMode = RollMode.NORMAL
    ) -> AttackResult: ...

    def damage(
        self,
        dice: Dice,
        expr: str,
        damage_type: str,
        critical: bool = False,
        resistances: frozenset[str] = frozenset(),
        vulnerabilities: frozenset[str] = frozenset(),
        immunities: frozenset[str] = frozenset(),
    ) -> DamageResult: ...

    def apply_damage(self, hp: HitPoints, amount: int, critical: bool = False) -> HpChange: ...

    def heal(self, hp: HitPoints, amount: int) -> HpChange: ...

    def death_save(self, dice: Dice, hp: HitPoints) -> DeathSaveResult: ...

    def initiative(self, dice: Dice, dex_modifier: int, mode: RollMode = RollMode.NORMAL) -> D20Roll: ...
