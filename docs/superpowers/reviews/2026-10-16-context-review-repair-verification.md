# Context review repair verification

Date: 2026-10-16 (Moscow)

Status: automatic acceptance passed on base commit `0c98050` plus the current
working-tree changes (not committed). Scenario manifest SHA-256:
`3003c99ffc1a2ce5b02acd1aca4bf3383060d8759b5a8a4d520a118ce0589cad`.

## Changes verified in this follow-up

- Narration location facts now use the validated public scene presentation;
  private location state does not enter the selected narration packet. A real
  turn test intercepts the narration request without substituting the snapshot.
- Routes use `location_exits`, the same topology as the map. Secret destinations
  require knowledge or a visit for every listener. Shared place facts are limited
  to a common listener location.
- Template narrative facts retain their instance subjects, so selecting a nearby
  NPC also retains its template properties and dependency closure.
- Scenario captures keep actual call purposes. Missing roles, required facts,
  leaks, and misrouted evidence fail independent assertions.
- All twelve scenario families create persisted world state and validate actual
  events/progress/ownership/knowledge/visibility, including interrupted narration
  resumed from a checkpoint. Removing the intended event invalidates the oracle.
  Multipart covers two ordered discoveries; a separate parser regression covers
  move-before-attack in an existing fight.
- Fixed an additional production parser bug: selecting one main action and one
  movement action no longer changes their original order when no part is dropped.
  Selection uses object identity so equal duplicate parts cannot bypass the limit.
- Evaluator variants dispatch at `build_prompt_bundle`, preserve tool protocol,
  and use a pinned historical assembler/templates from `dbfdc65` for legacy/v1.
  Provenance is in `tools/context_eval_history/provenance.json`.
- Input measurements describe actual dispatched messages/tools, with parsing
  reported separately. Tools comparisons really select full/profile tools.
  Outcome mismatches and instrumentation errors remain failures.

## Verification

- Snapshot/narration/layout/runtime matrix: 34 passed.
- Final intent/action-binding/multipart/context-quality matrix: 53 passed.
- Scenario worker matrix: 27 passed, including six parser recovery variations.
- Ruff on all changed Python files: exit 0.
- `graphify update .`: exit 0, 11,212 nodes / 35,142 edges.
- Context evaluator: 12/12 persisted-outcome scenarios passed in each of legacy,
  v1, and revised (36 total); CLI exit 0, no mechanical mismatches and no
  instrumentation errors. Baseline role-quality violations: legacy 2, v1 1;
  revised 0. Machine-readable report: `.superpowers/context-evaluator-review-final.json`.
- Final full suite: `.venv\Scripts\python.exe -m pytest -n 8 -q --junitxml=.superpowers/context-review-acceptance.xml`
  — **1918 passed, 19 skipped, 35 warnings**, exit 0, 454.17 seconds.
  The eight workers use half the host's sixteen logical processors. Fourteen
  skips are evaluator-only entry points, exercised separately by their isolated
  driver; five are existing skips. None of the twelve revised scenario families
  is skipped. Earlier full runs stopped for parser changes are not passes.
- Independent production-diff review: duplicate-part regression found, fixed
  with a red/green test, re-reviewed with no remaining findings.

## Scope of comparison

Historical assembly runs over the same current world inputs, action ownership,
mechanics, and completion policy. This is not a replay of the entire historical
runtime. Baseline privacy/recall violations are reported as baseline violations;
revised must pass the full role oracle. Historical assemblers are not required
to emit newly introduced selector diagnostics, but their world outcomes and refs
use the same assertions as revised.

Scripted results verify behavior and packet composition. They do not measure
provider tokens, paid cost, model prose quality, or live latency. No paid model,
application restart, or user campaign mutation was performed.

## Manual handoff

After the full automatic checks pass, restart with the updated code and test the
current campaign's inspection, doorway exit, and old promise; then test a new
campaign's start, dialogue, multipart request, and transition. Keep paid A/B prose
and spending measurement separate, with an agreed budget.
