"""Versioned growth sweep, using real earned budgets, equipment and combat arithmetic."""

from fractions import Fraction

from app.rules.dice import Dice, FixedDice
from app.rules.universal.contracts import ABILITY_KEYS, ENERGY_KEYS, UniversalSheet
from app.rules.universal.exploration import AbilityDefinitionV2, EffectIntentV2, exploration_cost
from app.rules.universal.items import ItemProfile, item_attack_profile
from app.rules.universal.mechanics import derive
from app.rules.universal.profiles import ProfileSpec, damage_amount, resolve_check, resource_cost
from app.rules.universal.progression import allocate_points, grant_xp, growth_sheet, level_threshold


def actual_build(level, allocation):
    if allocation not in {"str", "dex", "con", "wis", "even", "specialist"}:
        raise ValueError("Unknown build")
    key = "wis" if allocation == "specialist" else allocation
    scores = dict(zip(ABILITY_KEYS, (8, 13, 14, 12, 15, 10), strict=True))
    if key in ABILITY_KEYS:
        scores[key], scores["wis"] = scores["wis"], scores[key]
    sheet = grant_xp(
        UniversalSheet(abilities=scores, description={"identity": "balance probe"}), level_threshold(level)
    )
    points = 2 * (level - 1)
    if points:
        allocations = (
            {key: points} if key != "even" else {k: points // 6 + (i < points % 6) for i, k in enumerate(ABILITY_KEYS)}
        )
        sheet = allocate_points(sheet, allocations)
    return growth_sheet(sheet)


def distribution(sheet, profile, critical=False):
    sides = int(profile.base_dice[2:])
    rolls = (
        ([a, b] for a in range(1, sides + 1) for b in range(1, sides + 1))
        if critical
        else ([a] for a in range(1, sides + 1))
    )
    return sorted(damage_amount(FixedDice(values), sheet, profile, critical=critical) for values in rolls)


def chance(score, difficulty):
    return Fraction(sum(resolve_check(FixedDice([d]), score, False, difficulty).success for d in range(1, 21)), 20)


def simulate_build(level, allocation, seed=47):
    dice = Dice(seed)
    sheet = actual_build(level, allocation)
    derived = derive(sheet, [1])
    attribute = allocation if allocation in {"str", "dex", "wis"} else "wis"
    profile = ProfileSpec(id="audit", attribute=attribute, kind="damage")
    values = distribution(sheet, profile)
    crit = distribution(sheet, profile, True)
    mean = Fraction(sum(values), len(values))
    critical_mean = Fraction(sum(crit), len(crit))
    cost = resource_cost(profile, level)
    opponents = []
    for opposing in ("even", "con", "dex"):
        target = actual_build(level, opposing)
        defense = derive(target, [1])
        hit = chance(getattr(sheet.abilities, attribute), defense.ac)
        expected = (hit - Fraction(1, 20)) * mean + Fraction(1, 20) * critical_mean
        oneshot = (hit - Fraction(1, 20)) * Fraction(sum(v >= defense.hp_max for v in values), len(values)) + Fraction(
            1, 20
        ) * Fraction(sum(v >= defense.hp_max for v in crit), len(crit))
        control = 1 - chance(target.abilities.dex, 10 + derived.modifiers[attribute])
        retaliation = chance(target.abilities.str, derived.ac)
        enemy_profile = ProfileSpec(id="opposing", attribute="str", kind="damage", use_kind="weapon_basic")
        enemy_values = distribution(target, enemy_profile)
        enemy_crit = distribution(target, enemy_profile, True)
        enemy_expected = (retaliation - Fraction(1, 20)) * Fraction(sum(enemy_values), len(enemy_values)) + Fraction(
            1, 20
        ) * Fraction(sum(enemy_crit), len(enemy_crit))
        opponents.append(
            dict(
                build=opposing,
                hp=str(defense.hp_max),
                ac=str(defense.ac),
                hit_chance=str(hit),
                control_chance_after_hit=str(control),
                expected_damage=str(expected),
                one_shot_chance=str(oneshot),
                expected_opposing_actions_to_zero=str(Fraction(derived.hp_max) / enemy_expected),
            )
        )
    rarity = []
    for status, budget in [("common", 0), ("rare", 1), ("unique", 2), ("epic", 3)]:
        for variant in ("flat", "multiplier"):
            bonus = budget if variant == "flat" else 0
            item = ItemProfile(
                name=status,
                kind="weapon",
                status=status,
                attribute="dex" if allocation == "dex" else "str",
                attack_bonus=bonus,
            )
            weapon = item_attack_profile(item, "audit")
            damages = distribution(sheet, weapon)
            criticals = distribution(sheet, weapon, True)
            one_shots = []
            for opposing in ("even", "con", "dex"):
                defense = derive(actual_build(level, opposing), [1])
                hit = chance(getattr(sheet.abilities, item.attribute), defense.ac - bonus)
                risk = (hit - Fraction(1, 20)) * Fraction(sum(v >= defense.hp_max for v in damages), len(damages))
                risk += Fraction(1, 20) * Fraction(sum(v >= defense.hp_max for v in criticals), len(criticals))
                one_shots.append(risk)
            rarity.append(
                dict(
                    status=status,
                    variant=variant,
                    attack_bonus=str(bonus),
                    damage_range=[str(min(damages)), str(max(damages))],
                    max_one_shot_chance=str(max(one_shots)),
                    flat_bonus_disables_multiplier=bool(bonus),
                    energy_cost=str(resource_cost(weapon, level)),
                )
            )
    magic = []
    for intensity in ("light", "normal", "strong"):
        p = ProfileSpec(id="spell", kind="damage", attribute=attribute, intensity=intensity)
        vals = distribution(sheet, p)
        magic.append(
            dict(
                intensity=intensity,
                cost=str(resource_cost(p, level)),
                casts=str(derived.energy_max[attribute] // resource_cost(p, level)),
                damage_range=[str(min(vals)), str(max(vals))],
            )
        )
    area = AbilityDefinitionV2(
        name="audit area",
        intensity="normal",
        source="supernatural",
        attribute=attribute,
        target_count=4,
        effects=[EffectIntentV2(kind="damage")],
    )
    binding = AbilityDefinitionV2(
        name="audit bind",
        intensity="normal",
        source="supernatural",
        attribute=attribute,
        effects=[EffectIntentV2(kind="cannot_move")],
    )
    combined = Fraction(0)
    for pool in ENERGY_KEYS:
        p = ProfileSpec(id="reserve", kind="damage", attribute=pool)
        vals = distribution(sheet, p)
        combined += (derived.energy_max[pool] // resource_cost(p, level)) * Fraction(sum(vals), len(vals))
    return dict(
        level=str(level),
        build=allocation,
        allocated_points=str(sum(sheet.budget.growth_allocations.values())),
        budget_verified=sheet.budget.unspent == 0,
        abilities=sheet.abilities.model_dump(mode="json"),
        hp=str(derived.hp_max),
        ac=str(derived.ac),
        energies={k: str(v) for k, v in derived.energy_max.items()},
        damage_quantiles={"min": str(values[0]), "median": str(values[len(values) // 2]), "max": str(values[-1])},
        opponents=opponents,
        rarity=rarity,
        intensities=magic,
        multi_target_cost=str(exploration_cost(area, level)),
        timed_control_cost=str(exploration_cost(binding, level)),
        heal_per_energy=str(min(mean, derived.hp_max) / cost),
        combined_paid_reserve_damage=str(combined),
        weapon_when_empty={"energy_cost": "0", "available": True},
        sample_d20=[dice.d20() for _ in range(8)],
    )


def growth_report(seed=47):
    rows = [
        simulate_build(level, build, seed)
        for level in (1, 10, 20, 100, 1000)
        for build in ("str", "dex", "con", "wis", "even")
    ]
    flags = []
    for row in rows:
        for weapon in row["rarity"]:
            if Fraction(weapon["max_one_shot_chance"]) > 0:
                flags.append(
                    f"L{row['level']} {row['build']} {weapon['status']}/{weapon['variant']}: "
                    f"weapon one-shot risk {weapon['max_one_shot_chance']}"
                )
        for opponent in row["opponents"]:
            if opponent["hit_chance"] in {"1/20", "19/20"}:
                flags.append(
                    f"L{row['level']} {row['build']} vs {opponent['build']}: "
                    f"accuracy reaches natural-die bound {opponent['hit_chance']}"
                )
            if Fraction(opponent["one_shot_chance"]) > 0:
                flags.append(
                    f"L{row['level']} {row['build']} vs {opponent['build']}: "
                    f"one-shot risk {opponent['one_shot_chance']}"
                )
    return dict(
        rules_version="universal.v1",
        seed=seed,
        levels=[1, 10, 20, 100, 1000],
        rows=rows,
        flags=flags,
        provisional=True,
        notes=[
            "Exact arithmetic audit, not a balance proof or live model evaluation.",
            "Natural20/1 bounds remain; high specialization can make other outcomes rare.",
            "Resource-rich specialists and burst damage remain prototype tradeoffs.",
            "One eligible enemy reply per action; no grid/classes/XP cap.",
            "Compare balance-preliminary.md from Node2; this sweep uses saved-growth "
            "arithmetic and real item profiles.",
        ],
    )
