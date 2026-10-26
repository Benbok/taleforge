# Действия по законам мира Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Мастер решает по тексту мира (`laws`, `powers`, `world`), можно ли действие; код только считает и исполняет; всё созданное временное; любой запрос получает общий путь (существо, свободный эффект), а любой сбой доходит до игрока рассказом мастера.

**Architecture:** Расширяем 2А: срок называет игрок (по умолчанию 18 с), `create_object` получает шаблон `creature`, появляются виды эффектов `free_effect` и `command`. Сбои (нехватка энергии, запрет законами, исчерпанные исправления) превращаются в факты для того же повествования, которое уже есть, а не в готовый текст отказа. В решение и в обе проверки передаётся текст мира. Журнал необычных запросов хранится в новой таблице.

**Tech Stack:** Python 3.12, FastAPI/Pydantic 2/SQLAlchemy 2/Alembic (одна аддитивная миграция), pytest (`-n 4`), ruff.

**Spec:** [Действия по законам мира](../specs/2026-10-26-world-law-driven-actions-design.md); заменяет [свободное создание](../specs/2026-10-25-free-creation-design.md); база — ветка `feature/free-creation` (план [2026-10-25-free-creation.md](2026-10-25-free-creation.md) выполнен).

## Global Constraints

- Постоянного результата нет: каждое создание и наложение имеет срок; по умолчанию `DEFAULT_EFFECT_SECONDS = 18`; срок называет игрок; единицы срока `ceil(seconds / 6)`; верхнего предела срока нет, кроме `MAX_EFFECT_SECONDS = 604800` (неделя, защита целых чисел).
- Цена создания = `SCALE_PRICE[scale] × (2 если sturdy) × уровень × единицы срока` (tiny 1, small 3, medium 6, large 12, huge 24 за единицу и уровень): кружка на 18 с стоит 3, средняя постройка 18, большая 36. Это моё допущение; значения подбирать с владельцем.
- Управление созданным существом энергии не стоит.
- Нехватка энергии: ничего не создаётся и не тратится; мастер литературно говорит, что возможностей не хватило, и называет, сколько именно не хватило.
- До игрока не доходят тексты «некорректные параметры», «сервер отказал», «не поддерживается движком»; техническая ошибка провайдера модели остаётся прежней.
- Закрытый текст мира (`secret_text`, `private`) не попадает в проверки и повествование, которые видят игроки; `laws`, `powers`, `world` попадают.
- Здоровье, урон, лечение, бой вне плана (план 3).
- Тесты без платных вызовов; проверка модели только `tools/eval_exploration.py`.

## Review Focus

1. Сбой любого рода (нехватка, запрет законами, исчерпанные исправления) заканчивается рассказом мастера, а не служебной фразой (Task 4).
2. Созданное существо исчезает по сроку и не принимает команд после; чужой герой его не контролирует (Task 2).
3. Названный игроком срок больше 18 секунд дороже пропорционально и при нехватке даёт «не хватило N» (Task 1, 4).
4. Закрытый текст мира не просачивается в проверки и повествование (Task 3).
5. Повтор того же сообщения не создаёт существо или эффект дважды и не списывает дважды (Task 2).

---

## File Structure

- `app/rules/universal/exploration.py`: срок, виды `free_effect`/`command`, шаблон `creature`, вердикт `forbidden`, правила очистки.
- `app/core/universal/objects.py`, `commands.py` (новый): состояние существа, команда.
- `app/core/universal/effects.py`, `perception.py`: свободный эффект в списке действующих эффектов.
- `app/agents/master/exploration.py`, `universal.py`, `universal_narration.py`, `action_results.py`: текст мира, факты сбоев, промпты.
- `app/core/universal/journal.py` (новый), `app/db/models.py`, `alembic/versions/0006_universal_journal.py`: журнал.
- `tools/eval_exploration.py`: новые фразы.

---

### Task 1: Всё временное, срок называет игрок

**Files:**
- Modify: `app/rules/universal/exploration.py` (`EffectIntentV2.lifetime`, `Count` bounds for `duration_seconds`, `clean_model_intent`, `exploration_capabilities`), `app/core/universal/interpretation.py` (duration from the intent)
- Test: `tests/test_exploration_contracts.py`, `tests/test_exploration_interpretation.py`, update expectations in `tests/test_exploration_resolution.py`, `tests/test_exploration_objects.py`, `tests/test_exploration_crossing.py`

**Interfaces:**
- Produces: `MAX_EFFECT_SECONDS = 604800`; `EffectIntentV2.lifetime: Literal["instant", "timed"]` (a model's `"permanent"` is mapped to `"timed"` by `clean_model_intent`); `IntentV2.duration_seconds` honoured by `compile_exploration`; `create_object` is always timed.

- [ ] **Step 1: Write failing tests**: `test_a_permanent_result_becomes_a_timed_one_and_the_cup_costs_three` (cleaner maps `permanent`→`timed`; cup at level 1 costs 3); `test_a_duration_named_by_the_player_is_honoured_and_priced` (`duration_seconds=60` medium creation costs `6 × 10`); `test_the_default_term_is_eighteen_seconds_when_none_is_named`; `test_a_creation_always_ends` (a created structure has `temporary=True` and expires after its term).
- [ ] **Step 2: Run** `pytest tests/test_exploration_contracts.py tests/test_exploration_interpretation.py -q -n 0 -k "permanent or duration or default_term or always_ends"`. Expected: FAIL.
- [ ] **Step 3: Implement**: drop `"permanent"` from `lifetime` and the permanent-only validator; `clean_model_intent` maps `permanent` to `timed`; `compile_exploration` uses `intent.duration_seconds` (default 18, upper bound `MAX_EFFECT_SECONDS`); `apply_object_operation` marks every creation `temporary=True`; update `exploration_capabilities` (no `max_effect_seconds`); fix existing tests that used `lifetime="permanent"` or the cup price 1.
- [ ] **Step 4: Run** `pytest tests -q -n 4 -k "exploration or universal or mood or regen"`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: everything created lasts a limited time, named by the player`.

### Task 2: Существа, команды и свободные эффекты

**Files:**
- Create: `app/core/universal/commands.py`
- Modify: `app/rules/universal/exploration.py` (`EffectKind` += `free_effect`, `command`; `ObjectTemplate` += `creature`; `EffectIntentV2.abilities`), `app/core/universal/objects.py` (`ObjectState` creature fields, `accessible`), `app/core/universal/exploration_resolution.py`, `app/core/universal/effects.py`, `app/agents/master/universal.py` (context `active_effects[].description`, `creatures`)
- Test: `tests/test_exploration_creatures.py`

**Interfaces:**
- Consumes: Task 1 timed creation.
- Produces: `EffectIntentV2.abilities: str` (≤500, what a created being can do); `ObjectState.controller_id: str | None`, `.abilities: str`; creature row `Entity(kind="object", template="creature", owner_id=None)`; `async def command_creature(ctx, op, source_event) -> EffectChange` (kind `"commanded"`, requires `object_id` of a live creature whose `controller_id == actor`); `free_effect` stored through `start_effect` with `definition` keeping `label`, `appearance`; `active_effects` context rows gain `description`.

- [ ] **Step 1: Write failing tests**: `test_a_clay_puppet_is_created_for_its_term_and_priced_by_size` (medium creature 18 s costs 18; row has `template="creature"`, `controller_id`=hero, `abilities`); `test_the_creator_commands_the_puppet_for_free_and_a_stranger_cannot` (energy unchanged by `command`; another hero → refused at compile); `test_a_puppet_dissolves_when_its_term_ends_and_takes_no_more_orders`; `test_a_free_effect_is_remembered_and_shown_to_the_master_until_it_ends` (`free_effect` «скелеты остановлены», `active_effects` has it with `description`, gone after the term); `test_replaying_a_creation_or_free_effect_makes_no_second_one`.
- [ ] **Step 2: Run** `pytest tests/test_exploration_creatures.py -q -n 0`. Expected: FAIL.
- [ ] **Step 3: Implement** the kinds, creature creation branch in `apply_object_operation` (shared with structure), `command_creature`, `free_effect` in the timed-effects path (`TIMED_KINDS`, `MAGIC_KINDS`), `clean_model_intent` keeping `abilities` for creatures and `label`/`appearance` for `free_effect`, context fields.
- [ ] **Step 4: Run** the new tests and `pytest tests -q -n 4 -k "exploration or universal"`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: created beings, orders and free effects`.

### Task 3: Текст мира решает, можно ли

**Files:**
- Modify: `app/agents/master/universal.py` (context `world_rules`), `app/agents/master/exploration.py` (`SYSTEM`, `REVIEW`, narration review payload), `app/rules/universal/exploration.py` (`IntentReview.verdict` += `"forbidden"`)
- Test: `tests/test_exploration_master.py`

**Interfaces:**
- Produces: decision context key `world_rules: {"laws": str, "powers": str, "world": str}` (never `secret_text`/`private`); the same object in the review and narration-review payloads; review verdict `"forbidden"` with `message` (a reason in the world's terms); verdict `"unsupported"` is treated as `"mismatch"` with a hint to use `free_effect`.

- [ ] **Step 1: Write failing tests**: `test_laws_powers_and_world_reach_the_decision_and_both_reviews_but_never_the_secret_notes`; `test_a_forbidden_verdict_spends_nothing_and_is_not_a_repair_loop` (one decision, one review, no Event, energy unchanged); `test_an_unsupported_verdict_asks_the_model_to_use_a_free_effect`.
- [ ] **Step 2: Run** `pytest tests/test_exploration_master.py -q -n 0 -k "laws_powers or forbidden or unsupported"`. Expected: FAIL.
- [ ] **Step 3: Implement** the context key (replace `world_laws`), prompt rewrite in `SYSTEM` (permission is judged by `world_rules`; durations; creatures and `command`; `free_effect` when no kind fits; never refuse for lack of a kind) and `REVIEW` (judge by `world_rules`; verdict `forbidden` only when the text of the world forbids it), pass `world_rules` into `narration_review`.
- [ ] **Step 4: Run** the same command plus `tests/test_exploration_master.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: the world's own text decides what is allowed`.

### Task 4: Сбои доходят рассказом

**Files:**
- Modify: `app/agents/master/action_results.py` (`narration_parts`), `app/rules/universal/failures.py` (fact texts with numbers), `app/agents/master/exploration.py` (carry `need`/`have`, `forbidden` reason), `app/agents/master/universal_narration.py` (`SYSTEM`)
- Test: `tests/test_exploration_master.py`, `tests/test_universal_action_pipeline.py`

**Interfaces:**
- Produces: `NARRATED_FAILURES = {"insufficient_resources", "world_denial", "invalid_proposal", "unsupported_capability", "target_unavailable", "stale_profile"}`; `narration_parts(outcomes)` puts these into `story` (so the master narrates them) and keeps only technical ones (`internal_error`) as notices; failure `message` becomes a fact such as «Не хватило энергии: нужно 24, есть 7 (не хватает 17)»; the narration prompt tells the master to tell such a fact in the story and to state a shortfall.

- [ ] **Step 1: Write failing tests**: `test_a_shortfall_is_told_in_the_story_with_how_much_was_missing` (hero wis 2, price 3: the narration prompt contains the fact with «не хватает 1», the saved narration is the model's prose, nothing spent/created); `test_a_law_that_forbids_is_told_in_the_story` (forbidden review → story with the reviewer's reason); `test_exhausted_repairs_are_told_in_the_story_not_as_invalid_parameters` (two bad proposals → the narration prompt carries a fact, the player never sees «некорректные параметры»); `test_a_provider_failure_stays_a_plain_notice`.
- [ ] **Step 2: Run** `pytest tests/test_exploration_master.py tests/test_universal_action_pipeline.py -q -n 0 -k "shortfall or forbids or exhausted or provider_failure"`. Expected: FAIL.
- [ ] **Step 3: Implement** the fact texts and the routing; update tests that asserted the old refusal texts.
- [ ] **Step 4: Run** `pytest tests -q -n 4 -k "exploration or universal or mood or regen"`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: every failure reaches the player as the master's story`.

### Task 5: Журнал необычных запросов

**Files:**
- Create: `app/core/universal/journal.py`, `alembic/versions/0006_universal_journal.py`
- Modify: `app/db/models.py` (`UniversalJournal`), `app/db/session.py` (required table), `app/core/universal/exploration_resolution.py`
- Test: `tests/test_exploration_journal.py`, `tests/test_exploration_migration.py`

**Interfaces:**
- Produces: table `universal_journal(id, campaign_id, kind, source_text, detail JSON, created_at)`; `async def record_journal(session, campaign_id, kind, source_text, detail) -> None` with `kind in {"free_effect", "creature", "forbidden", "exhausted"}`; migration `universal_0005 → universal_0006`, additive.

- [ ] **Step 1: Write failing tests**: `test_free_effects_and_forbidden_requests_are_journaled_once` (a replay adds no second row); `test_the_migration_adds_the_journal_without_touching_existing_rows` (upgrade from `universal_0005`).
- [ ] **Step 2: Run** them. Expected: FAIL.
- [ ] **Step 3: Implement** model, migration, `record_journal` call sites (free effect and creature on creation, forbidden and exhausted at the end of admission), required-table check.
- [ ] **Step 4: Run** the new tests and `pytest tests -q -n 4 -k "exploration or universal"`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: a journal of unusual requests`.

### Task 6: Набор фраз, приёмка, закрытие

**Files:**
- Modify: `tools/eval_exploration.py`, `docs/superpowers/specs/2026-10-26-world-law-driven-actions-design.md`
- Test: `tests/test_exploration_acceptance.py`

- [ ] **Step 1: Write the acceptance test** `test_a_hero_makes_a_clay_puppet_and_orders_it_about` (create a medium creature, command it, expire it; nothing remains) and `test_not_enough_strength_is_a_story_with_the_shortfall` end to end with a scripted provider.
- [ ] **Step 2: Run** them. Expected: FAIL before Tasks 1–5, PASS after.
- [ ] **Step 3: Extend `tools/eval_exploration.py`** with: «леплю из глины маленького человечка и вдыхаю в него магию, чтобы он стал моей марионеткой», «приказываю марионетке принести ключ со стола» (state with a puppet), «останавливаю скелетов приказом на минуту», «чувствую шаги в земле через корень», «создаю мост на час», «воскрешаю мёртвого» (laws forbid, informational).
- [ ] **Step 4: Run** full verification: `pytest tests -q -n 4 -k "exploration or universal or mood or regen or voic"`, `ruff check app tests tools`, the eval via the one-off container (`docker run --rm -i --env-file C:/Temp/app.env -e REPEAT=3 -v <worktree>/app:/srv/app taleforge-universal-app:latest python - < tools/eval_exploration.py`). Expected: green; eval shows only the known flaky observations.
- [ ] **Step 5: Mark** the spec's open points settled and commit `feat: world-law-driven actions accepted`.
