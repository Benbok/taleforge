# Master context integration fixes — verification

Date: 2026-10-16 (Moscow)

## Current status

Tasks 1–5 are implemented and committed. Task 6 has an executable offline
scenario harness and paired context packets, but it is not yet a full
orchestrator A/B measurement. Task 7 is not complete: the full suite exposed
one remaining split-party websocket timeout.

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

The scenario harness verifies required/forbidden facts and compares a revised
packet with an explicit legacy packet. It does not yet execute all 12 scenarios
as full real-turn baseline/revised runs, and no provider token, USD, latency,
or prose-quality claim is made. The −40%/−25% targets remain unmeasured.

## Manual-test boundary

Do not restart the app or run the requested manual game scenarios yet. First
resolve or explicitly quarantine the split-party websocket timeout, rerun the
full suite, and then hand off the manual checklist from the plan.
