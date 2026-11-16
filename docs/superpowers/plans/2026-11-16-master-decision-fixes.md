# Master decision fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove five defects in the universal master's decide/review path: structured-call temperature, the never-firing rewards module, crash on unparsable review JSON, brittle quote matching, and one shared retry budget.

**Architecture:** All changes stay inside the existing pipeline: `_call` in `app/agents/master/universal.py`, module predicates in `app/agents/master/prompting/modules.py`, the decide loop and narration review in `app/agents/master/exploration.py`, quote checks in `app/core/universal/interpretation.py`. No schema or DB changes; new state lives in the turn trace.

**Tech Stack:** Python 3.12, pydantic, SQLAlchemy async, pytest (tests run via `asyncio.run`, fake `Provider` from `tests/test_universal_master.py`).

**Spec:** `docs/superpowers/specs/2026-11-16-master-decision-fixes-design.md`

## Global Constraints

- Structured purposes: `decide`, `exploration_decide`, `intent_review`, `narration_review`, `world_prepare`, `world_review` → temperature `0.2`; narration keeps `cfg.temperature` or `0.8`.
- Budgets: `lore` 1, `format` 2, `meaning` 1 retries; total cap 4 `exploration_decide` calls per message.
- A budget slot is persisted to the trace **before** the external call (existing invariant).
- `proposal_attempts[mid]` stays the total call count; legacy trace with `proposal_attempts[mid] >= 2` and no `proposal_budgets[mid]` is exhausted.
- An unparsable intent review never becomes `pass`.
- Player-facing text in Russian; code comments in English, matching the file's style.
- After code changes run `graphify update .` (AGENTS.md).

## Review Focus

1. Intent reviewer returns a truncated JSON whose repaired form lacks `verdict` → must count as mismatch, not crash, not pass. (Task 3 test `test_unparsable_intent_review_is_a_mismatch_not_a_pass`.)
2. Crash (provider exception) on the 3rd or 4th decide call, then recovery run → no extra call beyond cap 4. (Task 5 test `test_recovery_after_a_crash_never_exceeds_the_cap`.)
3. A lore request on the retry after a lore fetch → `not_realised` without fallback, as today. (Existing `test_exhausted_lore_does_not_execute_a_fallback_on_recovery` must stay green.)
4. Quote containing `«ёлка»` against source `"Ёлка"` → accepted; a quote with different words → still rejected. (Task 4 tests.)
5. Narration reviewer returns garbage → the written text is shown, turn status `done`. (Task 3 test.)

---

### Task 1: Structured calls run at temperature 0.2

**Files:**
- Modify: `app/agents/master/universal.py` (`_call`, the `temperature = ...` line and the two duplicated purpose sets)
- Test: `tests/test_exploration_master.py`

**Interfaces:**
- Produces: module-level `STRUCTURED_PURPOSES: frozenset[str]` in `app/agents/master/universal.py` (the six purposes above), used for model choice, temperature and tool options.

- [ ] **Step 1: Write the failing test** `test_structured_calls_run_cold_and_narration_keeps_its_temperature`: copy the `Recording` provider pattern from `test_structured_calls_leave_room_for_a_thinking_models_reasoning`, record `kwargs.get("temperature")`; same four replies. Assert `temps[0] == temps[1] == temps[3] == 0.2` and `temps[2] == 0.8`.
- [ ] **Step 2: Run** `pytest tests/test_exploration_master.py::test_structured_calls_run_cold_and_narration_keeps_its_temperature -v` → FAIL (`0.8 != 0.2`).
- [ ] **Step 3: Implement** `STRUCTURED_PURPOSES`; `temperature = 0.2 if purpose in STRUCTURED_PURPOSES else (cfg.temperature if cfg else 0.8)`; replace both inline purpose sets with the constant.
- [ ] **Step 4: Run** the test and `pytest tests/test_exploration_master.py tests/test_llm_sampling.py -q` → PASS.
- [ ] **Step 5: Commit** `fix(master): structured decisions and reviews run at temperature 0.2`.

### Task 2: Rewards module is always included

**Files:**
- Modify: `app/agents/master/prompting/modules.py` (`_rewards`)
- Test: `tests/test_prompting_modules.py`

- [ ] **Step 1: Write the failing test** `test_rewards_rules_reach_the_model_with_russian_history`: `context = empty_world(); context["history"] = ["Герой вошёл в пещеру."]`; assert `"rewards" in {m.name for m in select_modules(context)}`.
- [ ] **Step 2: Run** it → FAIL.
- [ ] **Step 3: Implement** `_rewards(context) -> bool` returns `True`; comment: the server validates and deduplicates every reward (`app/core/universal/rewards.py`), so the rules are always safe to show. Drop the now-unused `json` import if nothing else uses it.
- [ ] **Step 4: Update** existing expectations that list modules for `empty_world()` (e.g. the `== ["travel"]` assertion) to include `"rewards"` last; run `pytest tests/test_prompting_modules.py tests/test_context_eval_variants.py -q` → PASS.
- [ ] **Step 5: Commit** `fix(master): the rewards rules always reach the model`.

### Task 3: Unparsable review replies no longer drop the turn

**Files:**
- Modify: `app/agents/master/exploration.py` (intent review parse in `obtain_exploration_action`, narration review parse in `reviewed_narration`)
- Test: `tests/test_exploration_master.py`

**Interfaces:**
- Consumes: `repair_json(raw: str) -> dict | None` from `app/agents/llm.py`.
- Produces: `parse_reply(raw: str, model: type[BaseModel]) -> BaseModel | None` in `app/agents/master/exploration.py`: `json.loads`, else `repair_json`, then `model.model_validate`; `None` on any failure (log a warning with the first 500 chars).
- Produces: `REVIEW_UNAVAILABLE = "Проверка смысла не дала ответа; разбери слова игрока ещё раз."` — the `message` of the synthetic mismatch.

- [ ] **Step 1: Write failing tests**
  - `test_unparsable_intent_review_is_a_mismatch_not_a_pass`: replies `[proposal(), '{"verdict": ', proposal(), {"verdict": "pass", "covered_requirements": []}, "Искры мягко мерцают над ладонью.", {"verdict": "pass"}]`; assert turn `done`, one `HeroAbility`, and `"Проверка смысла не дала ответа" in json.dumps(provider.prompts[2])` (the retry carries the hint).
  - `test_a_garbled_narration_review_keeps_the_written_scene`: replies `[proposal(), {"verdict": "pass", "covered_requirements": []}, "Искры мягко мерцают над ладонью.", "not json"]`; assert turn `done` and a narration `Message` with that text exists.
- [ ] **Step 2: Run** both → FAIL (exceptions / `narration_unavailable`).
- [ ] **Step 3: Implement** `parse_reply`; intent review: `parse_reply(...) or IntentReview(verdict="mismatch", message=REVIEW_UNAVAILABLE, covered_requirements=[])`; narration review: `None` → return `text`.
- [ ] **Step 4: Run** `pytest tests/test_exploration_master.py -q` → PASS.
- [ ] **Step 5: Commit** `fix(master): a garbled review reply is a mismatch or an accepted scene, never a dropped turn`.

### Task 4: Quote matching ignores case, ё and quote marks

**Files:**
- Modify: `app/core/universal/interpretation.py` (requirement quote check and `evidence_quote` check in `compile_exploration`)
- Test: `tests/test_universal_interpretation_quotes.py` (create)

**Interfaces:**
- Produces: `normalize_quote(text: str) -> str` in `app/core/universal/interpretation.py`: `casefold`, `ё`→`е`, each of `«»„“”"'` → `"`, runs of whitespace → one space, strip.

- [ ] **Step 1: Write failing tests**
  - `test_normalize_quote_folds_case_yo_quotes_and_spaces`: `normalize_quote('  Зажигаю «Ёлку»\n') == 'зажигаю "елку"'`.
  - `test_a_quote_differing_only_in_case_reaches_the_roll`: run a turn (pattern of `test_fresh_v2_magic_...`) where `proposal()` gets `requirements=[{"id": "req_1", "quote": "INVENT A VINE SIGHT", "effect": "cosmetic"}]` and its effect `required_by=["req_1"]` (source in `prepare` is `"Invent a vine sight"`); review covers `["req_1"]`; assert one `HeroAbility`.
  - `test_a_quote_with_other_words_is_still_rejected`: same with quote `"summon a dragon"`; assert the second decide prompt contains `"дословным фрагментом"`.
- [ ] **Step 2: Run** → first two FAIL.
- [ ] **Step 3: Implement** `normalize_quote`; compare `normalize_quote(quote) in normalize_quote(source)` and likewise for evidence.
- [ ] **Step 4: Run** the new file plus `pytest tests/test_exploration_master.py -q` → PASS.
- [ ] **Step 5: Commit** `fix(universal): quotes match the player's words regardless of case, ё and quote marks`.

### Task 5: Separate retry budgets with a total cap

**Files:**
- Modify: `app/agents/master/exploration.py` (`obtain_exploration_action` loop)
- Test: `tests/test_exploration_budgets.py` (create); update existing count assertions listed in Step 4

**Interfaces:**
- Consumes: `REVIEW_UNAVAILABLE` (Task 3).
- Produces in `app/agents/master/exploration.py`:
  - `RETRY_LIMITS = {"lore": 1, "format": 2, "meaning": 1}`, `MAX_DECIDE_CALLS = 4`.
  - `may_retry(trace: dict, mid: str, reason: Literal["lore", "format", "meaning"]) -> bool` — false when `proposal_attempts[mid] >= MAX_DECIDE_CALLS`, when `proposal_budgets[mid][reason] >= RETRY_LIMITS[reason]`, or for a legacy trace (`proposal_attempts[mid] >= 2` and `mid not in proposal_budgets`).
  - Trace key `proposal_budgets[mid] = {"lore": int, "format": int, "meaning": int}`, incremented together with `proposal_attempts[mid]` and stored before the call.
- Reason for the next call: lore requested → `lore`; review verdict `mismatch`/`unsupported` (incl. `REVIEW_UNAVAILABLE`) → `meaning`; any other `ValueError`/`AccessDenied`/`InsufficientEnergy`/invalid JSON → `format`. The first call has no reason and spends only the total.
- When `may_retry` is false: lore → existing `not_realised` without fallback; others → existing exhaustion path (journal + `fallback_action`). Behaviour of those paths is unchanged.

- [ ] **Step 1: Write failing tests** (use `obtain_exploration_action` with a scripted `ask`, as in `tests/test_prompting_slicers.py`, or `run_turn` with `Provider`):
  - `test_a_lore_fetch_does_not_eat_the_format_repair`: decide replies `need_lore`, then invalid proposal, then valid → proposal returned, 3 decide calls.
  - `test_a_meaning_disagreement_still_leaves_a_format_repair`: valid→`mismatch`, invalid, valid→`pass` → proposal returned.
  - `test_format_failures_get_two_repairs_then_the_floor`: 3 invalid replies → floor proposal, exactly 3 decide calls, `proposal_budgets[mid]["format"] == 2`.
  - `test_the_total_cap_is_four_decide_calls`: `need_lore`; valid→`mismatch`; invalid; invalid → floor, exactly 4 decide calls, no fifth.
  - `test_recovery_after_a_crash_never_exceeds_the_cap`: same as above but the 4th decide raises `RuntimeError`; second `run_turn` with `Provider([])` makes no decide call.
  - `test_a_legacy_trace_with_two_attempts_gets_no_new_call`: trace `{"proposal_attempts": {"m": 2}}` and an invalid admission stored → no `ask("exploration_decide", ...)`.
- [ ] **Step 2: Run** `pytest tests/test_exploration_budgets.py -v` → FAIL.
- [ ] **Step 3: Implement** `may_retry` and wire the loop: replace `attempts.get(mid, 0) < 2` and the lore `attempts[mid] < 2` check with `may_retry(trace, mid, reason)`, tracking `reason` from the previous outcome as above.
- [ ] **Step 4: Update existing expectations** that pinned the old shared budget: `tests/test_exploration_master.py:69,86`, `tests/test_prompting_slicers.py:110`, `tests/test_universal_action_pipeline.py:123,198`, `tests/test_universal_action_review.py:68`, `tests/test_universal_check_results.py:86`. For each, recompute the count under the new limits and add replies where a scenario now gets another repair; do not weaken an assertion to a range. Run `pytest -q` → all PASS.
- [ ] **Step 5: Commit** `feat(master): lore, format and meaning have their own retry budgets under a cap of four calls`.

### Task 6: Wrap-up

- [ ] Run `pytest -q` (full) → PASS.
- [ ] Run `graphify update .`.
- [ ] Optional: run the eval in `tests/eval` and compare with `tests/eval/final-result.json`; report the numbers, do not commit eval output unless asked.
