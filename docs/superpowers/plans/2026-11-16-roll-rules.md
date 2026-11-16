# Roll rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Roll only where there is an obstacle and a stake; one attempt per (target, ability); a success can unlock or break a passage; a natural 1 brings a bounded mishap the model picks; the floor never makes magic work; the meaning review runs on server signals.

**Architecture:** New fields on `IntentV2`/`ExplorationAction` (`check_target`, `tool_item_id`, `concrete_method`, `fumble`) and a new effect kind `passage`, validated in `compile_exploration` and executed in `resolve_exploration`. Failed checks are remembered in a new table `attempt_locks` behind a small module `app/core/universal/attempts.py`. Prompt changes live in `app/agents/master/prompting/modules.py` and the review prompt in `app/agents/master/exploration.py`.

**Tech Stack:** Python 3.12, pydantic v2, SQLAlchemy async, alembic, pytest with fake providers (`tests/test_universal_master.Provider`, `ScriptedLLM`).

**Spec:** `docs/superpowers/specs/2026-11-16-roll-rules-design.md`

## Global Constraints

- No real model calls and no eval: every test uses fake providers; run tests in a worktree that has no `.env` (`D:/Workspace/Projects/taleforge/.venv/Scripts/python -m pytest ...`).
- Player-facing text in Russian; code comments in English, in the file's style.
- Discounts: −2 tool, −2 concrete method, difficulty floor 5.
- `harm` 1–3 HP, never below 1 HP. Fumble kinds: `harm`, `break_tool`, `alert`, `none`.
- Passage transitions: `locked→closed`, `locked→open`, `blocked→open`, success only, both link sides.
- A refused closed approach costs nothing: no dice, energy, HP or time.
- Location-target locks only for `observe`.
- After code changes: `graphify update .`.

## Review Focus

1. The same message is resolved twice (replayed receipt) after a failure → still one lock row, no IntegrityError. (Task 2 `test_close_approach_is_idempotent`.)
2. Hero B tries the approach hero A failed → refused for B too. (Task 3 `test_a_closed_approach_is_closed_for_the_whole_party`.)
3. A passage whose far side location row is missing → near side updated, no crash. (Task 6 `test_passage_with_missing_far_side_still_opens_here`.)
4. Fumble `harm` 3 at 1 HP → hero stays at 1 HP. (Task 5 `test_harm_never_drops_below_one_hp`.)
5. `tool_item_id` of another hero's item or an unknown id → no discount, no crash. (Task 4 `test_a_foreign_or_unknown_tool_gives_no_discount`.)

---

### Task 1: The roll is for obstacles only

**Files:**
- Modify: `app/agents/master/prompting/modules.py` (CORE text)
- Modify: `app/core/universal/interpretation.py` (`compile_exploration`)
- Test: `tests/test_roll_rules.py` (create)

**Interfaces:**
- Produces: `async def nothing_hidden_here(ctx) -> bool` in `app/core/universal/interpretation.py` — true when the actor's location has no `Entity` with `state["hidden"]` truthy and no link/sketch exit with `hidden` truthy.

- [ ] **Step 1: Failing tests**
  - `test_core_no_longer_demands_a_check_for_every_step`: `"обычный шаг, слово" not in CORE` and `"У каждого действия героя в мире есть проверка" not in CORE`; `"препятств" in CORE`.
  - `test_looking_at_what_is_in_plain_sight_is_not_rolled`: compile an `observe` intent with `resolution="check"` and four outcomes in the standard `setup`/`prepare` scene (nothing hidden) → `action.resolution == "automatic"`.
  - `test_searching_where_something_is_hidden_is_rolled`: same with a creature `Entity` in the hero's location whose `state["hidden"] = True` → `action.resolution == "check"`.
- [ ] **Step 2: Run** `pytest tests/test_roll_rules.py -v` → FAIL.
- [ ] **Step 3: Implement.** CORE: replace the sentence starting «У каждого действия героя в мире есть проверка» through «…а любое усилие.» with: «Проверка (resolution=check) нужна, только когда есть препятствие или противник и у провала есть последствие: поиск спрятанного, уговор, обман, взлом, лазание, прыжок. Обычная речь, ходьба по сцене и осмотр видимого — automatic.» Keep the difficulty scale and the rest. In `compile_exploration`, before building `ExplorationAction`: if every effect is `observe`, `intent.resolution == "check"` and `await nothing_hidden_here(ctx)`, set resolution to `automatic`. Update `tests/test_prompting_modules.py::test_no_sentence_of_the_old_prompt_is_lost` by adding the removed sentences to `docs/prompt-rules.md` as «убрано» lines (that test reads them from there).
- [ ] **Step 4: Run** `pytest tests/test_roll_rules.py tests/test_prompting_modules.py tests/test_exploration_master.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(universal): only an obstacle with a stake is rolled; looking at what is in sight is not`.

### Task 2: Attempt locks storage

**Files:**
- Modify: `app/db/models.py` (new `AttemptLock`)
- Create: `alembic/versions/0018_attempt_locks.py` (`revision="universal_0018"`, `down_revision="universal_0017"`)
- Create: `app/core/universal/attempts.py`
- Test: `tests/test_attempt_locks.py` (create)

**Interfaces:**
- Produces: `AttemptLock` with `__tablename__ = "attempt_locks"`, columns `id String(32) pk` (`new_id`), `campaign_id String(32) FK campaigns.id ondelete CASCADE`, `target_id String(64)`, `attribute String(8)`, `actor_id String(32)`, `event_id String(32)`, `created_at DateTime(tz)`; `UniqueConstraint(campaign_id, target_id, attribute, name="uq_attempt_lock")`.
- Produces in `app/core/universal/attempts.py`:
  - `async def approach_closed(session, campaign_id: str, target_id: str, attribute: str) -> bool`
  - `async def close_approach(session, campaign_id, target_id, attribute, actor_id, event_id) -> None` — no-op if the row exists.
  - `async def closed_approaches(session, campaign_id, target_ids: Iterable[str]) -> list[dict]` — `[{"target_id", "attribute"}]`, sorted.

- [ ] **Step 1: Failing tests** `test_a_closed_approach_is_remembered` (close then `approach_closed` true; other attribute false), `test_close_approach_is_idempotent` (twice → one row), `test_closed_approaches_lists_only_the_asked_targets`.
- [ ] **Step 2: Run** → FAIL (import error).
- [ ] **Step 3: Implement** model, migration (mirror `0017_artworks.py` style, index `ix_attempt_locks_campaign_id`), module.
- [ ] **Step 4: Run** `pytest tests/test_attempt_locks.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(universal): a failed approach is remembered on its target`.

### Task 3: One attempt per approach

**Files:**
- Modify: `app/rules/universal/exploration.py` (`IntentV2`, `ExplorationAction`: `check_target: str | None = Field(default=None, max_length=64)`)
- Modify: `app/core/universal/interpretation.py` (`compile_exploration`, `validate_exploration`)
- Modify: `app/core/universal/exploration_resolution.py` (after the check result)
- Modify: `app/rules/universal/failures.py` (new code)
- Modify: `app/agents/master/prompting/context.py`, `app/agents/master/prompting/modules.py`
- Test: `tests/test_roll_rules.py`

**Interfaces:**
- Consumes: Task 2 functions.
- Produces: failure code `"approach_closed"` → `("world_denial", "Этот способ уже не сработает: прошлая попытка не удалась и сделала его невозможным. Ничего не брошено и не потрачено; расскажи это в сцене и подскажи, что можно попробовать иначе.")`.
- Produces: decide context key `closed_approaches: list[{"target_id","attribute"}]` for the location id, every entity in the scene and every known passage id.

- [ ] **Step 1: Failing tests**
  - `test_a_failed_lockpick_closes_that_approach`: check `dex` with `check_target` = a passage id, dice `FixedDice([2])` → one `AttemptLock(target, "dex")`.
  - `test_the_same_approach_is_refused_without_dice_or_cost`: lock pre-seeded → `ActionValidationError("approach_closed")` from `validate_exploration`; energies and HP unchanged; no `Event`.
  - `test_another_ability_on_the_same_door_is_still_open`: lock `dex` → `str` check compiles.
  - `test_a_closed_approach_is_closed_for_the_whole_party`: lock written by hero A → hero B refused.
  - `test_a_failed_climb_in_the_room_does_not_lock_the_room`: check `str` without `check_target`, fails → no lock; failed `observe` check without target → lock on location id.
  - `test_an_unknown_check_target_is_a_format_error`: `check_target="nowhere"` → `ValueError` (repairable).
  - `test_the_decision_sees_closed_approaches`: context built by `prompting/context.py` contains the seeded lock.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Compile: default `check_target` to the actor's location id when `resolution == "check"`; reject an id that is neither the location, an `Entity` in it, nor a non-hidden passage of it. `validate_exploration`: if check and `approach_closed(...)` → `ActionValidationError("approach_closed")` (place it next to `impossible_deed`). Resolution: after the check, if `not result.success` and (`check_target != location id` or all effects are `observe`) → `close_approach(..., event.id)`. Rules text (combat/speech module or CORE, one sentence): «Способ из closed_approaches (та же цель и характеристика) уже не сработает: не предлагай его, скажи игроку, что так уже не выйдет, и предложи другой путь.»
- [ ] **Step 4: Run** `pytest tests/test_roll_rules.py tests/test_exploration_master.py tests/test_universal_check_results.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(universal): one attempt per approach — a failed way is closed for the party`.

### Task 4: Tool and method discount

**Files:**
- Modify: `app/rules/universal/exploration.py` (`IntentV2`: `tool_item_id: str | None = Field(default=None, max_length=64)`, `concrete_method: bool = False`; `ExplorationAction`: `tool_item_id`)
- Modify: `app/core/universal/interpretation.py` (`compile_exploration`, `is_plain_action`)
- Modify: `app/agents/master/exploration.py` (`REVIEW` text), `app/agents/master/prompting/modules.py` (CORE: one sentence on the fields)
- Test: `tests/test_roll_rules.py`

**Interfaces:**
- Produces: `TOOL_DISCOUNT = 2`, `METHOD_DISCOUNT = 2`, `MIN_DIFFICULTY = 5` in `app/core/universal/interpretation.py`; `ExplorationAction.tool_item_id` (consumed by Task 5 `break_tool`).

- [ ] **Step 1: Failing tests**
  - `test_a_real_tool_and_a_concrete_method_lower_the_difficulty`: difficulty 14, hero holds item `pick`, `tool_item_id="pick"`, `concrete_method=True`, review pass → `action.difficulty == 10`.
  - `test_the_difficulty_never_drops_below_five`: difficulty 6 with both → 5.
  - `test_a_foreign_or_unknown_tool_gives_no_discount`: `tool_item_id` of another hero's `InventoryItem`, then `"ghost"` → difficulty unchanged, `action.tool_item_id is None`, no exception.
  - `test_a_concrete_method_always_goes_to_the_meaning_review`: `is_plain_action(intent_with_concrete_method)` is False.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** Tool counts when `accessible(row, actor, held=…)` (`app/core/universal/objects.py`) accepts it as the hero's inventory item or an object in the scene; otherwise drop with `log.info`. `is_plain_action` returns False when `intent.concrete_method`. REVIEW gets: «Если concrete_method=true, а игрок не описал, чем и как действует, ответь mismatch с message «способ не описан — concrete_method=false».»
- [ ] **Step 4: Run** `pytest tests/test_roll_rules.py tests/test_exploration_master.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(universal): a real tool and a concrete method make a deed easier`.

### Task 5: A mishap on a natural 1

**Files:**
- Modify: `app/rules/universal/exploration.py` (`FumbleIntent`; `IntentV2.fumble`, `ExplorationAction.fumble`)
- Modify: `app/core/universal/exploration_resolution.py` (`_fumble`)
- Modify: `app/core/universal/perception.py` (`assess_detection`: `alerted` observer → hero's edge `disadvantage`)
- Modify: `app/agents/master/prompting/modules.py` (CORE: the sentence «critical_failure (выпала 1) всегда с небольшой травмой героя: сервер снимает 1 HP…» becomes the fumble list)
- Test: `tests/test_roll_rules.py`

**Interfaces:**
- Consumes: `ExplorationAction.tool_item_id` (Task 4).
- Produces: `class FumbleIntent(ClosedModel): kind: Literal["harm","break_tool","alert","none"] = "none"; amount: int = Field(default=1, ge=1, le=3, strict=True); creature_id: str | None = Field(default=None, max_length=64)`.

- [ ] **Step 1: Failing tests** (dice `FixedDice([1])`):
  - `test_harm_costs_the_chosen_hp`: `harm` 2 at 20 HP → 18; change `kind="damage"`, `amount "2"`.
  - `test_harm_never_drops_below_one_hp`: `harm` 3 at 1 HP → 1.
  - `test_a_broken_tool_leaves_the_inventory`: `break_tool` with `tool_item_id="pick"` → item gone; without a tool → nothing removed.
  - `test_an_alerted_creature_spots_a_sneaking_hero_more_easily`: `alert` on creature `guard` → `state["alerted"] is True`; next `assess_detection` roll uses `disadvantage`.
  - `test_words_never_wound`: talk-only action with `harm` → HP unchanged.
  - `test_no_fumble_given_means_no_mishap`: no `fumble` → HP unchanged (replaces the old fixed 1 HP; update existing tests asserting «теряет 1 HP» accordingly).
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** `_fumble(ctx, action, event) -> EffectChange | None` per spec; `alert` only on a living creature in the hero's location; talk-only maps `harm`/`break_tool` to `none`.
- [ ] **Step 4: Run** `pytest tests/test_roll_rules.py tests/test_exploration_master.py tests/test_universal_check_results.py -q` → PASS (adjusted old fumble expectations recounted, not loosened).
- [ ] **Step 5: Commit** `feat(universal): a natural 1 brings the mishap the master picks, within bounds`.

### Task 6: The passage effect

**Files:**
- Modify: `app/rules/universal/exploration.py` (`EffectKind` + `"passage"`, `ORDINARY_KINDS` + `"passage"`, `EffectIntentV2.passage_id: str | None = Field(default=None, max_length=64)`, `to_state: Literal["closed","open"] | None = None`, `_RELEVANT["passage"] = {"passage_id","to_state"}`)
- Create: `app/core/universal/passages.py`
- Modify: `app/core/universal/interpretation.py` (validation), `app/core/universal/exploration_resolution.py` (apply), `app/core/topology.py` or the `known_exits` builder in `app/agents/master/prompting/context.py` (add `passage_id`, `state`), `app/agents/master/prompting/modules.py` (CORE example)
- Test: `tests/test_passages.py` (create)

**Interfaces:**
- Produces: `ALLOWED = {("locked","closed"), ("locked","open"), ("blocked","open")}`; `async def passage_link(session, location, passage_id) -> dict | None`; `async def set_passage_state(session, campaign_id, location_id, passage_id, to_state) -> EffectChange`.

- [ ] **Step 1: Failing tests**
  - `test_an_unlocked_door_lets_the_party_through`: location with link `state="locked"`, check success with effect `passage(to_state="closed")` → both sides' link state `closed`; `move_hero` to the destination succeeds.
  - `test_a_failed_check_leaves_the_door_locked`.
  - `test_a_forbidden_transition_is_a_format_error`: `open→closed` → `ValueError`.
  - `test_passage_with_missing_far_side_still_opens_here`.
  - `test_core_names_passage_not_free_effect_for_a_broken_door`: `"выбитая дверь" not in CORE`; `"passage" in CORE`.
  - `test_known_exits_carry_the_passage_id_and_state`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement**; also update `sketch.exits`/`unplaced_exits` entries whose `to` matches when present.
- [ ] **Step 4: Run** `pytest tests/test_passages.py tests/test_universal_world_exploration.py tests/test_exploration_master.py -q` → PASS.
- [ ] **Step 5: Commit** `feat(universal): a successful deed can unlock or break a passage`.

### Task 7: Honest floor and server-led review

**Files:**
- Modify: `app/agents/master/exploration.py` (`fallback_action`)
- Modify: `app/core/universal/interpretation.py` (`is_plain_action`)
- Modify: `app/config.py` (`review_model: str = ""`, env `REVIEW_MODEL`), `app/agents/llm.py` (`review_model_for() -> str`: `model_for(settings.review_model)` style resolution when set, else `decide_model_for()`), `app/agents/master/universal.py` (`_call` uses it for `intent_review`, `narration_review`)
- Test: `tests/test_roll_rules.py`; update `tests/test_exploration_master.py` floor tests

**Interfaces:**
- Produces: failure fact for the magic floor reusing `not_realised_fact()` (no new code).

- [ ] **Step 1: Failing tests**
  - `test_magic_the_model_cannot_shape_does_not_happen`: replaces `test_a_magic_request_the_model_cannot_shape_is_kept_as_a_free_effect` → no `Event`, energy unchanged, prepared result is a failure.
  - `test_an_ordinary_floor_rolls_but_keeps_no_raw_text_effect`: floor operations kinds `== ["wait"]`, `resolution == "check"`.
  - `test_a_model_calling_magic_ordinary_still_gets_reviewed`: intent `player_request="ordinary"`, source text «колдую свет» → `is_plain_action(...)` False.
  - `test_reviews_use_the_review_model_when_set`: monkeypatch `settings.review_model` → recorded `model` for `intent_review` differs from `exploration_decide`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement.** `is_plain_action(intent, *, crossable=False, source="")`: drop the `player_request` condition, add `not needs_intent_review(source, intent, known=True)`; pass `context["source"]` from `obtain_exploration_action`.
- [ ] **Step 4: Run** `pytest tests/test_roll_rules.py tests/test_exploration_master.py tests/test_exploration_budgets.py tests/test_universal_action_review.py -q` → PASS.
- [ ] **Step 5: Commit** `fix(master): unshaped magic does not happen; the server decides when meaning is reviewed`.

### Task 8: Wrap-up

- [ ] Run `pytest tests -q -k "universal or exploration or interpretation or prompting or master or tts or budgets or roll or passage or attempt"` in the worktree (no `.env`) → PASS.
- [ ] Run `graphify update .`.
- [ ] No eval run.
