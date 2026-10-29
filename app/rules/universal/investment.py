"""Energy investment: a player may buy a small shortfall on a failed check with the attribute's own energy."""

INVEST_COST_FACTOR = 3  # same base as an ability's cost: 3 per level
INVEST_MAX_SHORTFALL = 5  # a bigger miss stays a miss, so the die keeps its weight
INVEST_TIMEOUT_SECONDS = 45  # the table waits this long for the decision


def shortfall(natural: int, total: int, difficulty: int) -> int:
    """Points missing to a success; 0 when investing cannot help (success, natural 1, natural 20)."""
    if natural in (1, 20):
        return 0
    return max(0, difficulty - total)


def invest_price(shortfall_points: int, level: int) -> int:
    return shortfall_points * level * INVEST_COST_FACTOR
