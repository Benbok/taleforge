"""Reproducible preliminary arithmetic audit, never a universal balance proof.

Run: python -m tools.eval_universal_balance --seed 47 --output report.md
All means/probabilities are exact Fractions. Seed controls illustrative die traces.
"""

from __future__ import annotations

import argparse
from fractions import Fraction
from pathlib import Path

from app.rules.dice import Dice, FixedDice
from app.rules.universal.contracts import ABILITY_KEYS, AbilityScores, HeroDescription, UniversalSheet
from app.rules.universal.mechanics import derive
from app.rules.universal.profiles import (
    INTENSITY_MULTIPLIERS,
    ITEM_BONUS_BUDGETS,
    RARITY_MULTIPLIERS,
    ProfileSpec,
    ResistanceSpec,
    bind_resistance,
    damage_amount,
    resolve_resistance,
    resource_cost,
)


def _build(level: int, build: str) -> UniversalSheet:
    scores = dict(zip(ABILITY_KEYS, (8, 13, 14, 12, 15, 10), strict=True))
    points = 2 * (level - 1)
    if build == "specialist":
        scores["wis"] += points
    else:
        # Stable round-robin order, each point assigned exactly once.
        for index in range(points):
            scores[ABILITY_KEYS[index % len(ABILITY_KEYS)]] += 1
    return UniversalSheet(
        level=level, abilities=AbilityScores(**scores), description=HeroDescription(identity="balance probe")
    )


def _distribution(sheet: UniversalSheet, profile: ProfileSpec, critical=False) -> list[int]:
    sides = int(profile.base_dice[2:])
    rolls = (
        ([a, b] for a in range(1, sides + 1) for b in range(1, sides + 1))
        if critical
        else ([a] for a in range(1, sides + 1))
    )
    return [damage_amount(FixedDice(values), sheet, profile, critical=critical) for values in rolls]


def evaluate_balance(seed: int = 47) -> dict:
    dice = Dice(seed=seed)
    rows, scenarios, automatic, one_shots = [], [], [], []
    for level in (1, 10, 100):
        for build in ("specialist", "even"):
            sheet = _build(level, build)
            derived = derive(sheet, [])
            p = ProfileSpec(id="probe", attribute="wis", kind="damage")
            amounts = _distribution(sheet, p)
            criticals = _distribution(sheet, p, critical=True)
            mean = Fraction(sum(amounts), len(amounts))
            mean_critical = Fraction(sum(criticals), len(criticals))
            mod = derived.modifiers["wis"]
            hits = sum(die != 1 and (die == 20 or die + mod >= derived.ac) for die in range(1, 21))
            expected = Fraction(hits - 1, 20) * mean + Fraction(1, 20) * mean_critical
            spec = bind_resistance(ResistanceSpec(source_attribute="wis", attribute="dex"), sheet.abilities.wis)
            binding = sum(
                resolve_resistance(FixedDice([d]), "target", "bind", sheet.abilities.dex, spec).applied
                for d in range(1, 21)
            )
            if 1 + mod + 2 >= 15:
                automatic.append(f"L{level} {build}: trained WIS check DC15 succeeds on every d20")
            if 20 + derived.modifiers["dex"] < spec.difficulty:
                automatic.append(f"L{level} {build}: DEX resistance to own WIS effect is impossible even on 20")
            row = {
                "level": level,
                "build": build,
                "growth_points": str(2 * (level - 1)),
                "wis": str(sheet.abilities.wis),
                "con": str(sheet.abilities.con),
                "dex": str(sheet.abilities.dex),
                "hp": str(derived.hp_max),
                "ac": str(derived.ac),
                "energy": str(derived.energy_max["wis"]),
                "cost": str(resource_cost(p, level)),
                "mean_damage": str(mean),
                "mean_critical_damage": str(mean_critical),
                "damage_range": [str(min(amounts)), str(max(amounts))],
                "hit_probability": str(Fraction(hits, 20)),
                "expected_damage_per_attempt": str(expected),
                "binding_probability_after_hit": str(Fraction(binding, 20)),
                "hp_over_mean_hit": str(Fraction(derived.hp_max) / mean),
                "hp_over_expected_attempt": str(Fraction(derived.hp_max) / expected),
                "group4_hp_over_expected_step": str(Fraction(derived.hp_max) / (4 * expected)),
                "sample_d20": [dice.d20() for _ in range(8)],
            }
            rows.append(row)
            for rarity in RARITY_MULTIPLIERS:
                for intensity in INTENSITY_MULTIPLIERS:
                    scenario = ProfileSpec(
                        id="probe",
                        attribute="wis",
                        kind="damage",
                        rarity=rarity,
                        intensity=intensity,
                        item_id=None if rarity == "common" else "probe-item",
                    )
                    values = _distribution(sheet, scenario)
                    crit_values = _distribution(sheet, scenario, critical=True)
                    # Include attack misses and natural-20 criticals in the one-shot rate.
                    one_shot = Fraction(hits - 1, 20) * Fraction(
                        sum(v >= derived.hp_max for v in values), len(values)
                    ) + Fraction(1, 20) * Fraction(sum(v >= derived.hp_max for v in crit_values), len(crit_values))
                    scenarios.append(
                        {
                            "level": level,
                            "build": build,
                            "rarity": rarity,
                            "intensity": intensity,
                            "mean_damage": str(Fraction(sum(values), len(values))),
                            "max_damage": str(max(values)),
                            "cost": str(resource_cost(scenario, level)),
                            "one_shot_probability_per_attempt": str(one_shot),
                        }
                    )
                    if one_shot:
                        one_shots.append(f"L{level} {build} {rarity}/{intensity}: one-shot probability {one_shot}")
    source = bind_resistance(ResistanceSpec(source_attribute="wis", attribute="dex"), 33)
    percentages = {
        str(score): str(
            5 * sum(resolve_resistance(FixedDice([d]), "t", "e", score, source).applied for d in range(1, 21))
        )
        for score in (14, 24, 33)
    }
    return {
        "seed": seed,
        "levels": [1, 10, 100],
        "rows": rows,
        "scenarios": scenarios,
        "resistance_binding_percent": percentages,
        "flags": {"automatic_checks": automatic, "one_shots": one_shots},
    }


def render_report(result: dict) -> str:
    lines = [
        "# Universal preliminary balance — 2026-10-24",
        "",
        "This is a reproducible prototype audit, not a universal balance proof. "
        "All item coefficients and budgets below are provisional designer proposals.",
        "",
        f"Seed: {result['seed']}. Probabilities and means are exact fractions; no model/provider calls.",
        "",
        "## Explicit provisional configuration",
        "",
        "| Status | Damage multiplier route | Shared flat attack + damage budget route |",
        "|---|---:|---:|",
    ]
    for rarity, multiplier in RARITY_MULTIPLIERS.items():
        lines.append(f"| {rarity} | {multiplier} | {ITEM_BONUS_BUDGETS[rarity]} |")
    lines += [
        "",
        "These modest ordered steps distinguish four statuses while keeping epic at 2x. "
        "Choose one route: any flat attack/damage bonus switches off the rarity multiplier. "
        "A rare item cannot receive both +1 damage and 5/4 damage. "
        "Noncommon power requires a saved participating item; runtime must verify that item. "
        "These budgets cover action attack/damage only; armor/restoration item budgets are deferred to Node3.",
        "",
        "Normal/light/strong intensity is 1, 1/2, 2. Base costs are 3L, L, 12L. "
        "Cost multiplies by targets, duration and numerical components. "
        "Control/defense encode their primary component explicitly; damage/heal have an implicit primary component. "
        "Every extra numeric effect costs another full component. Among damage attacks, only normal "
        "single-target instant physical weapon_basic without effects is free, "
        "and the server must verify equipped weapon provenance. "
        "Base dice are 1d4/1d6/1d8; 1d8 requires a saved condition. "
        "Bonus effects are 1/2/3 for light/normal/strong. "
        "Narrative facts carry no numeric operations. Ordinary checks without an energy key are free "
        "only at normal intensity with one target, one step and no effects; magical checks with an energy key "
        "pay one primary component. Ordinary trained checks use +2; "
        "resistance never inherits it.",
        "",
        "## Growth and ordinary common 1d6 outcomes",
        "",
        "Start STR8/DEX13/CON14/INT12/WIS15/CHA10. Specialist spends both points each level on WIS. "
        "Even build assigns every earned point in fixed STR/DEX/CON/INT/WIS/CHA round-robin order. "
        "All use +2 points per level, no level cap, no armor, no item bonus, no defense or healing. "
        "Targets mirror each attacker. Fractions below are successful noncritical damage before immunity.",
        "",
        "| L | Build | WIS | CON | HP | Energy | Cost | Mean damage | Hit chance | Expected / attempt |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in result["rows"]:
        lines.append(
            "| "
            + " | ".join(
                str(row[k])
                for k in (
                    "level",
                    "build",
                    "wis",
                    "con",
                    "hp",
                    "energy",
                    "cost",
                    "mean_damage",
                    "hit_probability",
                    "expected_damage_per_attempt",
                )
            )
            + " |"
        )
    lines += [
        "",
        "Natural 1 always misses; natural 20 always hits and doubles only base dice. "
        "The expected damage includes misses and criticals. "
        "Immunity applies after the minimum damage and remains zero. "
        "At fixed A14/CON14, a die4 gives damage6/cost3 at L1 and damage24/cost30 at L10. "
        "WIS33 resistance DC21 gives binding90%/65%/45% against DEX14/24/33, after an already successful hit.",
        "",
        "## Action economy sensitivity",
        "",
        "| L | Build | HP / mean hit | HP / expected attempt | HP / four attackers step |",
        "|---|---|---:|---:|---:|",
    ]
    for row in result["rows"]:
        lines.append(
            "| "
            + " | ".join(
                str(row[k])
                for k in (
                    "level",
                    "build",
                    "hp_over_mean_hit",
                    "hp_over_expected_attempt",
                    "group4_hp_over_expected_step",
                )
            )
            + " |"
        )
    lines += [
        "",
        "HP divided by mean damage is a throughput ratio, not an exact expected time-to-kill. "
        "Each committed player step permits one enemy response; a symmetric one-on-one enemy has the same expected "
        "damage/attempt shown above. Four allies concentrating attacks can deal four times that damage over four "
        "player steps while allowing four responses, subject to the target surviving. "
        "This does not simulate initiative, targeting, attrition, healing, party protection "
        "or future combat scheduling.",
        "",
        "## Flagged automatic checks and impossible resistance",
        "",
    ]
    lines.extend("- " + flag for flag in result["flags"]["automatic_checks"])
    lines += [
        "",
        "## Flagged one-shot scenarios",
        "",
        "Sweep: all four item statuses and three intensities, same-level mirrored target, "
        "full HP, common 1d6 base, no flat bonus, no immunity. "
        "Flags include critical-only one-shots and include misses in the rate.",
        "",
    ]
    lines.extend("- " + flag for flag in result["flags"]["one_shots"])
    lines += ["", "## Seeded illustrative d20 traces", ""]
    for row in result["rows"]:
        lines.append(f"- L{row['level']} {row['build']}: {row['sample_d20']}")
    lines += [
        "",
        "## Limits and next checks",
        "",
        "One-shot flags and automatic checks are real risks at high specialization and strong/epic intensity. "
        "The quadratic intensity cost limits frequency but does not prevent burst lethality. "
        "The report does not establish fair NPC budgets, item drop frequency, armor stacking, area effects, "
        "long-duration control, restoration loops, multi-enemy action economy or extended campaign balance. "
        "No natural-20 automatic resistance success is assumed. "
        "Node4 must extend the sweep and tune provisional coefficients using real saved combat scenarios. "
        "No live model behavior or UI was tested by this pure audit.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=47)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = render_report(evaluate_balance(args.seed))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    else:
        print(report)


if __name__ == "__main__":
    main()
