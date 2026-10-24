# Universal preliminary balance — 2026-10-24

This is a reproducible prototype audit, not a universal balance proof. All item coefficients and budgets below are provisional designer proposals.

Seed: 47. Probabilities and means are exact fractions; no model/provider calls.

## Explicit provisional configuration

| Status | Damage multiplier route | Shared flat attack + damage budget route |
|---|---:|---:|
| common | 1 | 0 |
| rare | 5/4 | 1 |
| unique | 3/2 | 2 |
| epic | 2 | 3 |

These modest ordered steps distinguish four statuses while keeping epic at 2x. Choose one route: any flat attack/damage bonus switches off the rarity multiplier. A rare item cannot receive both +1 damage and 5/4 damage. Noncommon power requires a saved participating item; runtime must verify that item. These budgets cover action attack/damage only; armor/restoration item budgets are deferred to Node3.

Normal/light/strong intensity is 1, 1/2, 2. Base costs are 3L, L, 12L. Cost multiplies by targets, duration and numerical components. Control/defense encode their primary component explicitly; damage/heal have an implicit primary component. Every extra numeric effect costs another full component. Among damage attacks, only normal single-target instant physical weapon_basic without effects is free, and the server must verify equipped weapon provenance. Base dice are 1d4/1d6/1d8; 1d8 requires a saved condition. Bonus effects are 1/2/3 for light/normal/strong. Narrative facts carry no numeric operations. Ordinary checks without an energy key are free only at normal intensity with one target, one step and no effects; magical checks with an energy key pay one primary component. Ordinary trained checks use +2; resistance never inherits it.

## Growth and ordinary common 1d6 outcomes

Start STR8/DEX13/CON14/INT12/WIS15/CHA10. Specialist spends both points each level on WIS. Even build assigns every earned point in fixed STR/DEX/CON/INT/WIS/CHA round-robin order. All use +2 points per level, no level cap, no armor, no item bonus, no defense or healing. Targets mirror each attacker. Fractions below are successful noncritical damage before immunity.

| L | Build | WIS | CON | HP | Energy | Cost | Mean damage | Hit chance | Expected / attempt |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 | specialist | 15 | 14 | 24 | 25 | 3 | 11/2 | 1/2 | 117/40 |
| 1 | even | 15 | 14 | 24 | 25 | 3 | 11/2 | 1/2 | 117/40 |
| 10 | specialist | 33 | 14 | 78 | 430 | 30 | 65/2 | 19/20 | 621/20 |
| 10 | even | 18 | 17 | 81 | 280 | 30 | 51/2 | 1/2 | 517/40 |
| 100 | specialist | 213 | 14 | 618 | 22300 | 300 | 605/2 | 19/20 | 5751/20 |
| 100 | even | 48 | 47 | 651 | 5800 | 300 | 441/2 | 1/2 | 4417/40 |

Natural 1 always misses; natural 20 always hits and doubles only base dice. The expected damage includes misses and criticals. Immunity applies after the minimum damage and remains zero. At fixed A14/CON14, a die4 gives damage6/cost3 at L1 and damage24/cost30 at L10. WIS33 resistance DC21 gives binding90%/65%/45% against DEX14/24/33, after an already successful hit.

## Action economy sensitivity

| L | Build | HP / mean hit | HP / expected attempt | HP / four attackers step |
|---|---|---:|---:|---:|
| 1 | specialist | 48/11 | 320/39 | 80/39 |
| 1 | even | 48/11 | 320/39 | 80/39 |
| 10 | specialist | 12/5 | 520/207 | 130/207 |
| 10 | even | 54/17 | 3240/517 | 810/517 |
| 100 | specialist | 1236/605 | 4120/1917 | 1030/1917 |
| 100 | even | 62/21 | 3720/631 | 930/631 |

HP divided by mean damage is a throughput ratio, not an exact expected time-to-kill. Each committed player step permits one enemy response; a symmetric one-on-one enemy has the same expected damage/attempt shown above. Four allies concentrating attacks can deal four times that damage over four player steps while allowing four responses, subject to the target surviving. This does not simulate initiative, targeting, attrition, healing, party protection or future combat scheduling.

## Flagged automatic checks and impossible resistance

- L100 specialist: trained WIS check DC15 succeeds on every d20
- L100 specialist: DEX resistance to own WIS effect is impossible even on 20
- L100 even: trained WIS check DC15 succeeds on every d20

## Flagged one-shot scenarios

Sweep: all four item statuses and three intensities, same-level mirrored target, full HP, common 1d6 base, no flat bonus, no immunity. Flags include critical-only one-shots and include misses in the rate.

- L1 specialist common/strong: one-shot probability 1/120
- L1 specialist rare/strong: one-shot probability 1/48
- L1 specialist unique/strong: one-shot probability 1/9
- L1 specialist epic/normal: one-shot probability 1/120
- L1 specialist epic/strong: one-shot probability 13/48
- L1 even common/strong: one-shot probability 1/120
- L1 even rare/strong: one-shot probability 1/48
- L1 even unique/strong: one-shot probability 1/9
- L1 even epic/normal: one-shot probability 1/120
- L1 even epic/strong: one-shot probability 13/48
- L10 specialist common/strong: one-shot probability 1/120
- L10 specialist rare/strong: one-shot probability 467/720
- L10 specialist unique/strong: one-shot probability 19/20
- L10 specialist epic/normal: one-shot probability 1/120
- L10 specialist epic/strong: one-shot probability 19/20
- L10 even rare/strong: one-shot probability 1/240
- L10 even unique/strong: one-shot probability 23/120
- L10 even epic/strong: one-shot probability 1/2
- L100 specialist common/strong: one-shot probability 1/120
- L100 specialist rare/strong: one-shot probability 19/20
- L100 specialist unique/strong: one-shot probability 19/20
- L100 specialist epic/normal: one-shot probability 1/120
- L100 specialist epic/strong: one-shot probability 19/20
- L100 even unique/strong: one-shot probability 1/2
- L100 even epic/strong: one-shot probability 1/2

## Seeded illustrative d20 traces

- L1 specialist: [12, 3, 14, 18, 15, 19, 11, 9]
- L1 even: [17, 13, 13, 20, 2, 14, 1, 4]
- L10 specialist: [1, 9, 16, 18, 1, 11, 19, 14]
- L10 even: [8, 8, 17, 17, 12, 15, 8, 2]
- L100 specialist: [18, 12, 12, 20, 11, 18, 19, 7]
- L100 even: [8, 2, 5, 11, 4, 12, 19, 13]

## Limits and next checks

One-shot flags and automatic checks are real risks at high specialization and strong/epic intensity. The quadratic intensity cost limits frequency but does not prevent burst lethality. The report does not establish fair NPC budgets, item drop frequency, armor stacking, area effects, long-duration control, restoration loops, multi-enemy action economy or extended campaign balance. No natural-20 automatic resistance success is assumed. Node4 must extend the sweep and tune provisional coefficients using real saved combat scenarios. No live model behavior or UI was tested by this pure audit.
