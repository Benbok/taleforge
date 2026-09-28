"""Кубики: разбор выражений вида ``2d6+3`` и броски с воспроизводимым генератором.

Генератор передаётся явно, чтобы тесты и журнал событий могли повторить бросок по seed.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass

_TERM = re.compile(r"([+-]?)\s*(?:(\d*)d(\d+)|(\d+))", re.IGNORECASE)
_FULL = re.compile(r"^\s*[+-]?\s*(?:\d*d\d+|\d+)(?:\s*[+-]\s*(?:\d*d\d+|\d+))*\s*$", re.IGNORECASE)

MAX_DICE = 100
ALLOWED_SIDES = {2, 3, 4, 6, 8, 10, 12, 20, 100}


class DiceError(ValueError):
    """Выражение кубиков не разобрано или выходит за пределы."""


@dataclass(frozen=True)
class DiceTerm:
    sign: int
    count: int
    sides: int  # 0 для числа без кубика

    @property
    def is_constant(self) -> bool:
        return self.sides == 0


@dataclass(frozen=True)
class DiceExpr:
    terms: tuple[DiceTerm, ...]
    text: str

    @property
    def modifier(self) -> int:
        return sum(t.sign * t.count for t in self.terms if t.is_constant)

    def doubled_dice(self) -> DiceExpr:
        """Критическое попадание по SRD: кубики урона удваиваются, модификатор нет."""
        terms = tuple(t if t.is_constant else DiceTerm(t.sign, t.count * 2, t.sides) for t in self.terms)
        return DiceExpr(terms, _render(terms))


@dataclass(frozen=True)
class DiceRoll:
    expr: DiceExpr
    rolls: tuple[tuple[int, int], ...]  # (грани, выпало) для каждого кубика
    total: int

    @property
    def text(self) -> str:
        return self.expr.text


def _render(terms: tuple[DiceTerm, ...]) -> str:
    out = []
    for i, t in enumerate(terms):
        body = str(t.count) if t.is_constant else f"{t.count}d{t.sides}"
        if i == 0:
            out.append(body if t.sign > 0 else f"-{body}")
        else:
            out.append(f"{'+' if t.sign > 0 else '-'}{body}")
    return "".join(out)


def parse(text: str) -> DiceExpr:
    if not isinstance(text, str) or not _FULL.match(text):
        raise DiceError(f"не выражение кубиков: {text!r}")
    terms = []
    for sign, count, sides, const in _TERM.findall(text):
        s = -1 if sign == "-" else 1
        if const:
            terms.append(DiceTerm(s, int(const), 0))
            continue
        n, f = int(count or 1), int(sides)
        if f not in ALLOWED_SIDES:
            raise DiceError(f"нет кубика d{f}")
        if not 1 <= n <= MAX_DICE:
            raise DiceError(f"число кубиков вне 1..{MAX_DICE}: {n}")
        terms.append(DiceTerm(s, n, f))
    t = tuple(terms)
    return DiceExpr(t, _render(t))


class Dice:
    """Источник случайности движка. В проде — системный генератор, в тестах — seed."""

    def __init__(self, seed: int | None = None, rng: random.Random | None = None):
        self._rng = rng or (random.Random(seed) if seed is not None else random.SystemRandom())

    def die(self, sides: int) -> int:
        return self._rng.randint(1, sides)

    def roll(self, expr: str | DiceExpr) -> DiceRoll:
        e = parse(expr) if isinstance(expr, str) else expr
        rolls: list[tuple[int, int]] = []
        total = 0
        for t in e.terms:
            if t.is_constant:
                total += t.sign * t.count
                continue
            for _ in range(t.count):
                v = self.die(t.sides)
                rolls.append((t.sides, v))
                total += t.sign * v
        return DiceRoll(e, tuple(rolls), total)

    def d20(self) -> int:
        return self.die(20)


class FixedDice(Dice):
    """Кубики с заранее заданными значениями, по порядку. Для тестов и воспроизведения журнала."""

    def __init__(self, values: list[int]):
        super().__init__(seed=0)
        self._values = list(values)

    def die(self, sides: int) -> int:
        if not self._values:
            raise DiceError("закончились заданные значения кубиков")
        v = self._values.pop(0)
        if not 1 <= v <= sides:
            raise DiceError(f"значение {v} невозможно на d{sides}")
        return v
