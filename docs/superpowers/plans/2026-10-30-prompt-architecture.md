# Лёгкий вход модели Implementation Plan

**Status:** выполнен 30 октября 2026. Итог: 74/100 против 70/100, средний вход
9041,4 против 11925,2 токенов (−24,2%). Финальный полный прогон: 2667 passed,
24 skipped. Два важных замечания независимого обзора исправлены. Результаты,
решения и отложенный небольшой случай null-снимков: `docs/prompt-architecture.md`
и `docs/prompt-architecture-review.md`.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Сократить вход модели на каждый ход (правила движка отдельно, лор кампании по требованию) без потери качества, доказанной набором типовых реплик.

**Architecture:** Три слоя: стабильный префикс (ядро промпта + схема), модули правил по состоянию хода, нарезчики контекста и указатель лора. Каждый слой вливается только если результат на наборе реплик не хуже базового.

**Tech Stack:** Python 3.12, FastAPI/SQLAlchemy, Pydantic 2, LiteLLM, pytest (`ScriptedLLM` для детерминированных тестов).

**Spec:** `docs/superpowers/specs/2026-10-30-prompt-architecture-design.md`

## Global Constraints

- Только универсальный движок (`ruleset_id == "universal"`); видимое игроку поведение и тексты не меняются.
- Не трогать незавершённую работу над артом, портретами и озвучкой.
- Качество важнее экономии: шаг не вливается, если доля успехов на наборе (`tests/eval`) ниже базовой в `tests/eval/baseline.json` более чем на 1 реплику из 20.
- Отбор лора лексический, детерминированный, без эмбеддингов.
- Модули подключаются кодом по состоянию хода, без отдельного вызова модели. Неоднозначное состояние: модуль **включается** (fail open).
- Стабильная часть запроса (ядро, схема) идёт первой и байт-в-байт одинакова между ходами.
- Прогон набора на реальной модели допустим (ответ владельца), в CI он не входит.
- Бэкенд проверяется: `.venv/Scripts/python.exe -m pytest <path> -q --timeout=90 -p no:cacheprovider -n 4`; перед коммитом `ruff check` и `ruff format` на изменённых файлах.

## Review Focus

Входы и условия, которых тесты задач сами не покажут, наиболее вероятные первыми:
1. Реплика ссылается на правило лора другими словами, чем в тексте мира: нужный блок не отобран. Ожидание: модель просит `need_lore`, сервер добавляет блок, ход не теряется (задача 8).
2. Русская морфология: «дверь/двери/дверью», «зал/залу». Ожидание: совпадение по основе слова (задача 7).
3. Мир без сил, без законов или с пустым лором (другая кампания). Ожидание: модули, блоки лора и нарезчики не падают на пустом (задачи 6, 7, 8).
4. Повторный запрос после отказа валидатора (`repair`) не ломает стабильный префикс. Ожидание: префикс тот же (задача 4).
5. Смена модели мастера на провайдера без префиксного кэша. Ожидание: поведение то же, кэш-разметка не ломает запрос (задача 4).

---

### Task 1: Чистая сборка запроса и счётчик размера

**Files:**
- Create: `app/agents/master/prompting/__init__.py`, `app/agents/master/prompting/messages.py`
- Modify: `app/agents/master/exploration.py` (вызов сборки в `obtain_exploration_action`)
- Test: `tests/test_prompting_messages.py`

**Interfaces:**
- Produces: `decide_messages(context: dict, repair: str | None = None) -> list[dict]` — ровно то, что сегодня уходит модели как `[system SYSTEM, user json(context + capabilities + repair)]`.
- Produces: `request_size(messages: list[dict], tool_schema: dict) -> dict[str, int]` — символы: `system`, `schema`, `context.<ключ>` для каждого верхнего ключа контекста, `total`.

- [x] **Step 1: Test** `test_decide_messages_match_the_previous_request`: для контекста `{"source": "иду", "scene": {}}` и `repair="x"` результат равен сборке из старого кода (две роли; user — `json.dumps({**context, "capabilities": exploration_capabilities(), "repair": "x"}, ensure_ascii=False)`); `test_request_size_counts_every_context_key`: сумма `context.*` + `system` + `schema` == `total`.
- [x] **Step 2:** Run `pytest tests/test_prompting_messages.py` — Expected: FAIL (module missing).
- [x] **Step 3:** Implement both functions in `messages.py`; replace the inline construction in `obtain_exploration_action` with `decide_messages(context, repair)` where `repair = (hint or last_failure.message) if attempts[mid] > 1 else None`.
- [x] **Step 4:** Run `pytest tests/test_prompting_messages.py tests/test_exploration_master.py tests/test_action_admission.py` — Expected: PASS.
- [x] **Step 5:** Commit `refactor(prompting): pure decide_messages and request_size`.

### Task 2: Снимки контекста для набора

**Files:**
- Create: `tests/eval/__init__.py`, `tests/eval/capture.py`, `tests/eval/fixtures/shire.json`, `tests/eval/fixtures/station.json`
- Test: `tests/test_eval_capture.py`

**Interfaces:**
- Produces: `async capture_context(session, campaign_id: str, source: str) -> dict` — тот же словарь, что строит `run_universal_turn` (без `capabilities`), с подставленным `source`. Вынести построение контекста из `run_universal_turn` (`app/agents/master/universal.py`, блок `context = dict(...)`) в `build_decide_context(session, campaign, hero, seat, msg_text) -> dict` в `app/agents/master/prompting/context.py`, чтобы им пользовались и ход, и снимок.
- Produces: `python -m tests.eval.capture <campaign_id> "<реплика>" <имя>` пишет `tests/eval/fixtures/<имя>.json`.

- [x] **Step 1: Test** `test_build_decide_context_has_the_same_keys_as_before`: для кампании из `tests/test_universal_resolution.py::setup` ключи равны `{world_development, world, world_rules, hero, resources, scene, history, source, established_evidence, objects, inventory, known_exits, constraints, active_effects, known_abilities}`.
- [x] **Step 2:** Run — Expected: FAIL.
- [x] **Step 3:** Extract `build_decide_context`; `run_universal_turn` calls it. Write `capture.py`.
- [x] **Step 4:** Run `pytest tests/test_eval_capture.py tests/test_universal_world_exploration.py tests/test_exploration_master.py` — Expected: PASS.
- [x] **Step 5:** In the container, capture two fixtures: `shire.json` from the live campaign (`c_169836e8c8cf8520`, hero at «Придорожный постоялый двор», реплика «захожу в постоялый двор») and `station.json` — written by hand: small sci-fi world (орбитальная станция, шлюз `locked`, нет магии, пустые `world.powers`), to prove the engine is not tied to one lore. Commit `test(eval): context fixtures from two different worlds`.

### Task 3: Набор реплик, проверка исхода, прогонщик, базовый замер

**Files:**
- Create: `tests/eval/cases.py`, `tests/eval/checks.py`, `tests/eval/run.py`, `tests/eval/baseline.json`
- Test: `tests/test_eval_checks.py`

**Interfaces:**
- Produces: `@dataclass EvalCase(name: str, fixture: str, source: str, expect: Expect)` and `@dataclass Expect(effect_kinds: set[str] = set(), destination: str | None = None, resolution: str | None = None, recipient: bool = False, forbid_kinds: set[str] = set(), quotes_from_source: bool = True)`.
- Produces: `check(case: EvalCase, raw_intent: dict) -> list[str]` — список нарушений; пуст = успех. Использует `clean_model_intent` и `IntentV2.model_validate`; всегда проверяет, что каждая `requirements[].quote` — подстрока `case.source`.
- Produces: `python -m tests.eval.run [--n 5] [--cases a,b] [--save]` — для каждой реплики N вызовов реальной модели по `decide_messages`, печатает таблицу: доля успехов, средние `tokens_in`, `tokens_cached`, число частей запроса (`request_size`); `--save` пишет `baseline.json`.

- [x] **Step 1: Test** `check` на готовых ответах: вход в зал `move→destination` проходит; `observe` вместо `move` даёт нарушение «нет effect move»; цитата не из source даёт нарушение; реплика-вопрос существу без `speak` даёт нарушение; чистая речь с `resolution="check"` даёт нарушение (`resolution` ожидается `automatic`). Все тесты на словарях, без модели.
- [x] **Step 2:** Run — Expected: FAIL.
- [x] **Step 3:** Implement `checks.py`, `cases.py` (≥16 реплик, обе фикстуры): переход в известное место; вход в закрытую дверь; вход в запертую (`locked`) — `move` не ожидается; речь с существом; вопрос без риска; взять предмет; отдать предмет, которого нет (ожидание: не `give` несуществующего); магия в мире с магией и в мире без (`station`: не `supernatural`); звук без тела (не создавать враждебное существо); обычный осмотр; подход внутри сцены; ожидание; опечатка в реплике («ахожу в зал»). `run.py` с отчётом.
- [x] **Step 4:** Run `pytest tests/test_eval_checks.py` — Expected: PASS. Then in the container: `python -m tests.eval.run --n 5 --save` (реальная модель мастера по умолчанию).
- [x] **Step 5:** Commit `test(eval): reply set, outcome checks, runner and the baseline`. **Gate:** дальнейшие задачи сравнивают с этим `baseline.json`.

### Task 4: Стабильный префикс и кэш-разметка

**Files:**
- Modify: `app/agents/master/prompting/messages.py`, `app/agents/master/exploration.py`, `app/agents/llm.py` (только разметка кэша)
- Test: `tests/test_prompting_prefix.py`

**Interfaces:**
- Consumes: `decide_messages`, `exploration_capabilities()`.
- Produces: `decide_messages` кладёт статичное (`capabilities`) в system-сообщение; user-сообщение содержит только переменные данные, `repair` последним. `cacheable(messages: list[dict], model: str) -> list[dict]` — для моделей `anthropic/*` и `claude*` помечает system-блок `cache_control={"type": "ephemeral"}`, для остальных возвращает без изменений.

- [x] **Step 1: Test** `test_system_message_and_tools_are_identical_between_turns` (два разных контекста и `repair` дают равный `messages[0]`); `test_repair_goes_last_in_the_user_message`; `test_cache_marker_only_for_anthropic_models` (deepseek-запрос не получает `cache_control`).
- [x] **Step 2:** Run — Expected: FAIL.
- [x] **Step 3:** Implement. В `_call` (`app/agents/master/universal.py`) применить `cacheable(payload, model)` для `exploration_decide`, `intent_review`.
- [x] **Step 4:** Run `pytest tests/test_prompting_prefix.py tests/test_exploration_master.py tests/test_action_admission.py` — Expected: PASS. Then `python -m tests.eval.run --n 5`; доля успехов не ниже базовой; сохранить в отчёте `tokens_cached`.
- [x] **Step 5:** Commit `feat(prompting): stable prefix and cache marker`.

### Task 5: Правила, которые проверяет код, уходят из промпта

**Files:**
- Create: `docs/prompt-rules.md`
- Modify: `app/agents/master/exploration.py` (`SYSTEM`), `app/core/universal/interpretation.py`, `app/rules/universal/exploration.py`
- Test: `tests/test_prompt_rules_enforced.py`

**Interfaces:**
- Produces: `docs/prompt-rules.md` — таблица «предложение из `exploration.SYSTEM` → где проверяется: схема / валидатор / только модель». Для каждого предложения, помеченного «валидатор» или «схема», в тестах есть отказ с понятным текстом.

- [x] **Step 1:** Разобрать `SYSTEM` по предложениям, заполнить таблицу `docs/prompt-rules.md` (колонки: предложение, слой проверки, тест).
- [x] **Step 2: Test** по одному тесту на каждое правило с пометкой «валидатор» и сейчас без явного теста (например, `quote` не из source; `destination_id` вне `known_exits`; `move` без `travel_scope`): отказ с текстом, называющим причину и ход исправления.
- [x] **Step 3:** Run — Expected: FAIL там, где проверки или текста нет; добавить проверки и тексты.
- [x] **Step 4:** Удалить из `SYSTEM` предложения, дублирующие проверку с понятным отказом; в таблице пометить «убрано».
- [x] **Step 5:** Run `pytest tests/test_prompt_rules_enforced.py tests/test_exploration_interpretation.py tests/test_exploration_master.py` — PASS. `python -m tests.eval.run --n 5` — не хуже базового. Commit `refactor(prompting): rules the code enforces leave the prompt`.

### Task 6: Модули правил с гейтингом

**Files:**
- Create: `app/agents/master/prompting/modules.py`
- Modify: `app/agents/master/exploration.py` (`SYSTEM` → ядро + модули), `app/agents/master/prompting/messages.py`
- Test: `tests/test_prompting_modules.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) PromptModule(name: str, text: str, applies: Callable[[dict], bool])`; `CORE: str`; `MODULES: tuple[PromptModule, ...]` в фиксированном порядке: `travel`, `objects`, `magic`, `speech`, `combat`, `rewards`; `select_modules(context: dict) -> list[PromptModule]`; `compose_system(context: dict) -> str` = `CORE` + выбранные модули.
- Gating: `travel` — есть `known_exits` или `scene.exits`; `objects` — есть `objects` или `inventory`; `magic` — у `world_rules.powers` непустой текст **или** реплика содержит корни магии; `speech` — в сцене есть существа; `combat` — в сцене враждебные или `mode == "combat"`; `rewards` — всегда выключен по умолчанию, включается при `reward` в истории хода. Любое неоднозначное состояние (нужный ключ отсутствует) — модуль включён.

- [x] **Step 1: Test** (1) `test_no_sentence_of_the_old_prompt_is_lost`: каждое предложение старого `SYSTEM` (сохранить копию в `tests/data/old_exploration_system.txt`) входит в `CORE` или в текст одного из модулей либо помечено «убрано» в `docs/prompt-rules.md`; (2) `test_modules_follow_the_state` для пустого мира (без выходов, предметов, сил) выбирается только `CORE`; для мира с выходами — `travel`; (3) `test_ambiguous_state_includes_the_module` (контекст без ключа `objects`) → `objects` включён; (4) `test_order_is_fixed`.
- [x] **Step 2:** Run — FAIL.
- [x] **Step 3:** Implement; `decide_messages` использует `compose_system(context)`; префикс для одного и того же набора модулей остаётся байт-в-байт равным.
- [x] **Step 4:** Run `pytest tests/test_prompting_modules.py tests/test_prompting_prefix.py tests/test_exploration_master.py` — PASS. `python -m tests.eval.run --n 5` — не хуже базового; сравнить `tokens_in`.
- [x] **Step 5:** Commit `feat(prompting): rule modules gated by the state of the turn`.

### Task 7: Блоки лора и отбор по смыслу реплики

**Files:**
- Create: `app/agents/master/prompting/lore.py`
- Test: `tests/test_prompting_lore.py`

**Interfaces:**
- Produces: `@dataclass(frozen=True) LoreBlock(id: str, title: str, summary: str, text: str)`; `split_lore(world: dict) -> list[LoreBlock]` — из `laws`, `powers`, `world`, `inhabitants`, `history` режет на абзацы-блоки (`id = "<поле>:<номер>"`, `title` — первые ~6 слов, `summary` — первое предложение до 120 символов); `stems(text: str) -> set[str]` — основы слов (нижний регистр, обрезка окончаний до 5 символов, слова короче 3 отбрасываются); `select_blocks(blocks: list[LoreBlock], query: str, budget: int) -> tuple[list[dict], list[LoreBlock]]` — указатель `[{"id","title","summary"}]` для всех блоков и полные блоки по пересечению основ с `query`, пока суммарная длина ≤ `budget`.

- [x] **Step 1: Test** (1) `test_split_makes_blocks_with_stable_ids`; (2) `test_stems_match_russian_forms` («дверь», «двери», «дверью» дают общую основу; «зал»/«залу»); (3) `test_relevant_block_is_selected_by_the_players_words`; (4) `test_budget_limits_full_blocks_and_keeps_the_whole_index`; (5) `test_empty_world_gives_no_blocks_and_no_error`.
- [x] **Step 2:** Run — FAIL.
- [x] **Step 3:** Implement.
- [x] **Step 4:** Run `pytest tests/test_prompting_lore.py` — PASS.
- [x] **Step 5:** Commit `feat(prompting): lore blocks and selection by the players words`.

### Task 8: Нарезчики контекста и `need_lore`

**Files:**
- Create: `app/agents/master/prompting/slicers.py`
- Modify: `app/agents/master/prompting/context.py` (`build_decide_context` вызывает `slice_context`), `app/rules/universal/exploration.py` (`IntentV2.need_lore`), `app/agents/master/exploration.py` (цикл попыток)
- Test: `tests/test_prompting_slicers.py`

**Interfaces:**
- Consumes: `LoreBlock`, `select_blocks`.
- Produces: `slice_context(context: dict, source: str, extra_blocks: list[str] = ()) -> dict` — меняет: `world_rules` → `{"lore_index": [...], "lore": [полные блоки]}` (через `select_blocks`, бюджет 1500 символов плюс `extra_blocks`); `objects` — присутствующие и инвентарь с описанием до первой строки, полные для названных в `source`; `established_evidence` — абзацы с пересечением основ с `source` и сущностями сцены; `hero` — компактная карточка (имя, характеристики, способности без описаний); `history` — последние 6 реплик, длинные укорочены до 400 символов. `scene`, `known_exits`, `source`, `active_effects`, `resources` — без изменений.
- Produces: `IntentV2.need_lore: list[str] = Field(default_factory=list, max_length=4)` — модель просит блоки лора по id из `lore_index`.
- Цикл попыток: если разобранный ответ содержит `need_lore` с известными id, сервер вызывает `slice_context(..., extra_blocks=ids)` и повторяет запрос в рамках тех же двух попыток (отдельной попытки не создаёт); неизвестные id игнорируются.

- [x] **Step 1: Test** (1) `test_slicing_keeps_the_present_whole` (сцена, выходы, source, эффекты равны исходным); (2) `test_objects_are_trimmed_except_the_named_ones`; (3) `test_lore_index_is_always_present_even_when_no_block_is_relevant`; (4) `test_need_lore_adds_the_requested_blocks_within_the_attempt_budget` (ScriptedLLM: первый ответ с `need_lore=["laws:1"]`, второй валидный; ровно два вызова модели, второй запрос содержит блок); (5) `test_unknown_lore_ids_are_ignored`; (6) `test_empty_world_slices_without_error`.
- [x] **Step 2:** Run — FAIL.
- [x] **Step 3:** Implement; в `ExplorationAction`/схеме `need_lore` не попадает (убирается `clean_model_intent`).
- [x] **Step 4:** Run `pytest tests/test_prompting_slicers.py tests/test_exploration_master.py tests/test_universal_world_exploration.py` — PASS. `python -m tests.eval.run --n 5` — не хуже базового; сравнить `tokens_in`.
- [x] **Step 5:** Commit `feat(prompting): context slicers, lore index and need_lore`.

### Task 9: Те же приёмы для проверки смысла и рассказчика

**Files:**
- Modify: `app/agents/master/exploration.py` (`REVIEW`, вход `intent_review`), `app/agents/master/universal_narration.py`, `app/agents/master/public_context.py`
- Test: `tests/test_prompting_review_narration.py`

**Interfaces:**
- Consumes: `slice_context`, `select_blocks`, модули (`compose_system`-аналог для рассказчика не нужен: его `SYSTEM` остаётся ядром).

- [x] **Step 1: Test** `test_review_gets_the_sliced_context` (вход `intent_review` содержит `lore_index`, не содержит полного `world_rules`); `test_narration_context_keeps_what_the_story_needs` (сцена, исходы, `scene_note`, последние реплики сохранены).
- [x] **Step 2:** Run — FAIL.
- [x] **Step 3:** Implement; удалить из входа дубли (`scene` дважды и т. п.).
- [x] **Step 4:** Run `pytest tests/test_prompting_review_narration.py tests/test_narration_integrity.py tests/test_exploration_master.py` — PASS. Eval: `python -m tests.eval.run --n 5` — не хуже базового.
- [x] **Step 5:** Commit `feat(prompting): slicing for review and narration`.

### Task 10: Итоговый замер и закрепление

**Files:**
- Modify: `tests/eval/baseline.json` (новый базовый замер), `docs/superpowers/specs/2026-10-30-prompt-architecture-design.md` (раздел «Итог»)
- Create: `docs/prompt-architecture.md` — как добавлять правило (модуль), как добавлять тип контекста (нарезчик), как пополнять набор реплик.

- [x] **Step 1:** `python -m tests.eval.run --n 5` на обоих мирах; записать в спецификацию: токены на ход до и после (по частям), долю успехов до и после.
- [x] **Step 2:** Полный прогон `pytest tests -q -n 4 --timeout=60` — все тесты проходят (кроме падений параллельной работы над артом, которые назвать по имени).
- [x] **Step 3:** Написать `docs/prompt-architecture.md`; пересобрать образ, перезапустить контейнер; сыграть три хода вручную (переход, речь, предмет).
- [x] **Step 4:** Commit `docs: measured result and how to extend the prompt architecture`.
