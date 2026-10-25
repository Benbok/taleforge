# Natural critical results

User rule: a natural d20 result of 20 is a critical success, and a natural 1 is a critical failure. This explicitly replaces the previous policy under which ordinary checks and resistance rolls used only their modified totals.

The shared check resolver now applies natural extremes before comparison with difficulty. Resistance uses that same resolver. Only the die selected after advantage/disadvantage is critical; a modified total of 20 or 1 is not a natural critical result. Attacks retain their existing critical damage and miss behavior.

Per-target check proof, aggregate results, saved receipts, failure metadata and roll cards carry critical flags. Cards display critical labels and explain why they override the sum/difficulty. New semantic check admissions must predefine separate critical-success and critical-failure descriptions, alongside ordinary results, before rolling. The server selects and saves the actual branch. Older saved two-branch admissions remain readable and use a critical label with their existing consequence; no old receipt is recalculated.

An ordinary listening check does not receive the physical attack's automatic self-injury. Its critical failure uses the predefined observable setback. Existing attack fumble self-damage remains atomic and replay-safe.

Verification: 11 new backend regression cases were observed failing and then passing. They cover low-score natural 20, high-score natural 1, selected/discarded extremes with advantage/disadvantage, modified totals, resistance, saved descriptions, displayed labels and replay without a second roll. Two existing pure-rule assertions were updated because they explicitly encoded the superseded rule. Two frontend critical-label cases were observed failing and then passing.

Final scoped backend suite: **170 passed** (all universal tests, WebSocket suites and focused existing roll/link tests). Full frontend suite: **362 passed**; latest changed-card tests and production build passed. Ruff and diff whitespace checks passed. Existing Vite bundle warnings remain. No paid generation or live forced-dice action was used. Other user frontend edits remain outside this commit.
