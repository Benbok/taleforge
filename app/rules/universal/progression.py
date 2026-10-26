"""Exact uncapped version1 growth. Library editing never calls these operations."""

from bisect import bisect_right

from app.rules.universal.contracts import ABILITY_KEYS, AbilityScores, HeroBudget, UniversalSheet

THRESHOLDS = (
    0,
    300,
    900,
    2700,
    6500,
    14000,
    23000,
    34000,
    48000,
    64000,
    85000,
    100000,
    120000,
    140000,
    165000,
    195000,
    225000,
    265000,
    305000,
    355000,
)


def natural(value, minimum=0):
    if type(value) is not int or value < minimum:
        raise ValueError("Нужно точное целое число в допустимом диапазоне")
    return value


def level_threshold(level):
    natural(level, 1)
    if level <= 20:
        return THRESHOLDS[level - 1]
    n = level - 20
    return 355000 + 50000 * n + 2500 * n * (n + 1)


def level_for_xp(xp):
    natural(xp)
    if xp < 355000:
        return bisect_right(THRESHOLDS, xp)
    low, high = 20, 40
    while level_threshold(high) <= xp:
        high *= 2
    while low + 1 < high:
        middle = (low + high) // 2
        if level_threshold(middle) <= xp:
            low = middle
        else:
            high = middle
    return low


def growth_sheet(value):
    sheet = UniversalSheet.model_validate(value.model_dump())
    budget = sheet.budget or HeroBudget(initial_scores=sheet.abilities)
    if budget.growth_total != 2 * (sheet.level - 1) or sheet.unspent_points != budget.unspent:
        raise ValueError("Бюджет роста не соответствует сохранённому уровню")
    expected = {k: getattr(budget.initial_scores, k) + budget.growth_allocations.get(k, 0) for k in ABILITY_KEYS}
    if expected != sheet.abilities.model_dump():
        raise ValueError("Характеристики не соответствуют бюджету роста")
    return sheet.model_copy(update={"budget": budget})


def grant_xp(sheet, amount):
    natural(amount)
    sheet = growth_sheet(sheet)
    xp = sheet.xp + amount
    level = max(sheet.level, level_for_xp(xp))
    gained = 2 * (level - sheet.level)
    budget = sheet.budget.model_copy(
        update={"growth_total": sheet.budget.growth_total + gained, "unspent": sheet.budget.unspent + gained}
    )
    return UniversalSheet.model_validate(
        {**sheet.model_dump(), "xp": xp, "level": level, "budget": budget, "unspent_points": budget.unspent}
    )


def allocate_points(sheet, allocations):
    sheet = growth_sheet(sheet)
    if not allocations or set(allocations) - set(ABILITY_KEYS):
        raise ValueError("Выберите характеристики")
    for amount in allocations.values():
        natural(amount)
    spent = sum(allocations.values())
    if not 0 < spent <= sheet.budget.unspent:
        raise ValueError("Недостаточно заработанных очков")
    growth = {k: sheet.budget.growth_allocations.get(k, 0) + allocations.get(k, 0) for k in ABILITY_KEYS}
    budget = sheet.budget.model_copy(update={"growth_allocations": growth, "unspent": sheet.budget.unspent - spent})
    scores = AbilityScores(**{k: getattr(budget.initial_scores, k) + growth[k] for k in ABILITY_KEYS})
    return UniversalSheet.model_validate(
        {**sheet.model_dump(), "abilities": scores, "budget": budget, "unspent_points": budget.unspent}
    )
