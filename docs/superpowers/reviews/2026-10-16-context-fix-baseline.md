# Master context integration baseline

Date: 2026-10-16 (Moscow)

## Scope

This is an offline diagnostic baseline for Task 1 of
`docs/superpowers/plans/2026-10-16-master-context-integration-fixes.md`.
It does not claim a paid-model comparison or a quality result.

## Source and verification

- Starting commit: `dbfdc65add2dacb590996878df3bf874aa1fc579`
- Targeted command: `.venv\Scripts\python.exe -m pytest tests/test_context_runtime_integration.py tests/test_master_prompt_context.py -n 0 -q`
- Result: `11 passed`
- The runtime integration test intercepts `llm.complete` and compares diagnostics with the exact serialized `messages` and `tools` arguments.
- Estimated sizes use `chars/4-ceil`; they are not provider token usage.

## Measured role-block baseline

The scripted role-context fixture reported:

| Role | Instructions | Other blocks | Estimated input |
|---|---:|---:|---:|
| decide | 19,143 chars / 32,606 UTF-8 bytes | 110 policy, 62 canon, 55 actions, 180 difficulty, 38 request | 4,786 tokens |
| narrate | 772 chars / 1,398 UTF-8 bytes | 110 policy, 16 request | 193 tokens |

The empty tool list serializes to 2 characters and 1 estimated token in this fixture. Actual per-call `messages/tools` sizes remain authoritative; logical block totals must not be added to them a second time.

## Previously observed live evidence

The source observation recorded in the plan covered four decide turns:

- two used the legacy path because of uncertain intent;
- two used the legacy path because of the soft budget;
- the calls were labeled `role-context-v1`, so the label alone did not prove that selection was applied;
- tool schemas were approximately 31k estimated tokens across three turns and 14k in one turn;
- parse calls and their costs were tracked separately; the cost of the failed parse was unknown.

These observations are not a control group and are not re-priced here.

## Diagnostic contract

Each persisted `LlmCall.diagnostics` row now records the path metadata without prompt text, refs, or provider signatures:

- `assembly_path`: `selected`, `expanded`, or `legacy`;
- `selection_applied`: boolean;
- `expansion_reasons`: bounded reason labels;
- `retry_count` and de-duplicated `retry_reasons`;
- sizes calculated from the actual call arguments.

Unknown provider usage, cache coverage, and price remain unknown unless supplied by the provider response.
