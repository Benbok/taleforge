# Добыча в сценах, темп боя и подарки NPC: план реализации

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Игрок может находить и брать предметы в сценах, враг перестаёт отвечать на каждый вздох героя, здоровье медленно восстанавливается отдыхом, а предмет можно подарить NPC ради бонуса к убеждению.

**Architecture:** Всё в универсальном движке (`app/core/universal`, `app/rules/universal`, `app/agents/master`). Добыча строится по идее старого генератора сцен: сервер решает, сколько предметов и каких видов, модель лишь называет и описывает слоты; сила предмета берётся из уже существующего `ItemProfile` (только статус `common`). Предмет лежит в сцене как объект с состоянием `loot`; `take` превращает его в обычный предмет героя через существующий `create_item`.

**Tech Stack:** Python 3.12, SQLAlchemy async, Pydantic v2, pytest (`.venv\Scripts\python -m pytest -n 0`), Ruff.

**Spec:** `docs/superpowers/specs/2026-10-31-universal-loot-tempo-gifts-design.md` (читать целиком до начала).

## Global Constraints

- Только универсальный движок. Не трогать и не импортировать старые каталоги, пакеты контента и `app/tools/master/*`.
- Вся добыча статуса `common`; расходник восстанавливает `hp` на 6; броня `defense_bonus` 1; оружие `1d6` (`str`) или `1d4` (`dex`). Модель чисел не задаёт.
- Бюджет добычи на сцену 0–2 предмета; сложность `deadly` или настройка кампании `loot_enabled: false` дают 0.
- Враг не отвечает на действие, если все его эффекты из `speak`, `observe`, `wait`, `hold_breath` и оно длится не больше 60 игровых секунд. Остальное провоцирует.
- Здоровье: +1 HP за каждые 600 игровых секунд, только вне боя и только у героя в сознании (HP > 0); не выше максимума.
- Бонус подарка: +2 (`common`), +3 (`rare`), +4 (`unique`, `epic`); в сумме на проверку не больше +4; только невраждебному существу в той же сцене; экипированный предмет подарить нельзя.
- Все изменения идемпотентны по ключу шага и ключу запроса: повтор хода не создаёт добычу, HP или подарок дважды.
- Не менять числа урона, защиты и здоровья существ. Деньги и контейнеры не вводить.
- Python-стиль проекта: Ruff (`ruff check` и `ruff format`), строки до 120 знаков, русские комментарии и сообщения пользователю, как в соседнем коде.
- Не добавлять к 14 заранее падающим тестам новых падений: `tests/test_db_startup.py`, `tests/test_llm_sampling.py`, `tests/test_voice_emotion_context.py::test_compact_voice_keeps_persona_mood_public_results_and_small_limit`.

## Review Focus

Входы, которые спека подразумевает, но задачи прямо не называют; тест для каждого добавлен в задачу-владельца.

1. Один и тот же предмет берут дважды или двое героев сразу: второй получает отказ, предмет один (Задача 5).
2. Сцена без добычи: бюджет 0 при `deadly`, при `loot_enabled: false`, при пустом ответе модели; ответ модели с лишним предметом обрезается, с недостающим дополняется нейтральным именем (Задачи 3, 4).
3. Подарок экипированного, чужого или несуществующего предмета и подарок врагу (Задача 6).
4. Действие ровно 60 и 61 секунда, реплика героя, который лежит без сознания, смешанное действие «сказать и взять» (Задача 1).
5. Восстановление здоровья при повторе шага, при HP 0, в бою и у героя с полным здоровьем; остаток времени не теряется между короткими шагами (Задача 2).

---

## File Structure

- Create `app/core/universal/provocation.py` — когда враг отвечает.
- Modify `app/core/universal/combat.py` — вызов `provokes` в `eligible_enemies`.
- Modify `app/core/universal/regeneration.py`, `app/core/universal/clock.py` — восстановление здоровья.
- Create `app/core/universal/loot.py` — бюджет, слоты, профиль, подбор, представление.
- Modify `app/rules/universal/world.py` — схема `WorldLoot` и поле `WorldScenePlan.items`.
- Modify `app/core/universal/world_generation.py` — слоты в контексте, создание предметов сцены.
- Modify `app/agents/master/world.py` — подсказки генератора сцены.
- Modify `app/core/universal/objects.py` — предмет сцены в `visible_objects`.
- Modify `app/core/universal/interpretation.py`, `app/core/universal/exploration_resolution.py` — проверка и исполнение `take` и `give`.
- Create `app/core/universal/gifts.py` — подарок NPC и бонус.
- Modify `app/agents/master/prompting/modules.py`, `app/agents/master/universal_narration.py` — подсказки модели и рассказчика.
- Tests: `tests/test_universal_provocation.py`, `tests/test_universal_health_regen.py`, `tests/test_universal_loot.py`, `tests/test_universal_gifts.py` (новые); существующие хелперы: `tests/test_universal_resolution.py::setup`, `tests/test_exploration_resolution.py::prepare`, `tests/test_universal_exchange.py::enemy`, `tests/test_universal_world_exploration.py::world_setup`.

---

### Задача 1: враг отвечает не на каждое действие

**Files:**
- Create: `app/core/universal/provocation.py`
- Modify: `app/core/universal/combat.py` (начало `eligible_enemies`, около строки 30)
- Test: `tests/test_universal_provocation.py`

**Interfaces:**
- Produces: `QUIET_KINDS: frozenset[str]` (`speak`, `observe`, `wait`, `hold_breath`), `QUIET_SECONDS: int = 60`, `provokes(action: ExplorationAction) -> bool`.

- [ ] **Step 1: Write the failing tests** в `tests/test_universal_provocation.py`:
  - `test_quiet_words_and_looking_do_not_provoke`: действия из `speak`, из `observe`, из `wait`, из `speak`+`wait` с `elapsed_game_seconds` 6 и 60 → `provokes(...) is False`.
  - `test_anything_else_provokes`: `move`, `take`, `weapon_attack`, `free_effect` → `True`; `speak` с `elapsed_game_seconds=61` → `True`; `speak`+`take` → `True`.
  - `test_a_quiet_action_gets_no_enemy_reply_but_an_attack_does`: через `setup` и `enemy` (как в `tests/test_universal_review_regressions.py::test_observer_enemy_can_reply`) построить враждебного врага рядом с героем; `run_exchange` для `wait` даёт `len(results) == 1`, для атаки (`attack` из `tests/test_universal_combat_actions.py`) даёт `len(results) == 2`.
  - `test_a_quiet_exchange_replayed_adds_no_reply`: повтор `run_exchange` с тем же ключом возвращает те же результаты, ответа врага нет.
  - `test_a_downed_hero_waiting_gets_no_reply_either`: герой на 0 HP (`vitality` как в `_down` из `tests/test_universal_review_regressions.py`) ждёт 6 секунд → ответа нет.
- [ ] **Step 2: Run:** `.venv\Scripts\python -m pytest -n 0 tests/test_universal_provocation.py -q`; ожидается FAIL (модуля нет).
- [ ] **Step 3: Implement** `provokes(action)` в новом модуле: `not (action.operations and all(op.kind in QUIET_KINDS for op in action.operations) and action.elapsed_game_seconds <= QUIET_SECONDS)`. В `eligible_enemies` первой строкой: `if not provokes(ExplorationAction.model_validate(exchange.proposal)): return []` (импорт `ExplorationAction` уже есть в `combat.py`).
- [ ] **Step 4: Run** тесты задачи и `tests/test_universal_combat_actions.py tests/test_universal_combat_playthrough.py tests/test_universal_exchange.py tests/test_universal_review_regressions.py -q`; ожидается PASS. Если старый тест ждал ответа на тихое действие, поправить его под новое правило (в `observer`-тесте враг-наблюдатель отвечает на `wait` — этот тест перевести на действие `take` и оставить смысл).
- [ ] **Step 5: Commit** `feat(combat): the enemy answers only to what concerns it`.

### Задача 2: восстановление здоровья отдыхом

**Files:**
- Modify: `app/core/universal/regeneration.py`, `app/core/universal/clock.py` (рядом с `regenerate_energy`)
- Test: `tests/test_universal_health_regen.py`

**Interfaces:**
- Produces: `HEALTH_REGEN_SECONDS = 600`; `async def regenerate_health(session, campaign_id, elapsed_seconds: int) -> None`. Остаток секунд хранится в `hero.resources["hp_regen_carry"]` (строка с целым).

- [ ] **Step 1: Write the failing tests:**
  - `test_an_hour_of_rest_gives_six_hit_points_out_of_combat`: герой с HP 10 из максимума, `complete_step(s, "c", "k", 3600, dice=FixedDice([]))` → HP `"16"`.
  - `test_short_steps_add_up_without_losing_the_remainder`: сто steps по 6 секунд (600) → ровно +1 HP, ещё 99 → ещё +0, затем следующий → +1 (проверить через `hp_regen_carry`).
  - `test_nothing_comes_back_in_combat_at_zero_or_at_full_health`: рядом враг → без изменений; HP 0 (`stable`) → без изменений; HP на максимуме → остаётся и `hp_regen_carry` не растёт.
  - `test_a_replayed_step_restores_nothing_twice`: тот же `source_key` ещё раз → HP тот же.
  - `test_it_never_passes_the_maximum`: HP на 1 ниже максимума, шаг 3600 → ровно максимум.
- [ ] **Step 2: Run:** FAIL.
- [ ] **Step 3: Implement** `regenerate_health`: для каждого героя `active`/`approved`, не в бою (`encounters.in_combat`, как в `regenerate_energy`), с HP > 0 и HP < максимума (`derive(sheet, starting_defense_bonuses(sheet)).hp_max`): `carry += elapsed_seconds`; `gain, carry = divmod(carry, 600)`; HP = `min(max, hp + gain)`; сохранить HP и остаток в `hero.resources`. Вызвать из `app/core/universal/clock.py::_complete_step` сразу после `regenerate_energy`.
- [ ] **Step 4: Run** тесты задачи, `tests/test_universal_review_regressions.py tests/test_exploration_resolution.py -q`; PASS.
- [ ] **Step 5: Commit** `feat(vitality): slow natural recovery of health while resting`.

### Задача 3: бюджет и профиль добычи (чистые функции)

**Files:**
- Create: `app/core/universal/loot.py`
- Test: `tests/test_universal_loot.py`

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class LootSlot: ref: str; kind: Literal["consumable", "weapon", "armor"]`
  - `def loot_slots(campaign, location_id: str) -> list[LootSlot]` — детерминированно по `campaign.id`, `location_id`, `campaign.difficulty`; `[]` если `campaign.settings.get("loot_enabled") is False` или сложность `deadly`; ссылки `loot_1`, `loot_2`.
  - `def loot_profile(slot: LootSlot, name: str, description: str, attribute: str = "str") -> ItemProfile` — `status="common"`; `consumable`: `restore_pool="hp"`, `restore_amount=6`; `weapon`: `attribute` из `str|dex`, `base_dice` `1d6` для `str` и `1d4` для `dex`; `armor`: `defense_bonus=1`.
  - `FALLBACK_NAMES: dict[str, str]` — `consumable`: «Фляга с настойкой», `weapon`: «Потёртый нож», `armor`: «Кожаная куртка».
- Таблица числа предметов по сложности (в `loot.py`, одной константой): `easy` — 0 (20%), 1 (50%), 2 (30%); `normal` — 0 (30%), 1 (60%), 2 (10%); `hard` — 0 (60%), 1 (40%); `deadly` — только 0. Число берётся из `int(sha256(f"loot:{campaign.id}:{location_id}")...)`; вид слота: consumable 50%, weapon 25%, armor 25% по другому байту того же хеша.

- [ ] **Step 1: Write the failing tests:**
  - `test_slots_are_deterministic_and_bounded`: одни и те же аргументы дают один список; для 200 разных `location_id` на `normal` число слотов всегда 0–2, ссылки `loot_1`, `loot_2` без дублей.
  - `test_the_table_is_followed`: на 2000 разных локаций доли чисел на `normal` попадают в 30/60/10% ±8 п.п.; на `deadly` и при `loot_enabled=False` всегда `[]`.
  - `test_profile_numbers_come_from_the_server`: для каждого вида `loot_profile` проходит `ItemProfile.model_validate`, статус `common`, числа как в Global Constraints; `weapon` с `attribute="dex"` даёт `1d4`; неизвестный атрибут → `ValueError`.
- [ ] **Step 2: Run:** FAIL.
- [ ] **Step 3: Implement** модуль по интерфейсам выше (хеш → два независимых байта: на число и на виды).
- [ ] **Step 4: Run** `tests/test_universal_loot.py -q`; PASS.
- [ ] **Step 5: Commit** `feat(loot): server-side loot budget and bounded item profiles`.

### Задача 4: генератор сцены создаёт добычу

**Files:**
- Modify: `app/rules/universal/world.py` (после `WorldPassage`), `app/core/universal/world_generation.py` (`scene_reservation` — добавить `loot_slots` в контекст около строки 140; `publish_scene` — после создания объектов около строки 197), `app/agents/master/world.py` (`PLAN_SYSTEM`, `REVIEW_SYSTEM`)
- Test: `tests/test_universal_loot.py` (дополнить), `tests/test_universal_world_exploration.py` (существующие должны проходить)

**Interfaces:**
- Consumes: `LootSlot`, `loot_slots`, `loot_profile`, `FALLBACK_NAMES` из Задачи 3.
- Produces: `class WorldLoot(ClosedModel): ref: str (шаблон ^loot_[12]$); name: str (1–100); description: str (до 600, по умолчанию ""); attribute: Literal["str","dex"] = "str"`; `WorldScenePlan.items: list[WorldLoot] = Field(default_factory=list, max_length=2)` (общая проверка уникальности ссылок включает `items`). Контекст резервирования получает ключ `loot_slots: list[{ref, kind}]`. `publish_scene` создаёт по одному `Entity(kind="object")` на слот с состоянием `{"universal_scene_ref": row.id, "loot": <ItemProfile.model_dump(mode="json")>}`, идентификатор `entity_id(campaign_id, location.id, "loot:" + ref)`, местоположение — текущая сцена.

- [ ] **Step 1: Write the failing tests:**
  - `test_the_scene_context_carries_the_loot_slots`: `scene_reservation(...)` для кампании на `normal` с известным хешем возвращает `context["loot_slots"] == [{"ref": "loot_1", "kind": ...}]` (взять локацию, для которой `loot_slots` непустой; тест подбирает её циклом).
  - `test_a_published_scene_holds_the_loot_as_objects`: `publish_scene` с планом, где `items` совпадает со слотами → в БД ровно N объектов с ключом `loot` в состоянии, профили через `loot_profile`, имена от модели.
  - `test_extra_items_are_cut_and_missing_ones_are_filled`: план с 2 предметами при 1 слоте → создан 1; план без `items` при 1 слоте → создан 1 с `FALLBACK_NAMES[kind]`; при 0 слотов предметы модели игнорируются.
  - `test_loot_is_not_built_twice`: повторная публикация той же сцены не создаёт дублей (как для объектов: `Blocked("identity_conflict")` не должен всплыть наружу для уже опубликованной фазы).
- [ ] **Step 2: Run:** FAIL.
- [ ] **Step 3: Implement** схему и поле; в `scene_reservation` добавить `loot_slots=[{"ref": s.ref, "kind": s.kind} for s in loot_slots(campaign, location.id)]`; в `publish_scene` брать слоты из `row.reservation["context"]["loot_slots"]` (не пересчитывать), сопоставлять `plan.items` по `ref`, обрезать лишнее и дополнять пропущенное `FALLBACK_NAMES`. В `PLAN_SYSTEM` заменить абзац «Вещи из сцены героям не достаются…» правилом: «В context.loot_slots перечислены предметы, которые можно найти в этой сцене: верни items по одному на слот (ref, name, description, для оружия attribute str или dex). Числа, статус и количество не указывай. Других вещей, которые можно взять, не описывай: остальное — обстановка.» В `REVIEW_SYSTEM` добавить нарушение: предмет в `items` без слота или вещь из описания, которая выглядит добычей, но не записана в `items`.
- [ ] **Step 4: Run** `tests/test_universal_loot.py tests/test_universal_world_exploration.py -q -k "loot or scene or world"` и `-k "world or admission"` по всему `tests`; PASS.
- [ ] **Step 5: Commit** `feat(loot): scene preparation creates server-budgeted loot`.

### Задача 5: предмет сцены видно и можно взять

**Files:**
- Modify: `app/core/universal/loot.py` (добавить `loot_view`, `pick_up`), `app/core/universal/objects.py::visible_objects`, `app/core/universal/interpretation.py::validate_exploration` (проверка операций над объектом, около строки 300), `app/core/universal/exploration_resolution.py::_objects` (ветка `take`, около строки 119)
- Test: `tests/test_universal_loot.py`

**Interfaces:**
- Produces: `def loot_view(row: Entity) -> dict` (`id`, `name`, `description`, `location_id`, `template="loot"`, `loot_kind`); `async def pick_up(ctx, row: Entity, source_event: Event, index: int) -> EffectChange` — вызывает `create_item(ctx.session, ctx.campaign_id, ctx.actor_id, ItemProfile.model_validate(row.state["loot"]), f"loot:{row.id}")`, затем `row.location_id = None` и `row.state = {**row.state, "taken_by": ctx.actor_id}`; возвращает `EffectChange(kind="item_taken", subject_id=<id предмета героя>, description="«<имя>» теперь у героя.")`. Если `row.location_id` не равен месту героя или предмет уже взят — `ValueError("Предмет уже взят или лежит в другом месте")`.

- [ ] **Step 1: Write the failing tests:**
  - `test_loot_is_listed_among_the_visible_objects`: `visible_objects` возвращает запись `loot_view` для лежащего предмета и не возвращает взятый.
  - `test_take_moves_the_item_into_the_inventory`: действие с `take` по предмету сцены → у героя в `owned_items` один предмет с профилем из `state["loot"]`, предмет сцены без `location_id`, исход содержит `item_taken`.
  - `test_the_second_take_is_refused_and_the_item_stays_single`: второй `take` тем же героем и вторым героем (другая `seat`/персонаж) → отказ с `ValueError` на разборе; `owned_items` всё равно один.
  - `test_replayed_take_is_not_a_second_item`: повтор `resolve_exploration` с тем же ключом (`status == "repeated"`) предметов не добавляет.
  - `test_loot_cannot_be_used_as_raw_material`: `place`, `give`, `fill`, `pour`, `move` с `object_id` предмета сцены → `ValueError` на разборе («можно только взять»).
  - `test_an_item_in_another_place_cannot_be_taken`: герой в другой локации → отказ.
  - Для действий использовать `prepare`/`build` из `tests/test_exploration_resolution.py` по образцу `test_a_structure_is_remembered_priced_and_not_built_twice`.
- [ ] **Step 2: Run:** FAIL.
- [ ] **Step 3: Implement.** `visible_objects`: после обычного цикла добавить `loot_view(row)` для сущностей `kind == "object"` с `"loot" in row.state`, `row.location_id == actor.location_id` и без `hidden`. `validate_exploration`: в цикле по `object_id/source_id` перед `accessible(obj, actor)` — ветка для `obj is not None and "loot" in obj.state`: если `op.kind != "take"` → `ValueError("Предмет из сцены можно только взять")`, иначе проверить место героя и `taken_by` (то же `ValueError`). `_objects`: ветка `take` перед обращением к `apply_object_operation`: если `"loot" in item.state` → `changes.append(await pick_up(ctx, item, event, index))`; `continue`.
- [ ] **Step 4: Run** `tests/test_universal_loot.py tests/test_exploration_resolution.py tests/test_exploration_crossing.py tests/test_universal_world_exploration.py -q`; PASS.
- [ ] **Step 5: Commit** `feat(loot): scene items can be found and taken`.

### Задача 6: подарок NPC и бонус к убеждению

**Files:**
- Create: `app/core/universal/gifts.py`
- Modify: `app/core/universal/interpretation.py` (разрешить `give` для своего снаряжения, около строки 285), `app/core/universal/exploration_resolution.py` (`_objects`: ветка `give` для предмета героя; `_execute`: бонус к проверке около строки 212)
- Test: `tests/test_universal_gifts.py`

**Interfaces:**
- Produces: `GIFT_BONUS = {"common": 2, "rare": 3, "unique": 4, "epic": 4}`; `GIFT_BONUS_CAP = 4`; `async def give_item_to_creature(ctx, item_row: Entity, creature_row: Entity, source_event: Event, index: int) -> EffectChange` — у предмета `quantity` становится 0, в `creature_row.state["gifts"]` добавляется имя предмета, возвращается `EffectChange(kind="item_given", subject_id=creature_row.id, description="«<предмет>» передан: <имя существа>.")`; `async def gift_bonus(ctx, action: ExplorationAction) -> int` — сумма по операциям `give` из исходного действия (до исполнения) со статусом предмета, не больше `GIFT_BONUS_CAP`; 0, если `action.resolution != "check"` или нет операции `speak`.
- Правила отказа (`ValueError` на разборе, до броска): получатель не существо, не в сцене героя, враждебен (`state["hostile"]`), без `recipient_id`; предмет чужой, экипированный или с `quantity < 1`.

- [ ] **Step 1: Write the failing tests:**
  - `test_a_gift_moves_the_item_to_the_creature_and_leaves_the_hero_without_it`.
  - `test_a_gift_before_persuasion_adds_the_bonus_to_the_check`: проверка `speak`+`give` с `FixedDice([x])`, где без бонуса провал, а с +2 успех; `result.total` на 2 больше, чем у такой же проверки без подарка.
  - `test_the_bonus_is_capped_and_needs_a_speak_check`: подарок без `speak` или при `resolution="automatic"` → бонус 0; три подарка → не больше +4.
  - `test_refused_gifts`: враждебному существу, герою-получателю не из сцены, экипированному предмету, чужому предмету, несуществующему id → `ValueError` на разборе, предмет остаётся у героя.
  - `test_a_replayed_gift_is_not_given_twice`.
- [ ] **Step 2: Run:** FAIL.
- [ ] **Step 3: Implement.** В `validate_exploration` ветка `universal_item`: добавить `give` в разрешённые виды при выполнении правил отказа выше (проверка владельца уже есть через `_owned`). В `_objects`: ветка `give` для предмета с `universal_item` (рядом с `take`/`consume`): `give_item_to_creature(...)`. В `_execute`: `bonus = await gift_bonus(ctx, action)`; `resolve_check(dice, score, False, action.difficulty, action.edge, bought + bonus)` (и в ветке предрасчёта `ctx.invest`, чтобы цена вложения считалась с тем же бонусом).
- [ ] **Step 4: Run** `tests/test_universal_gifts.py tests/test_exploration_resolution.py tests/test_universal_combat_actions.py -q`; PASS.
- [ ] **Step 5: Commit** `feat(social): gifts to NPCs give a bonus to persuasion`.

### Задача 7: подсказки моделям, документы, общая проверка

**Files:**
- Modify: `app/agents/master/prompting/modules.py` (модуль объектов: добавить предложения, не трогая старые — защитный тест `tests/test_prompting_modules.py` требует сохранения прежних предложений), `app/agents/master/universal_narration.py`, `docs/universal-orientation-generation.md` (убрать «loot» из исключений и описать добычу), новый короткий раздел в `docs/universal-combat.md` про темп и восстановление.
- Test: `tests/test_prompting_modules.py` (существующий), прогон всего набора.

- [ ] **Step 1: Write the failing test** `test_object_module_tells_loot_can_be_taken_and_gifts_given` в `tests/test_prompting_modules.py`: текст модуля объектов содержит «template=loot» и «give». Run: FAIL.
- [ ] **Step 2: Implement.** В `modules.py` добавить предложения: «Предмет сцены с template=loot можно только взять эффектом take; взятый становится снаряжением героя.» и «Подарок предмета невраждебному существу в той же сцене оформляй эффектом give с recipient_id рядом со speak: он усиливает убеждение.» В `universal_narration.py` убрать из правила «Не придумывай… предметы» исключение, если оно мешает упоминать предметы сцены; добавить: «Предметы сцены (template=loot) и inventory можно упоминать; других вещей не вводи.»
- [ ] **Step 3: Run** `tests/test_prompting_modules.py tests/test_universal_narration_style.py tests/test_prompting_review_narration.py -q`; PASS.
- [ ] **Step 4: Run всё:** `.venv\Scripts\python -m pytest -q -p no:cacheprovider tests`; ожидается только те же 14 падений из Global Constraints. `ruff check` и `ruff format --check` по изменённым файлам чисты. Затем `graphify update .`.
- [ ] **Step 5: Живая проверка** (описание сценария, не код): по `docs/` или по заметкам команды поднять копию приложения с копией базы, запустить игру из опубликованной версии мира, сыграть: осмотр, взять предмет сцены, надеть его, ударить врага, «сказать» врагу фразу (ответа нет), подождать час (HP +6 вне боя), подарить предмет NPC перед убеждением. Записать результат в сообщение для заказчика.
- [ ] **Step 6: Commit** `feat(universal): prompts and docs for loot, quiet actions and gifts`.

## Self-review

- Покрытие спеки: §4.1 (Задача 1), §4.2 (2), §5.1–5.2 (3, 4), §5.3 (5; изменение `perception.py` из спеки не понадобилось: предмет сцены хранится не как `universal_item`, поэтому наблюдение его не пропускает; проверить при реализации Задачи 5 тестом `test_loot_is_listed...` и при необходимости поправить), §5.4 и §6 (6, 7). Сценарии приёмки §9: п.1–2 → Задачи 4–5; п.3 → 1; п.4 → 2; п.5 → 6; п.6–7 → Задача 7.
- Отличие от спеки: добыча хранится в `state["loot"]`, а не как `universal_item` без владельца — так не нужно менять схему `ItemState` и фильтры сцены; в спеке это названо «состоянием `universal_item`», при реализации действует это решение плана.
