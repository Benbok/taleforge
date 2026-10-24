"""Движок правил: интерфейс RulesEngine, кубики и реализации по системам."""

from app.rules.base import RollMode, RulesEngine
from app.rules.dice import Dice, FixedDice

__all__ = ["Dice", "FixedDice", "RollMode", "RulesEngine", "get_engine"]


def get_engine(ruleset_id: str) -> RulesEngine:
    """Движок по ``ruleset_id`` кампании. Пока известен только ``dnd5e``."""
    if ruleset_id == "universal":
        from app.rules.universal.engine import UniversalEngine

        return UniversalEngine()
    raise KeyError(f"неизвестная система правил: {ruleset_id}")
