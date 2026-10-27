from app.rules.universal.profiles import resolve_attack, resolve_check, resource_cost


class UniversalEngine:
    """Universal actions use saved bounded profiles, without legacy spell tables."""

    ruleset_id = "universal"
    version = "universal.v1"

    ability_modifier = staticmethod(lambda score: (score - 10) // 2)
    proficiency_bonus = staticmethod(lambda level: 2)
    resolve_check = staticmethod(resolve_check)
    resolve_attack = staticmethod(resolve_attack)
    resource_cost = staticmethod(resource_cost)
