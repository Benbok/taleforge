from app.rules.universal.contracts import ENERGY_KEYS, START_ARRAY, AbilityScores, ActorDerived, UniversalSheet


def validate_starting_scores(scores: AbilityScores) -> AbilityScores:
    if sorted(scores.model_dump().values()) != list(START_ARRAY):
        raise ValueError("используйте каждое значение 15, 14, 13, 12, 10, 8 ровно один раз")
    return scores


def derive(sheet: UniversalSheet, defense_bonuses: list[int]) -> ActorDerived:
    scores = sheet.abilities.model_dump()
    mods = {key: (value - 10) // 2 for key, value in scores.items()}
    return ActorDerived(
        hp_max=10 + scores["con"] + 6 * (sheet.level - 1),
        energy_max={key: sheet.level * (10 + scores[key]) for key in ENERGY_KEYS},
        ac=12 + mods["dex"] + sum(defense_bonuses),
        modifiers=mods,
    )
