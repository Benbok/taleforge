# LLM turn efficiency: implementation and verification

## Task 1: telemetry

Baseline from the Docker PostgreSQL database, read-only, before behavior changes:
144 calls, $0.484081 stored estimate; 3,492,007 prompt tokens and 19,603 output tokens.
16 done turns, 1 failed. Cutoff: 2026-10-15T14:05:08.104446+00:00 (17:05:08 Moscow).
Matches the design baseline exactly. All 144 historical rows have unknown cache and price coverage;
the stored cost total is not evidence of full price coverage. Parse without turn_id stays visible.

Automated verification: 21 telemetry/report tests passed; 50 focused regression tests passed.
SQLite migration upgrade/downgrade passed, preserving historical NULL fields.
PostgreSQL 16 migration 0031 upgrade/downgrade passed in the isolated database
`taleforge_llm_coverage_test_20261015`, preserving the historical row.
During the initial offline stage the live database was not migrated or restarted. The initial targeted telemetry
checks used scripted replies. See the full-suite incident below for later provider invocations.

Pre-existing lint issues: five E501 lines in app/core/map_memory.py, one import ordering issue
in app/core/world_tx.py, and twelve fixture-name F811 reports in tests/test_companions.py.
Confirmed against cc392eb; no changes made to those unrelated files.

## Human verification

Manual testing started on 2026-10-16 in campaign `c_45d44d2e512123f3` (Тест затрат).
All six flags were explicitly enabled at the user's request at 05:03:31 UTC (08:03:31 Moscow).
The activation snapshot records 237 calls and $0.79253886 stored cost before activation.
This is an observational test on different actions, not a controlled paired benchmark.

Independent Task 1 review found three issues (zero-price repricing, omitted function-call sizes, phase classification); all fixed with regression tests. Real world-transaction rollback also preserves tokens/cache/price and invalid-output audit in the independent call writer.

## Implemented behavior (Tasks 2–7)

All six `llm_optimization` flags default to false and can be changed independently:
`action_refs`, `tool_profiles`, `role_context`, `early_finish`, `compact_voice`, `compact_review`.
Existing campaigns retain their stored settings. Dispatcher ownership checks also protect
the legacy path; read-only calls ignore surplus action references.

- Real action references include pending/denied/dependent parts; invented references get
  one correction, then stop without applying remaining batch mutations.
- Decision tools use permission-filtered stable profiles with explicit general expansion.
- Role prompts separate mechanics/private context from public narration. Missing/uncertain
  context falls back to the complete legacy path rather than truncating actions.
- Early completion checks terminal parts, every required actor and pending obligations;
  independent search evidence is required. Turn checkpoint/NPC/world-clock tail remains.
- Voice uses a compact parallel request only when LINE is enabled. Thinking is disabled
  only for verified Gemini 2.5 Flash/Flash-Lite IDs; unknown models retain default.
- Compact character review requires the review tool and allows two responses. Attempt IDs,
  persisted lifecycle events, admission rechecks and UI polling handle retries/restarts.

Targeted evidence: profiles 31 passed; context/visibility 27 passed; completion 41 passed,
1 PostgreSQL-only skipped; voice/TTS/accounting 63 passed; review/admission 44 passed,
then review cleanup 9 passed; contract freshness 2 passed. Both UI retry paths pass.

## Full-suite isolation incident

The first full server run finished with 1702 passed, 1 failed, 5 skipped. An existing
layout-pilot test omitted its usual background-master suppression fixture and invoked
Gemini three distinct times (warnings were duplicated in captured stderr/log output).
The test failed on SQLite locking caused by the unexpected background work. These logs
do not establish successful responses or billing; the original temporary database is no
longer available, so exact usage cannot be recovered. This was disclosed during execution.

The pilot now imports the existing suppression fixture. A suite-wide autouse provider
guard rejects real `litellm.acompletion` calls; deliberate test mocks can replace it.
Direct provider and real-client escape regressions pass. All subsequent test runs use
this guard. Later deployment and flag activation were separately authorized by the user.

## Review decisions and limits

Independent reviews covered telemetry, references and character-review lifecycle;
Important findings were corrected. After temporary auxiliary model unavailability,
a final independent integration review also covered tool profiles, role context,
completion and voice. It identified DB-session lifetime/concurrent access in compact
narration/voice prompt assembly; the correction prepares a detached context snapshot
before closing the owned session.

- Compact narration omits private offscreen plot notes; human evaluation must check that
  public prose still supplies sufficient hints. Common-audience known facts remain.
- Failed spawn/transition history conservatively keeps the extra decision request even
  after a repair. This can reduce savings but preserves unresolved-work handling.
- A duplicate review during the brief campaign claim lock can receive 409; retries during
  model waiting share one attempt. It cannot create a parallel paid review task.
- Size estimates are chars/4 rounded up, not provider usage. Scripted results cannot
  establish cache savings, actual prices or literary quality.

## Offline comparison (Task 8)

The scripted CLI passed all 26 named scenarios (27 collected subcases) in each variant:
27 passed, 0 failed, 0 skipped; no mechanical snapshot mismatches. Six fixtures execute
complete master turns; the remaining twenty exercise real tools or visibility directly.
Generation root seed is fixed to 0 in the evaluator, including container loot.

| Recorded purpose | Legacy | Optimized |
| --- | ---: | ---: |
| parse | 6 | 6 |
| decide | 8 | 4 |
| emotion | 6 | 6 |
| narrate | 6 | 6 |
| total | 26 | 22 |

Optimized prompt fallback count is 3 (legacy 0). All 26/22 scripted usages remain
unknown for real prices; costs/cache/literary quality are not inferred. This is
orchestration evidence on fixed replies, not a measured cost-reduction percentage.
Durable machine-readable evidence: `2026-10-15-llm-turn-efficiency-scripted.json`.
Runner safety/paired-turn tests: 27 passed. Live was not performed.

## Manual handoff requirements

Migration 0031 and application deployment were applied at the user's request after
the offline handoff. Use an isolated test campaign for a controlled paid comparison,
with an explicit budget. Keep model, seed, world and voice settings identical between
legacy and optimized runs. Enable flags separately, recording turn completeness,
failed/fallback rates, actual cache/price coverage and p50/p95, plus paired human ratings
of atmosphere, continuity and initiative. Disable an individual flag to roll it back.

For the checked-in Docker setup, the manual application command is
`docker compose up -d --build app`: the rebuilt image includes migration 0031 and
its startup command runs `alembic upgrade head`. The local frontend build has
already been produced. This command was executed at the user's explicit request.

Campaign flags can be changed through `PATCH /api/campaigns/{id}` with, for example,
`{"llm_optimization":{"action_refs":true}}`. Start with an isolated campaign;
then add `tool_profiles`, `role_context`, `early_finish`, `compact_voice`,
`compact_review` separately. Supply the desired complete flag object when editing
it; unspecified flags default to false. Retain the previous object for rollback.

The targets of 40% lower cost and 25% lower median latency remain unverified.

## Manual testing findings, 2026-10-16

At the latest recorded checkpoint: 24 optimized turns versus 10 recent legacy turns.
Attributed mean cost per turn: $0.010061 versus $0.029759; mean decide requests:
1.83 versus 4.10; median duration: 10.38 versus 13.94 seconds. These observational
reductions (about 66% cost, 26% median duration) do not establish the targets because
actions differ and seven optimized turns recorded automatic cancellation. The
optimized interval spent $0.27056 including parse/background calls; campaign total
was $1.06310. LLM API errors and gameplay-tool failures are distinct metrics.

Two gameplay defects were reproduced and corrected:

- `382f278`: accepted adjudication left pending progress, causing a later cancellation.
  Completion and replay now persist the exact part result. Targeted suite: 54 passed,
  2 skipped; full scripted conversation regression included.
- `0ce55a4`: recognized spoken requests with no parsed parts exposed no real reference.
  Under action_refs, confident speech gets a durable talk part. Missing/uncertain
  parsing remains unbound. Targeted suite: 79 passed. Both fixes deployed and checked
  in the running container; old cancelled turns were not replayed automatically.

Web verification: 235 tests passed; production build/typecheck passed. Changed Python
files pass Ruff; the 18 baseline issues above remain. The first broad integration run
after the initial suite had 1801 passed, 5 failed, 5 skipped: four failures came from
runner tests collected while their source was changing, and one synthetic binding
fixture lacked new ownership fields. These were corrected and scoped reruns passed.
The subsequent full-suite log stops at 35% with no final result retained; a complete
green full-suite result is therefore not claimed.

The user chose to continue manual testing in a new campaign. New campaigns retain
default-false optimization flags until explicitly enabled for their campaign ID.

Offline replay command:

```powershell
.venv\Scripts\python.exe -m tools.eval_turn_efficiency --mode scripted --cases tests/fixtures/turn_efficiency.json --output .tmp/turn-efficiency-scripted.json
```

The live CLI supports one paired attack in newly created disposable SQLite worlds.
`--campaign` labels the evaluation; it never looks up or mutates an existing game.
It requires `--isolated-test-campaign`, `--model`, `--max-cost-usd` and
`--max-request-cost-usd`. The latter reserves a conservative amount before every
request; actual provider billing can exceed that reservation for an in-flight call.
Returned usage is journalled before another request is admitted. Unknown prices or
provider failures stop further spending. No default budget is supplied.

This narrow driver keeps parser and dice fixed and voice disabled; it does not replace
the broad campaign, cold/warm cache and paired prose-quality checks above.
