# Master context integration fixes — verification

Date: 2026-10-16 (Moscow)

Follow-up review repairs are verified in
`docs/superpowers/reviews/2026-10-16-context-review-repair-verification.md`.
Current working-tree acceptance: **1918 passed, 19 skipped, 35 warnings**;
context evaluator: **12/12 persisted-outcome scenarios in each of three
variants**, exit 0, no mechanical mismatches or instrumentation errors.
The older counts below describe earlier revisions.

## Current status

Tasks 1–6 are implemented and verified in the current `main`. The full suite
is green. This report supersedes the earlier partial 90-pass result and the
pre-fix full-suite failure summary below; those entries remain as historical
evidence only.

No paid model, live game, application restart, or manual user action was run.

## Commits in this pass

- `ef44c73` — actual context assembly and baseline diagnostics
- `fea8f8f` — unresolved intent recovery
- `79aa207` — production decision fact selection
- `9c1634b` — audience-safe narration context
- `bd5ecb6` — explicit initial tool profiles and tool metrics
- `cacbb88` — executable context scenarios and paired packets
- `b896a69` — production effect-shape compatibility, prompt marker/order
  compatibility, and split-party subject scoping

The pre-existing untracked `.tmp_exec_probe` and the plan file remain
untouched.

## Verification evidence

The final runtime integration assertion observes a production decide packet:
selected fact markers occur once each, the retained `scene_table` occurs once,
and the required history block is present. The snapshot is not a complete
replacement for the scene table, so no artificial size reduction is claimed.

The final targeted matrix was:

```text
.venv\Scripts\python.exe -m pytest tests/test_master_context_selection.py tests/test_context_runtime_integration.py tests/test_context_quality.py tests/test_context_eval_variants.py tests/test_turn_efficiency.py -n 0 -q
65 passed, 1 warning
```

The final full run was:

```text
.venv\Scripts\python.exe -m pytest -n 4 -q
1893 passed, 5 skipped, 35 warnings
exit code: 0
```

The earlier partial result below is retained only to explain why the plan was
reopened; it is not the current acceptance result.

Targeted integration set after the final fix:

```text
.venv\Scripts\python.exe -m pytest tests/test_master_context_selection.py tests/test_context_runtime_integration.py tests/test_context_quality.py tests/test_turn_efficiency.py tests/test_intent.py tests/test_memory.py tests/test_whisper.py -n 0 -q
90 passed, 1 warning
```

The focused production regressions for raw effects, shove/grapple, memory,
whisper, and split-party context also pass. `ruff check` and `git diff --check`
pass. `graphify update .` completed successfully.

The full run was executed as requested:

```text
.venv\Scripts\python.exe -m pytest -n 4 -q
1865 passed, 5 skipped, 7 failed, 35 warnings
```

Six failures were fixed in `b896a69`:

- raw `World.effects` rows caused the post-action context snapshot to crash;
- structured prompts lost compatibility markers/order used by integration
  checks;
- split-party decision subjects included an entity from another place;
- related intent, memory, and whisper scenarios then passed again.

The remaining failure is:

```text
tests/test_party_split.py::test_fight_is_only_where_the_foes_are
```

Its websocket wait times out while waiting for the response to `Пью из
фонтана`. The same test also hangs with `-n 0`; no assertion failure or new
context traceback is produced. This is an unresolved orchestration blocker,
so the full-suite gate is not green.

## Measurement limits

The follow-up harness executes all twelve families as full gateway-backed turns
for legacy/v1/revised assembly, with independent persisted-outcome and role
oracles. Historical role violations are explicitly reported; revised has none
in this set. Scripted runs do not measure provider token usage, USD, live latency,
or prose quality. The −40%/−25% targets remain unmeasured.

## Manual-test boundary

Automatic acceptance is now green. The next step is a user-controlled restart
with the updated code and the manual checklist from the follow-up report.
The current campaign has not been reset or used as a mutable A/B fixture.
