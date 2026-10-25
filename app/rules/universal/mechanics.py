from app.rules.universal.contracts import ENERGY_KEYS, START_ARRAY, AbilityScores, ActorDerived, UniversalSheet


def validate_starting_scores(scores: AbilityScores) -> AbilityScores:
    if sorted(scores.model_dump().values()) != list(START_ARRAY):
        raise ValueError("используйте каждое значение 15, 14, 13, 12, 10, 8 ровно один раз")
    return scores


def starting_defense_bonuses(sheet: UniversalSheet) -> list[int]:
    return [sheet.starting_equipment.armor.defense_bonus] if sheet.starting_equipment else []


def starting_items(sheet: UniversalSheet) -> list[dict]:
    if not sheet.starting_equipment:
        return []
    return [item.model_dump(mode="json") for item in (sheet.starting_equipment.weapon, sheet.starting_equipment.armor)]


def derive(sheet: UniversalSheet, defense_bonuses: list[int]) -> ActorDerived:
    scores = sheet.abilities.model_dump()
    mods = {key: (value - 10) // 2 for key, value in scores.items()}
    return ActorDerived(
        hp_max=10 + scores["con"] + 6 * (sheet.level - 1),
        energy_max={key: sheet.level * (10 + scores[key]) for key in ENERGY_KEYS},
        ac=12 + mods["dex"] + sum(defense_bonuses),
        modifiers=mods,
    )


STEP_SECONDS = 6  # one short game step; a longer action restores once per started step


def energy_regen(pool_max: int) -> int:
    """Energy a pool gets back per game step: about a twelfth of the pool, rounded, at least one.

    A larger pool (a higher ability or level) therefore recovers faster, and a simple spell paid in
    one sitting returns in a handful of steps, while consumables still restore a whole pool at once."""
    return max(1, (pool_max + 6) // 12)
