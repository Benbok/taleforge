# Свободное создание Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Игрок может создать магией любой предмет или постройку; цену задаёт оценка масштаба моделью, созданное запоминается как предмет места, а крупное создание с пометкой «куда ведёт» открывает новое место при переходе по нему.

**Architecture:** Существующий эффект `create_object` получает оценку `scale`/`sturdiness` и новый шаблон `structure`; сервер считает цену по масштабу, запись хранится как Entity-объект с расширенным `ObjectState`. Эффект `move` с `object_id` постройки превращается в переход: при успехе проверки сервер создаёт место на той стороне и переносит героя. Промпты и независимая проверка смысла получают правила мира; разбор ответа модели остаётся терпимым (`clean_model_intent`).

**Tech Stack:** Python 3.12, FastAPI/Pydantic 2/SQLAlchemy 2, pytest (`-n 4`), ruff; JSON-состояние сущностей, без миграций базы.

**Spec:** [Свободное создание](../specs/2026-10-25-free-creation-design.md); продолжает [этап 2А](../specs/2026-10-25-exploration-magic-design.md).

## Global Constraints

- Действия по-прежнему одна транзакция; повтор того же действия не создаёт предмет и не списывает цену дважды (ключ сущности от `source_event.id` и номера компонента).
- Цены целые; срок временного создания 18 игровых секунд (`DEFAULT_EFFECT_SECONDS`), постоянное остаётся; единицы срока `ceil(18/6)=3` для временного, `1` для постоянного.
- Ориентир цены размера за уровень героя: tiny 1, small 3, medium 6, large 12, huge 24; прочность `sturdy` умножает цену на 2.
- Лимита на число созданных предметов нет; предел только цена и нехватка энергии показывается числами («нужно N, есть M»).
- `leads_to` допустим только у `scale` large и huge.
- Постройка принадлежит месту (`owner_id` пуст): пользоваться ею может любой герой в этом месте и на той стороне.
- Здоровье и урон от падения не трогаем (план 3); провал перехода только рассказ.
- Расходники, `clean_model_intent`, `FormBlocked` и `InsufficientEnergy` из 2А не ломаем; существующая кружка (`vessel`) стоит прежние 1 при `intensity=light`.
- Наполнение содержимым нового места существующей генерацией мест (`WorldGenerationState`) в этот план не входит: место получает название и описание из `leads_view`, остальное мастер достраивает в повествовании; подключение генерации записано как следующая работа.
- Без живых платных вызовов в тестах; проверка на модели только через `tools/eval_exploration.py`.

## Review Focus

1. Нехватка энергии на громадное создание: отказ с числами, ничего не списано и не создано (Task 1, 2).
2. Повтор того же сообщения/действия: ни второй постройки, ни второго списания (Task 2).
3. Переход по постройке, исчезнувшей между созданием и переходом: отказ с объяснением, герой остаётся (Task 4).
4. Другой игрок или герой на дальней стороне пользуется той же постройкой (Task 2, 4).
5. Пометка `leads_to` у малого создания, скрытое/чужое не просачиваются в обзор других игроков (Task 1, 2).

---

## File Structure

- `app/rules/universal/exploration.py`: поля эффекта `scale`, `sturdiness`, `leads_to`, `leads_view`, шаблон `structure`, цена эффекта, правила очистки.
- `app/core/universal/objects.py`: `ObjectState` для постройки, создание, доступность с дальней стороны.
- `app/core/universal/crossing.py` (новый): `cross_structure(ctx, op, event) -> EffectChange`, создание места на той стороне.
- `app/core/universal/interpretation.py`, `exploration_resolution.py`: проверки и маршрутизация `move`.
- `app/agents/master/exploration.py`, `universal.py`: промпты, правила мира в проверке смысла.
- `tools/eval_exploration.py`: новые фразы.

---

### Task 1: Оценка масштаба и цена

**Files:**
- Modify: `app/rules/universal/exploration.py` (EffectIntentV2, `exploration_cost`, `definition_key`, `clean_model_intent`)
- Test: `tests/test_exploration_contracts.py`

**Interfaces:**
- Produces: `EffectIntentV2.scale: Literal["tiny","small","medium","large","huge"] = "tiny"`, `.sturdiness: Literal["fragile","ordinary","sturdy"] = "ordinary"`, `.leads_to: str = ""` (≤128), `.leads_view: str = ""` (≤300); `ObjectTemplate` gains `"structure"`; `SCALE_PRICE: dict[str, int]`; `exploration_cost` prices a `create_object` effect as `SCALE_PRICE[scale] * (2 if sturdy) * level * units` and every other effect as before.

- [ ] **Step 1: Write failing tests** in `tests/test_exploration_contracts.py`: `test_creation_price_follows_the_models_scale_and_sturdiness` (a permanent `create_object` structure: tiny→1, small→3, medium→6, large→12, huge→24 at level 1; `sturdy` large→24; level 2 doubles; timed (units 3) huge→72; the default cup (no `scale`) stays 1); `test_leads_to_is_for_large_creations_only` (small with `leads_to` raises `ValidationError`; large accepts); `test_scale_and_sturdiness_change_the_identity_of_a_creation` (`definition_key` differs between tiny and huge, same for a renamed label).
- [ ] **Step 2: Run** `.venv/Scripts/python.exe -m pytest tests/test_exploration_contracts.py -q -n 0 -k "scale or leads_to"`. Expected: FAIL (unknown field `scale`).
- [ ] **Step 3: Implement** the fields and validator on `EffectIntentV2`; `SCALE_PRICE`; `effect_price(effect, definition, level) -> int` used by `exploration_cost`; add `scale`, `sturdiness`, `leads_to` to the `create_object` entry of `meaningful` in `definition_key`; `clean_model_intent` keeps `scale`, `sturdiness`, `leads_to`, `leads_view`, `template`, `material` for `create_object` and drops `leads_to` when `scale` is below large.
- [ ] **Step 4: Run** the same command plus `tests/test_exploration_contracts.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: price creation by the models scale and sturdiness`.

### Task 2: Свободное создание запоминается как предмет

**Files:**
- Modify: `app/core/universal/objects.py` (`ObjectState`, `apply_object_operation`, `accessible`, `ordinary_object_view`), `app/core/universal/interpretation.py` (drop the vessel-only check)
- Test: `tests/test_exploration_objects.py`, `tests/test_exploration_resolution.py`

**Interfaces:**
- Consumes: Task 1 fields.
- Produces: `ObjectState.template` gains `"structure"`; new `ObjectState` fields `scale`, `sturdiness`, `leads_to: str`, `leads_view: str`, `leads_to_location_id: str | None`; created structure row: `Entity(kind="object", name=op.label or "Постройка", description=op.appearance, location_id=actor.location_id)`, `owner_id=None`; `accessible` also allows a structure whose `leads_to_location_id == actor.location_id`.

- [ ] **Step 1: Write failing tests**: `test_a_structure_is_remembered_and_priced` (resolve a supernatural `create_object` structure `scale="large"`, permanent: one Entity of template `structure` at the hero's location, `owner_id` None, energy debited by 12, a second `resolve_exploration` with the same key adds no entity and debits nothing); `test_another_hero_in_the_place_can_use_the_structure` (`accessible(row, other_hero)` passes, a hero in another place fails); `test_a_timed_structure_expires_with_the_step_clock` (18 s later `object_expired` change, `expired=True`); `test_an_unaffordable_huge_creation_is_refused_with_numbers_and_creates_nothing` (energy 7, `scale="huge"` → `InsufficientEnergy` text «нужно 24, есть 7», no Entity, no Event).
- [ ] **Step 2: Run** `pytest tests/test_exploration_objects.py tests/test_exploration_resolution.py -q -n 0 -k "structure or unaffordable"`. Expected: FAIL («Создаётся только один обычный сосуд»).
- [ ] **Step 3: Implement** the `structure` branch in `apply_object_operation` (key as for the cup, `quantity` must be 1, no material accounting), widen `compile_exploration` so `create_object` accepts template `vessel` or `structure`, add the new fields to `ObjectState`, update `accessible`.
- [ ] **Step 4: Run** the new tests and the existing object/resolution suites. Expected: PASS.
- [ ] **Step 5: Commit** `feat: free-form creations are remembered as place objects`.

### Task 3: Промпты, правила мира и проверка правдоподобия

**Files:**
- Modify: `app/agents/master/exploration.py` (`SYSTEM`, `REVIEW`, review payload), `app/agents/master/universal.py` (context `world_laws`)
- Test: `tests/test_exploration_master.py`

**Interfaces:**
- Consumes: Task 1 fields. Produces: decision context key `world_laws: str` (only the studio's `laws`, never `private`); review payload gains `world_laws`.

- [ ] **Step 1: Write failing tests**: `test_world_laws_reach_the_decision_and_the_review_but_never_the_private_notes` (campaign secret `{"studio": {"laws": "NO TIME TRAVEL", "private": "HIDDEN-SECRET"}}`: the decide prompt's JSON has `world_laws == "NO TIME TRAVEL"` and the review prompt contains `NO TIME TRAVEL`; `HIDDEN-SECRET` appears in neither the review prompt nor the narration prompt); `test_a_creation_review_mismatch_on_scale_refuses_without_spending` (reviewer returns `mismatch` for a «bridge» priced `tiny` → no Event, hero energy unchanged).
- [ ] **Step 2: Run** `pytest tests/test_exploration_master.py -q -n 0 -k "world_laws or scale"`. Expected: FAIL.
- [ ] **Step 3: Implement**: in `SYSTEM` describe free creation (any object or structure, `template="structure"`, choose `scale` by size and effort, `sturdiness`, `leads_to`/`leads_view` only for large/huge that lead somewhere, respect `world_laws`); in `REVIEW` require the scale to be plausible for the description (a bridge is never tiny), the world laws not violated and secrets not revealed; pass `world_laws` into both payloads.
- [ ] **Step 4: Run** the new tests and `tests/test_exploration_master.py`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: world laws and scale plausibility in the creation prompts and review`.

### Task 4: Переход по постройке открывает новое место

**Files:**
- Create: `app/core/universal/crossing.py`
- Modify: `app/core/universal/exploration_resolution.py` (`OBJECT_KINDS` gains `"move"`), `app/core/universal/objects.py` (route `move` with `object_id`), `app/rules/universal/exploration.py` (`clean_model_intent`: keep `resolution="check"` when a `move` effect has `object_id`)
- Test: `tests/test_exploration_crossing.py`

**Interfaces:**
- Consumes: Task 2 structure state.
- Produces: `async def cross_structure(ctx, op, source_event) -> EffectChange` (kind `"moved"`): requires `accessible`, `leads_to` non-empty, not expired; on first crossing creates `Entity(kind="location", name=leads_to, description=leads_view, state={"links": [{"to": origin_id}], "created_by": structure_id})` with id `"en_" + sha256(f"cross:{structure_id}")[:24]`, adds `{"to": new_id, "label": structure.name}` to the origin's `links`, stores `leads_to_location_id`, sets only the actor's `Character.location_id`; crossing from the far side goes back to the origin.

- [ ] **Step 1: Write failing tests** in `tests/test_exploration_crossing.py`: `test_crossing_creates_the_far_place_once_and_moves_only_the_walker` (two heroes at the origin, one crosses: new location exists with links both ways, walker's `location_id` is it, the other's is unchanged; a second crossing by another hero reuses the same location id); `test_crossing_back_from_the_far_side_returns_to_the_origin`; `test_an_expired_or_missing_structure_gives_no_path` (`ValueError` with «пути больше нет», the hero stays); `test_a_failed_check_does_not_move_and_is_told_by_the_models_outcome` (FixedDice fail → `location_id` unchanged, description is the model's `failure` text); `test_a_structure_without_leads_to_cannot_be_crossed`; `test_crossing_is_blocked_in_bush_form` (`FormBlocked`).
- [ ] **Step 2: Run** `pytest tests/test_exploration_crossing.py -q -n 0`. Expected: FAIL (module missing).
- [ ] **Step 3: Implement** `cross_structure`; the savepoint simulation in `resolve_exploration` already covers compound object operations, so `move` with `object_id` is validated before dice and applied only on success.
- [ ] **Step 4: Run** `pytest tests/test_exploration_crossing.py tests/test_exploration_resolution.py tests/test_exploration_contracts.py -q -n 0`. Expected: PASS.
- [ ] **Step 5: Commit** `feat: crossing a structure opens the place on its far side`.

### Task 5: Набор фраз, приёмка и закрытие

**Files:**
- Modify: `tools/eval_exploration.py`, `docs/superpowers/specs/2026-10-25-free-creation-design.md`
- Test: `tests/test_exploration_acceptance.py`

**Interfaces:** Consumes Tasks 1–4.

- [ ] **Step 1: Write the acceptance test** `test_a_hero_grows_a_bridge_and_walks_to_the_far_side` in `tests/test_exploration_acceptance.py` (scripted provider; create a `large` bridge with `leads_to="Дальний край пропасти"`, then a checked `move` with its id succeeds; hero is in the new place; energy after both steps equals start minus 12 plus regeneration).
- [ ] **Step 2: Run** it. Expected: FAIL before the tasks above are complete, PASS after.
- [ ] **Step 3: Extend `tools/eval_exploration.py`** with cases: «создаю лиану, чтобы взобраться по стене» (`create_object`, structure), «выращиваю мост через пропасть» (`create_object`, scale large or huge, `leads_to` set), «строю каменную стену» (scale medium or large), «перехожу по мосту» (state with a bridge object, `move` with its `object_id`), «создаю огромный замок за одну секунду» (informational gap).
- [ ] **Step 4: Run** the full verification: `pytest tests -q -n 4 -k "exploration or universal or mood or voic or regen"`, `ruff check app tests tools`, `docker exec -i -e REPEAT=3 taleforge-app-1 python - < tools/eval_exploration.py`. Expected: all green; the eval prints at most the known flaky observations.
- [ ] **Step 5: Mark** the spec's open points settled and commit `feat: free creation accepted with a bridge walkthrough and eval phrases`.
