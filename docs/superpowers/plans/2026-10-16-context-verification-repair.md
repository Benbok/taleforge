# Context verification repair — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Устранить воспроизводимое зависание теста, исправить непроверенные границы production-контекста и получить достоверную офлайн-проверку полных ходов и сравнения вариантов.

**Architecture:** Отдельно проверять приём заявки, сбор фактов из БД, отбор/видимость, реальный вызов модели и сохранённый исход хода. Ожидания теста не становятся входными фактами. Evaluator явно выбирает сборщик при одинаковых механике, refs и политике завершения.

**Tech Stack:** Python, pytest/pytest-timeout/xdist, Starlette TestClient, SQLAlchemy, ScriptedLLM, существующий evaluator.

**Spec:** `docs/superpowers/specs/2026-10-16-master-context-revision-design.md`; уточняет незавершённые пункты `2026-10-16-master-context-integration-fixes.md`.

Статус: задачи 1–6 выполнены в текущей `main`; автоматическая приёмка зелёная. Проверенный code HEAD перед документальным handoff: `e400954`. Ручные и платные проверки остаются отдельным этапом.

Повторное ревью выявило незакрытые пункты реализации; они исправлены в рабочей
копии поверх `0c98050`. Актуальная приёмка: **1918 passed, 19 skipped** и
**36 сценариев сравнительного evaluator**, exit 0. Подробности и ограничения:
`docs/superpowers/reviews/2026-10-16-context-review-repair-verification.md`.
Ниже сохранены исходные задачи и исторические результаты предыдущей реализации.

## Результаты исследования

### 1. Timeout — потерянный терминальный ответ в тесте

Подтверждённая цепочка:

1. `tests/test_party_split.py::test_fight_is_only_where_the_foes_are` использует общий `client`, а не локальный `game_client` с ScriptedLLM.
2. `tests/conftest.py::client` создаёт приложение с настоящим LiteLLM-клиентом.
3. `app/gateway/ws.py::_send` вызывает parser и recovery **до** сохранения Message.
4. При повторном неуспехе recovery `_send` отправляет `message.rejected` и выходит до `publish_message`.
5. `tests/test_ws.py::next_of` пропускает все события другого типа. Ограничение в 20 событий не ограничивает время `receive_json()`.
6. Тест ждёт `message.new`, которого при отказе не будет. pytest-timeout убивает worker; это не доказательство deadlock приложения.

Диагностическая проба на текущем HEAD: только в памяти процесса `LiteLLMClient.complete` заменён на LLMError; локальный `next_of` завершает ожидание при отказе. Тот же тест за 7.26 с падает на строке 344 с `message.rejected`, reason «Не удалось разобрать действие. Уточните, что делает ваш герой.». Сеть для модели не использовалась. В setup дополнительно был лог SQLAlchemy CancelledError; его нельзя считать причиной полученного отказа.

Граница доказательства: воспроизведён путь parser failure → rejection → скрытый отказ. Первоначальная ошибка реального провайдера и её параметры этой пробой не установлены. Прежнее утверждение «старый нестабильный тест» не было обосновано.

### 2. Сценарии проверяют заранее подставленный ответ

`tests/context_scenarios.py::scenario_facts` объединяет `required_facts` и `expected_outcomes`, превращает их в ContextFact и затем проверяет наличие этих же строк. `initial_state` отсутствует; обрабатывается только `requests[0]`; инструменты и MasterService не исполняются. «attack» или «resume» в prompt не доказывают атаку или возобновление.

Forbidden-факты искусственно помечены субъектом `unrelated` и проверяются только в decide. Это проверка релевантности, а не публичной видимости. Private-факт может быть законно нужен decide и запрещён narrate — текущая схема этого не выражает.

Тесты `test_production_decide_request_selects_snapshot_facts` и `test_production_narrate_request_uses_audience_safe_snapshot` перехватывают реальный вызов, но подменяют `collect_context_snapshot`. Они доказывают подключение selector, но не корректность преобразования реального мира.

### 3. Evaluator не исполняет заявленный context experiment

В `tools/eval_turn_efficiency.py::main` параметры `--experiment` и `--context-variant` только валидируются и добавляются в готовый отчёт. `run_scripted` всегда запускает `legacy/optimized`; instrumentation переключает сразу все optimization.FLAGS, включая action_refs/tool_profiles/role_context. Это смешивает причины изменений. Live поддерживает только attack, не 12 сценариев.

Baseline в `execute_context_scenario` — искусственный system=`legacy` и список маркеров. Это не историческая сборка того же мира; её размер не является базой для экономии.

### 4. Реальный snapshot имеет дополнительные дефекты и риски

В `app/agents/master/context_snapshot.py`:

- FactState имеет `ref.key` и `depends_on`, а сборщик читает `item.key` с fallback `fact` и не переносит зависимости. Разные факты одного субъекта получают одинаковый ключ; selector строит `by_key`, поэтому адреса зависимостей неоднозначны. Не утверждать, что все дубликаты автоматически исчезают: итоговый фильтр сохраняет строки по выбранным ключам.
- Запрос narrative facts идёт по id сущностей/героев без template_id, хотя другие production-пути запрашивают оба. Риск потери каталожной мотивации/отношения требует теста с настоящим NarrativeView.
- Публичность target/place определяется видимостью объекта, затем в текст включается весь `state`. Видимость объекта не разрешает все его поля. Нужен тест с безопасным описанием и закрытым полем; утечка в живом ходе пока не измерялась.
- `_json` режет сериализацию по 1200/6000 символов, включая plot. Обязательное поле после границы может пропасть; JSON может стать невалидным.
- `current_place = focus or scene.location_id`: focus может остаться местом начала хода после move. `scene_places()` уже умеет учитывать актуальные позиции crew. Нужен resume-тест с разными старым focus и новым местом.
- Соседство routes выводится из `location_id == current_place`. Это вложенность, не доказательство доступного перехода. Источник маршрутов нужно брать из действующей модели карты/переходов.
- В decide одновременно остаётся полная `scene_table()` и добавляются структурированные факты. Полнота частично держится на старом блоке; реальное устранение повторов ещё не доказано. Удалять таблицу до покрытия чисел/ресурсов нельзя.

Следствие: прежний статус «задачи 1–5 выполнены» означает наличие кода, но не доказанную приёмку всех требований. Одного зелёного pytest после исправления helper недостаточно.

## Global Constraints

- Работать в текущей main, сохранять чужие изменения и `.tmp_exec_probe`; коммитить явный перечень файлов.
- Только офлайн, изолированная тестовая БД. Не перезапускать приложение и не менять текущую кампанию.
- Настоящие LLM-запросы запрещены в этих тестах. Платный запуск требует отдельного бюджета и остаётся за границей плана.
- `EARLY_FINISH_ENABLED = False`; не менять модель, длину ответа, права, refs и правила механики ради экономии.
- Не скрывать failure через skip/xfail, повышенный timeout или ослабление assertions.
- Unknown usage/cost остаются unknown; estimated tokens не считать USD/provider usage.
- После изменения кода выполнить `graphify update .` и проверить завершение процесса, а не только строку AST extraction.

## Review Focus

1. Отказ parser/recovery до Message: явный ответ и ноль игровых мутаций — задача 1.
2. Два факта одного NPC, template facts и неизвестная зависимость — задача 2.
3. Видимый NPC с приватным state, индивидуальные знания общей аудитории, move/resume — задача 3.
4. Составная заявка/два героя/повтор checkpoint: реальные refs, порядок, отсутствие двойного эффекта — задача 4.
5. Вариант сравнения меняет только заявленный фактор; неполный/упавший прогон не считается успехом — задачи 5–6.

## Task 1: Детерминированный приём заявки и ожидание WebSocket

**Files:** Modify `tests/test_party_split.py`, `tests/test_ws.py`; Create `tests/test_ws_waiting.py`; extend `tests/test_intent_recovery.py`. Production `app/gateway/ws.py` менять только при воспроизведённом нарушении контракта.

**Interfaces:** добавить специализированный `wait_message_result(ws, *, client_id: str, timeout_s: float = 10.0) -> dict`, возвращающий соответствующий `message.new` или `message.rejected`. Deadline охватывает сам await receive через TestClient portal/AnyIO cancel scope, а не только число событий. Общий `next_of` не менять глобально без аудита тестов, ожидающих отказ.

- [ ] Добавить тесты rejection, успешной публикации, отсутствия событий и постороннего broadcast: helper возвращает правильный результат или ограниченный TimeoutError с типами уже полученных событий, без токенов/prompt.
- [ ] В split-party тесте явно использовать ScriptedLLM, валидный parser intent и сценарий завершения narration. Сохранить проверки свободной группы, инициативы другой группы, цели гоблина и запрета отдыха в бою.
- [ ] Отдельно покрыть gateway parser-error → recovery-error: ровно две попытки parse, rejection с client_id, отсутствие принятого action/нового turn/изменения мира. Успешный recovery должен сохранить Message и refs именно его владельца.
- [ ] Заблокировать вызов настоящего provider adapter в этих fixtures; failure должен быть явным до сети. Не подменять parse_intent в тесте recovery.
- [ ] Запустить `.venv\Scripts\python.exe -m pytest tests/test_ws_waiting.py tests/test_party_split.py tests/test_intent_recovery.py -n 0 -q`; затем те же тесты `-n 4`. Expected: PASS, ни worker crash, ни пропущенных проверок.
- [ ] Коммит `test: make split-party admission deterministic and rejection-aware`.

## Task 2: Адреса и зависимости настоящих фактов

**Files:** Modify `app/agents/master/context_snapshot.py`, `app/agents/master/context_selection.py`; Create `tests/test_context_snapshot_contract.py`.

**Interfaces:** `fact_key(ref: FactRef) -> str` — детерминированная сериализация campaign/namespace/subject/key/version/snapshot_ref; одна функция для ключа и ссылок depends_on. `collect_context_snapshot` сохраняет внешний контракт.

- [ ] Создать мир с двумя FactState одного NPC, разными ключами/версиями, фактом template_id, обязательством и зависимостью на удалённый ресурс. Assert уникальность ключей, сохранение semantic identity и замыкание выбранной зависимости.
- [ ] Воспроизвести failures на текущем коде; отдельно unknown dependency должен дать reason и сохранить нужный раздел.
- [ ] Читать `ref.key`, `depends_on`, запрашивать instance/template facts и дедуплицировать по полной идентичности. Использовать существующие правила override NarrativeView, не вводить собственный приоритет каталога.
- [ ] Убрать произвольное обрезание обязательных структурных значений. Тест: обязательное поле после 1200/6000 символов доходит до модели; превышение размера отражается в diagnostics.
- [ ] Запустить `.venv\Scripts\python.exe -m pytest tests/test_context_snapshot_contract.py tests/test_master_context_selection.py tests/test_context_runtime_integration.py -n 0 -q` — PASS.
- [ ] Коммит `fix: preserve narrative fact identities and dependencies`.

## Task 3: Публичные поля и актуальное место после перехода

**Files:** Modify `app/agents/master/context_snapshot.py`, `app/agents/master/finish.py`, `app/agents/master/prompt_context.py`; extend `tests/test_narration_context_packet.py`, `tests/test_context_runtime_integration.py`, `tests/test_layout_turn.py`.

**Interfaces:** snapshot возвращает отдельно master-факты и явно разрешённую публичную проекцию; narrate/voice выбирают проекцию по всей аудитории. Использовать существующие `visible_scene`, `scene_payload` и NarrativeView; сырые state не делать публичными. Места брать из актуальных позиций crew/viewers, поддержать несколько мест.

- [ ] Добавить тесты реальной БД без monkeypatch snapshot: видимый NPC с публичным описанием и private-state marker; индивидуальный факт известен одному из двух слушателей; публичная связь и старое обещание должны сохраниться.
- [ ] Перехватить все narrate/voice messages: запретных полей нет, разрешённые есть. Decide вправе получать закрытую мотивацию. Проверить обе стадии раздельно.
- [ ] Покрыть move/checkpoint/resume при старом focus: новые место/пути присутствуют, прежняя сцена не выдаётся за текущую; исполненный эффект не повторяется.
- [ ] Покрыть связанный проход и вложенную, но недоступную локацию. Использовать реальные маршруты карты/переходов, не родительство как критерий достижимости.
- [ ] Реализовать минимальную публичную проекцию и актуализацию subjects; не удалять полезные факты целиком из-за наличия секретных полей.
- [ ] Запустить `.venv\Scripts\python.exe -m pytest tests/test_narration_context_packet.py tests/test_resolution_visibility.py tests/test_layout_turn.py tests/test_voice_emotion_context.py tests/test_context_runtime_integration.py -n 0 -q` — PASS.
- [ ] Коммит `fix: project audience-safe facts from current world state`.

## Task 4: Исполняемые сценарии с независимыми ожиданиями

**Files:** Rewrite `tests/context_scenarios.py`; Modify `tests/fixtures/context_quality.json`, `tests/test_context_quality.py`; Create `tests/context_scenario_worlds.py`, `tests/context_scenario_assertions.py`.

**Interfaces:** manifest v2: `id`, `fixture`, `requests[]` (actor/text), `parser_script`, `model_script`, `dice`, `required_facts_by_role`, `forbidden_facts_by_role`, `expected_world`, `rubric`. Registry `build_scenario(case_id, client, settings) -> ScenarioWorld` содержит campaign_id, actors, entity aliases. `run_scenario(case, world, client, llm) -> ScenarioResult` возвращает перехваченные вызовы, события и сохранённый итог. `assert_scenario(case, result) -> None` только читает результат, не создаёт входные данные.

- [ ] Сначала тест на независимость oracle: испортить expected_world/обязательный факт/видимость — тест обязан упасть. Запретить импорт expected_outcomes в построение world/model inputs.
- [ ] Все requests провести через gateway и MasterService; сообщения и refs брать из БД. Scripted ответы содержат команды модели, а assertions проверяют реальные Event, Message, ActionProgress и состояние мира.
- [ ] Перенести существующие selector-marker проверки в явно названные unit tests; они больше не считаются end-to-end сценариями.
- [ ] Реализовать следующую матрицу, переиспользуя существующие fixtures mechanics/narrative/resume:

| Scenario | Проверяемый результат |
|---|---|
| speech_npc | речь без механической команды обработана, произвольных эффектов нет |
| old_promise | обещание из сохранённой памяти присутствует после длинной истории; свежие данные не заменены сводкой |
| hidden_search | успешный поиск меняет knowledge; до раскрытия секрет отсутствует в публичном пакете |
| combat_effect | активный эффект влияет на реальное разрешение атаки, HP/ресурс сверены |
| multipart | все части имеют настоящие refs, исполнены в порядке по одному разу |
| two_heroes | оба владельца обработаны, чужая ссылка отвергнута |
| split_party | исход и сообщения ограничены своей группой, чужих секретов нет |
| transition | реальный переход и последующий snapshot нового места |
| resume | продолжение сохранённого checkpoint без повторения мутаций |
| unknown_parser | empty/error/timeout и success/failure recovery: уточнение или корректный binding |
| world_reaction | активное обязательство даёт подтверждённое событие/изменение состояния |
| npc_motive | приватный мотив в decide, публичное проявление/отношение в narrate, без утечки |

- [ ] Длинную кампанию включить как вариант old_promise; missing dependency как вариант world_reaction; общий рассказ двум группам как вариант split_party. Число 12 — покрытие семейств, не запрет дополнительных тестов.
- [ ] Запустить `.venv\Scripts\python.exe -m pytest tests/test_context_quality.py -n 0 -q` — все семейства действительно исполнены, никакого skip. Коммит `test: validate context scenarios through complete game turns`.

## Task 5: Реальные варианты evaluator и отдельные факторы

**Files:** Modify `tools/eval_turn_efficiency.py`, `tests/test_turn_efficiency.py`; Create `tools/context_eval_variants.py`, `tests/test_context_eval_variants.py`.

**Interfaces:** `ExperimentConfig(kind: Literal['context','tools','product'], variants: tuple[str, ...])`; `run_scripted(..., experiment: ExperimentConfig) -> dict`. Для context варианты legacy/v1/revised; для tools одинаковый revised с full/profile tools. CLI сохранить старый product default, добавить tools; context-variant реально выбирает единственный вариант либо `all` для сравнения.

- [ ] Failing test: смена CLI variant меняет реально перехваченный пакет, а не только report label. Effective config передаётся child process и возвращается им в отчёте; несовпадение блокирует отчёт.
- [ ] Создать изолированные исторические adapters на зафиксированном исходном commit `dbfdc65...`: legacy — прежний склеенный пакет, v1 — прежний role-context путь с fallback, revised — текущий production assembler. Артефакты исходных templates/логики хранить в evaluator с provenance; не переключать checkout и не выполнять исторический master pipeline.
- [ ] Для context сохранить одинаковые actions/refs, tools, модель, generation settings и завершение. Не использовать `dict.fromkeys(FLAGS, variant == 'optimized')` для context experiment. Product оставить отдельно и явно документировать его различия.
- [ ] Два уровня: одинаковые зафиксированные входы assembler/replay; затем отдельные полные ходы из одинакового начального мира. Нормализовать случайные id только при сравнении результатов, не переписывать отправляемые реальные refs.
- [ ] Учитывать bytes/estimated tokens по фактическим messages/tools каждого вызова, parse/recovery/narrate/voice/emotion/summary и retries; фиксировать settings, commit, fixture hash, seed, call count, provider/cache knownness.
- [ ] Missing scenario/пустой result/child crash/неизвестный вариант → nonzero exit, не пустой успешный отчёт. Все ошибки входят в расходы, успешные полные ходы считаются отдельно.
- [ ] Запустить `.venv\Scripts\python.exe -m pytest tests/test_context_eval_variants.py tests/test_turn_efficiency.py -n 0 -q` — PASS; выполнить scripted context comparison всех 12 семейств. Live пока остаётся отключённым для неподдерживаемых сценариев.
- [ ] Коммит `fix: execute isolated context evaluation variants`.

## Task 6: Проверить дублирование и закрыть приёмку

**Files:** Modify `app/agents/master/turn.py`, `app/agents/master/prompt_context.py` только после результатов задач 2–5; extend `tests/test_context_runtime_integration.py`; update оба прежних плана и verification report.

- [ ] На перехваченных пакетах составить соответствие scene_table ↔ selected facts по смысловым полям: числа, эффекты, ресурсы, id, заявки, маршруты. Не считать одинаковые слова ошибкой; проверять повторную сериализацию одной и той же записи.
- [ ] Если snapshot покрывает раздел полностью, сделать его единственным источником сериализации; иначе сохранить раздел и честно записать отсутствие сокращения. Memory/history остаются обязательными без обрезания.
- [ ] Проверить всю матрицу после изменения сборки. Не использовать уменьшение размера как замену полноте/видимости.
- [ ] Выполнить полный `.venv\Scripts\python.exe -m pytest -n 4 -q`, ruff изменённых Python-файлов, `git diff --check`, `graphify update .`; сохранить terminal exit codes и summary. Прерванный запуск не PASS.
- [ ] Исправить статусы документов: предыдущие 90 passed проверяли часть покрытия; старый полный результат был до последних фиксов. Указать фактический новый HEAD и ограничения.
- [ ] Передать ручные сценарии текущей и новой кампании только после зелёной автоматической приёмки. Платные 12 × 3 × 3 и слепая оценка прозы остаются отдельным этапом с согласованным бюджетом.
- [ ] Коммит `docs: verify complete context repair and manual handoff`.

## Критерий завершения

Готовность подтверждается одновременно: bounded WebSocket tests; реальные DB-backed facts и audience checks; все семейства полных ходов с независимыми oracle; исполняемые варианты evaluator с одинаковыми механическими политиками; зелёный полный suite. Цели −40% входа/стоимости и −25% задержки не объявляются достигнутыми по scripted данным. Quarantine timeout и cosmetic report labels не закрывают этот план.

## Финальная проверка 2026-10-16

- Tasks 1–5 закрыты коммитами `421204a`, `1bf0cba`, `81bc155`, `87e02bc`, `e400954`; Task 6 закрывается итоговым документальным коммитом после этой проверки.
- На реальном decide-пакете selected facts проверены на однократную сериализацию; `scene_table` сохранён, потому что snapshot не заменяет полностью его числовые, механические, инвентарные и sketch-поля. `history` сохранён обязательным блоком; память не обрезается при наличии.
- Целевая матрица: `65 passed, 1 warning`. Полный suite: `1893 passed, 5 skipped, 35 warnings`, exit code `0`.
- Ограничения прежние: не запускались live/paid модели, ручные сценарии кампаний и слепая оценка прозы; цели экономии не заявляются достигнутыми.
