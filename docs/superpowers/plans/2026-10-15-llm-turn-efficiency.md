# LLM Turn Efficiency Implementation Plan

> Пересмотр от 2026-10-16: [план исправления контекста](2026-10-16-master-context-revision.md)
> и [анализ вариантов](../specs/2026-10-16-master-context-revision-design.md).
> Этот документ сохраняет историю первого этапа. Пересмотр требует единого поведения
> без пользовательских флагов и отдельной проверки качества/экономии контекста.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Снизить расходы и задержку игрового хода без потери корректности правил,
полноты обработки свободных заявок, памяти и качества повествования.

**Architecture:** Поэтапно добавить измерения, исправить контракт ссылок на действия,
разделить промпты по ролям и выбирать стабильные профили инструментов. Завершать
decide по подтверждённому состоянию частей и обязательств, сохраняя общий маршрут
для сложных случаев и возможность отключения каждого изменения.

**Tech Stack:** Python >=3.11, FastAPI, SQLAlchemy, PostgreSQL/SQLite, Alembic,
LiteLLM, Jinja2, pytest; React/TypeScript/Vitest для состояния проверки героя.

**Spec:** `docs/superpowers/specs/2026-10-15-llm-turn-efficiency-design.md`.

Статус: реализация в main по разрешению пользователя; этапы 1–7 выполнены,
офлайн-часть этапа 8 выполнена. По последующему разрешению пользователя приложение
развёрнуто, начато ручное тестирование всех флагов; исправлены два выявленных дефекта.
Контролируемое парное сравнение и окончательное решение о включении остаются открыты.

## Global Constraints

- Python >=3.11; использовать существующий LiteLLM, не добавлять второго LLM-клиента.
- Серверные правила D&D, права доступа, транзакции и checkpoint сохраняются.
- Новые режимы под независимыми флагами `llm_optimization`, по умолчанию false.
- `tokens_cached=null` означает неизвестный кеш; не заменять неизвестное нулём.
- `tokens_in` — полный prompt total; reasoning нельзя повторно прибавлять к output cost.
- Диагностика не хранит ключи, полные промпты, скрытые рассуждения и thought signatures.
- 5–12 тыс. токенов decide и ≤2 тыс. voice_line — мягкие цели, не лимиты обрезания.
- Типовые простые действия: 0–2 decide; сложные заявки сохраняют общий маршрут.
- Не выполнять платные прогоны, не менять активные настройки и не перезапускать игру
  при выполнении офлайн-этапов. Для сравнения живых моделей нужен согласованный бюджет.
- После изменений кода выполнять `graphify update .`; неожиданные чужие изменения сохранять.

## Review Focus

1. Несколько частей одной заявки и два героя: нельзя считать ход законченным по одному `ctx.closed`.
2. Успешный поиск и критический провал: обязательное последствие должно попасть в мир до рассказа.
3. Выдуманный ref и пустой результат парсера: чтение сцены доступно, мутация не получает чужую заявку.
4. Неизвестный кеш, неизвестная цена и rollback: отчёт не приписывает бесплатность или экономию.
5. Смена сцены, скрытый факт, речь без action: расширение контекста не теряет сюжет и не публикует секрет.

Каждый пункт покрывается тестами в задачах ниже; ручная оценка прозы остаётся
отдельной проверкой, а не подменяется наличием scripted fixture.

## Карта файлов

Новые модули мастера: `prompt_context.py` (роль и блоки промпта),
`tool_profiles.py` (выбор набора), `decision_completion.py` (завершение),
`optimization.py` (валидация флагов). Не превращать `turn.py` в новый сборник логики.
Новая диагностика: `app/core/llm_diagnostics.py`, CLI `tools/llm_session_report.py`.
Новые шаблоны: `decide_system.j2`, `narrator_system.j2`, `voice_system.j2`,
`review_system.j2`; исходный `master_system.j2` остаётся для legacy.
Миграция после фактического Alembic head; номер выяснить при реализации.

## Порядок и границы поставки

1 → 2 → 3 → 4 → 5 → 6 → 7 → 8. Задачи 2, 4 и 5 особенно тесно связаны
контрактом заявок; их поведение проверять совместно. После каждого этапа можно
остановиться на работающем ПО и оценить полученный эффект.

### Task 1: Достоверная телеметрия и исходный отчёт

**Files:** Modify `app/agents/llm.py`, `app/agents/master/turn.py`,
`app/agents/master/parsing.py`, `app/db/models.py`, `app/core/spend.py`,
`app/agents/world_generator.py`, `app/agents/layout_model.py` и остальные места
переноса `LLMReply` в `LlmCall`, найденные через rg; Create migration,
`app/core/llm_diagnostics.py`, `tools/llm_session_report.py`;
Test `tests/test_llm_accounting.py`, `tests/test_llm_session_report.py`.

**Interfaces:** `cached_tokens_of(usage: Any) -> int | None` в llm.py;
`LLMReply.tokens_cached: int | None`, `LLMReply.cost_known: bool`;
`LlmCall.tokens_cached: int | None`, `cost_known: bool | None` (null для старых строк),
`diagnostics: dict | None`; `prompt_sizes(blocks: dict[str, str], tools: list) -> dict`
в llm_diagnostics.py. Диагностика различает actual usage и оценку размера блоков.

- [x] Написать failing-тесты: cached=80/total=100 даёт uncached=20; отсутствие cache
  metadata оставляет null; reasoning=25/output=40 не даёт output=65; streaming и
  non-streaming сохраняют одинаковые поля; ошибка расчёта цены оставляет
  `cost_known=false`; исторические строки имеют неизвестный статус цены.
- [x] Добавить fixture отчёта: 16 done + 1 failed, parse без turn_id, оплаченный
  invalid output и транзакционный rollback. Assert: failed не исчезает; mean decide
  для done и всех ходов разные; отсутствие цены/кеша видно в отчёте.
- [x] Запустить `.venv\Scripts\python.exe -m pytest tests/test_llm_accounting.py tests/test_llm_session_report.py -n 0 -q`;
  убедиться в FAIL по новым полям/поведению.
- [x] Реализовать интерфейсы, миграцию и перенос метрик во всех путях записи.
  CLI: `--campaign ID --output PATH`, JSON с `by_purpose`, `done_turns`,
  `failed_turns`, `unattributed_calls`, p50/p95 и coverage cache/cost. Доступ к
  базе через существующую конфигурацию, запросы в read-only транзакции.
  По умолчанию только метаданные; тексты сообщений и секреты не экспортировать.
- [x] Проверить миграцию upgrade/downgrade на SQLite fixture и отдельной временной
  PostgreSQL базе; не мигрировать работающую игру для теста. Перезапустить целевые тесты.
- [x] Снять исходный JSON текущей кампании до изменения поведения; сверить totals
  с $0.484081/144 (или явно записать новый cutoff при наличии новых вызовов).
- [x] Commit: `feat: measure cached usage and report turn efficiency`.

### Task 2: Настоящие ссылки на действия и ограниченное исправление

**Files:** Modify `app/agents/master/resolution.py`, `turn.py`, `action_binding.py`,
`app/tools/registry.py`; Create `app/agents/master/optimization.py`;
Test `tests/test_multipart_actions.py`, `tests/test_resolution_requests.py`,
`tests/test_decision_action_refs.py`.

**Interfaces:** `optimization_flags(settings: dict) -> dict[str, bool]` — whitelist
шести флагов из spec, default false; `action_context_prompt(ctx: ToolContext) -> str`
в resolution.py. Возвращает все реальные текущие refs, намерения, статусы и
зависимости независимо от adjudication admission; legacy `resolution_prompt` остаётся.
Метаданные `invalid_source_repairs` живут в диагностике хода, лимит 1.

- [x] Написать failing-тесты: обычная заявка без допуска к adjudicate всё равно
  содержит настоящий source_id; две части содержат разные part; пустой parse
  не создаёт выдуманный ref; чужая кампания, автор и несовместимая часть отвергаются.
- [x] Воспроизвести последний failed turn scripted-ответами: `source_id=current`,
  затем `msg_current`. Assert: только одна попытка исправления, дальнейшего цикла
  чтения/мутаций нет, техническая причина публично не выдаётся за успех.
- [x] Проверить read-only get_scene с лишним invalid ref: сцена читается в обычных
  границах доступа; тот же ref в `auto_success` отвергается. Две неоднозначные
  части не привязываются к первой автоматически.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/test_decision_action_refs.py tests/test_multipart_actions.py tests/test_resolution_requests.py -n 0 -q` → FAIL.
- [x] Реализовать под `action_refs`. Отдельно исправить безопасную терминализацию
  без выбрасывания ToolError на выдуманной ссылке; не ослаблять серверную проверку.
  Валидацию `llm_optimization` подключить к существующему обновлению настроек
  кампании; тест: неизвестное имя/не-bool отклоняется.
- [x] Те же тесты → PASS; добавить regression проверки rollback/replay из
  `tests/test_resolution_replay.py` и `tests/test_multipart_replay.py`.
- [x] Commit: `fix: expose action references and stop invalid source loops`.

### Task 3: Профили инструментов и стабильные схемы

**Files:** Create `app/agents/master/tool_profiles.py`;
Modify `app/agents/master/common.py`, `turn.py`, `app/tools/registry.py`;
Test `tests/test_decision_tool_profiles.py`, `tests/test_tools.py`.

**Interfaces:** `select_tool_profile(ctx: ToolContext, messages: list) -> str`;
`profile_tool_names(ctx: ToolContext, profile: str) -> list[str]`;
`tool_specs(world: World, names: list[str] | None = None, *, dynamic_ids: bool = True) -> list[dict]`.
`expand_decision_tools` — native read-only управляющий инструмент без мутаций мира;
всегда возвращает профиль general. Исполнение перехватывается оркестратором,
разрешённый список немедленно пересчитывается и проверяется для остатка пакета.

- [x] Написать failing-тесты выбора combat/exploration/social/general; смешанная
  и неразобранная заявка → general; неизвестный профиль → general. Узкий набор
  содержит чтение и расширение, не включает запрещённые настройки кампании.
- [x] Проверить расширение: general сохраняется до конца хода; расширение не
  добавляет host/internal tools; вызов до расширения отвергается, после допускается.
- [x] Проверить равенство JSON схем одного профиля при смене id сцены в compact
  режиме и различие динамического контекста; legacy dynamic_ids=true неизменён.
  Несуществующие id всё ещё отклоняются сервером.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/test_decision_tool_profiles.py tests/test_tools.py -n 0 -q` → FAIL.
- [x] Реализовать whitelist каждого профиля по реальному REGISTRY и покрыть все
  доступные инструменты хотя бы general. Канонически сортировать выдачу схем.
  Включение только через `tool_profiles`; не добавлять LLM-классификатор.
- [x] Те же тесты → PASS; сравнить размер схем legacy/профиль через prompt_sizes.
- [x] Commit: `feat: select stable decision tool profiles`.

### Task 4: Контекст по ролям с устойчивым префиксом

**Files:** Create `app/agents/master/prompt_context.py`, четыре system templates
из карты файлов; Modify `turn.py`, `finish.py`, `narration.py`, `recall.py`;
Test `tests/test_master_prompt_context.py`, `tests/test_narration_integrity.py`.

**Interfaces:** `PromptBundle` dataclass: `messages: list[dict]`,
`blocks: dict[str, str]`, `version: str`, `fallback_reason: str | None`;
`async build_prompt_bundle(ctx: ToolContext, cfg: AgentConfig, *, role: str,
inputs: dict) -> PromptBundle`. Функция чтения, не меняет мир и не вызывает LLM.
Legacy `_system_prompt` остаётся доступным при выключенном флаге/неполном контексте.

- [x] Написать failing-тесты: неизменный prefix при смене хода; обязательные refs,
  цели, ресурсы, текущие правила и последствия сохранены; контекст narrate не
  содержит инструкции выбрать tool_call; технические role rules не теряются.
- [x] Добавить случаи: разошедшийся отряд, смена локации, NPC с отношениями и
  сюжетной связью, скрытый факт, игрок без intent. Assert на видимость и сохранение
  фактов; переполнение мягкого бюджета включает fallback, не теряет активную часть.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/test_master_prompt_context.py tests/test_narration_integrity.py -n 0 -q` → FAIL.
- [x] Реализовать builder и подключить `role_context` к decide/narrate;
  review/voice переходят в следующих задачах. Динамические id вынести в контекст;
  размеры blocks писать через Task 1, оценки маркировать. Не переписывать memory
  subsystem и не вызывать дополнительное суммирование на каждом ходе.
- [x] Те же тесты → PASS; run `tests/test_resolution_visibility.py` и
  `tests/test_narrative_access.py`. Сохранить локальный отчёт размеров тестовых сцен.
- [x] Commit: `feat: build role specific master context`.

### Task 5: Доказуемое завершение цикла decide

**Files:** Create `app/agents/master/decision_completion.py`;
Modify `turn.py`, `action_progress.py` только при необходимости извлечения чистого
чтения статусов; Test `tests/test_decision_completion.py`, `tests/test_multipart_progress.py`.

**Interfaces:** `CompletionCheck` dataclass: `can_finish: bool`, `reasons: tuple[str, ...]`;
`check_decision_completion(ctx: ToolContext, *, trace_calls: list[dict],
required_actors: set[str], opening_actors: set[str], pending: dict[str, bool]) -> CompletionCheck`.
`pending` передаёт переход/spawn/реакцию/обязательный ответ мира/сюжет;
отсутствующий обязательный ключ означает невозможность раннего завершения.

- [x] Написать failing-тесты: завершённая сервером простая атака → 0 decide;
  один успешный native tool batch → 1 decide без «готово»; две части одного героя
  требуют обеих; чужой герой не закрывает заявку; чистая речь получает decide.
- [x] Проверить запреты завершения: успешный поиск без находки, крит без последствия,
  переход со сбоем, обязательный spawn repair, реакция, ready world response,
  незавершённый сюжетный эффект, неизвестный pending. Обычный игровой промах
  терминален и не перебрасывается. Legacy без частей завершается консервативно.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/test_decision_completion.py tests/test_multipart_progress.py -n 0 -q` → FAIL.
- [x] Реализовать read-only check под `early_finish`, вызывать после маршрута и
  полного batch, до следующего LLM-запроса. Сохранить дальнейшее выполнение
  NPC/часов/checkpoint; ожидание подготовки оставить finish/settle. В trace
  писать причину завершения/продолжения. Не снижать MAX_STEPS глобально.
- [x] Те же тесты → PASS; run `tests/test_resolution_end_to_end.py`,
  `tests/test_multipart_replay.py`, `tests/test_narration_playtest.py`.
- [x] Commit: `perf: finish resolved turns without redundant decisions`.

### Task 6: Компактная голосовая реакция

**Files:** Modify `app/agents/master/narration.py`, `turn.py`, `prompt_context.py`,
`app/agents/prompts/voice_line.j2`; Test `tests/test_voice_emotion_context.py`,
`tests/test_tts.py`, `tests/test_master_prompt_context.py`.

**Interfaces:** `_ask(..., *, tool_choice: Any = None, max_tokens: int = 8192,
thinking: bool = True)` — новые keyword-only параметры после существующих;
forward в LLMClient. Voice использует max_tokens=512; остальные defaults сохранены.
Режим thinking менять только по проверенным возможностям фактической модели;
не отключать его по одной подстроке `flash`.

- [x] Написать failing-тесты: voice prompt включает нрав, стиль, настроение,
  новости и public results, исключает secrets/полную боевую инструкцию;
  прежние проверки чистки текста сохранены. Без канала LINE — 0 voice_line.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/test_voice_emotion_context.py tests/test_tts.py tests/test_master_prompt_context.py -n 0 -q` → FAIL.
- [x] Под `compact_voice` подключить bundle роли voice_line; не объединять его
  с narrate, сохранить параллельный запуск. Добавить проверяемую политику
  возможностей моделей для thinking; неизвестная модель сохраняет default.
- [x] Те же тесты → PASS; размер voice fixture ≤2 тыс. оценочных токенов при
  описанном методе подсчёта, фактический provider usage проверить в живом замере.
- [x] Commit: `perf: compact voice reaction context`.

### Task 7: Надёжная и компактная проверка героя

**Files:** Modify `app/agents/master/review.py`, `prompt_context.py`,
`app/api/characters.py`, `app/core/characters.py`,
`web/src/pages/CampaignHeroPage.tsx`, `web/src/cabinet/PlayersTab.tsx`;
Test `tests/test_master.py`, `tests/test_llm_tool_choice.py`,
Create `web/src/pages/CampaignHeroPage.test.tsx`.

**Interfaces:** Task 6 `_ask` поддерживает tool_choice. Для `compact_review`
максимум 2 model responses; tool_choice="required" с единственным review_character.
Состояние проверки публикуется `character.review_started`/reviewed/review_failed;
при GET восстанавливается из событий с учётом времени последней отправки героя.
Запуск во время активной сессии получает понятный Conflict, не ложное ожидание.

- [x] Написать failing-тесты: один правильный tool_call одобряет; неверные args
  исправляются один раз; два ответа без вызова завершаются конкретной ошибкой;
  отчёт различает ошибку формата и отказ исполнителя. Повторный click в ходе
  проверки не создаёт параллельную оплачиваемую задачу.
- [x] Тесты гонки: сессия стартует/человек одобряет, пока LLM отвечает — не обходить
  admission и не повторять выдачу снаряжения. После исключения running очищается;
  перезапуск приложения не оставляет вечное ожидание (событие начала без конца
  из старого процесса трактуется как прерванное, без автоматического платного retry).
- [x] UI-тест: retry убирает прежнюю ошибку, показывает новую попытку и затем
  итоговую ошибку/статус; reload восстанавливает итог. Ручной допуск сохраняется.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/test_master.py tests/test_characters.py tests/test_llm_tool_choice.py -n 0 -q`
  и `npm.cmd --prefix web test -- CampaignHeroPage.test.tsx` → FAIL новых кейсов.
- [x] Реализовать compact_review, диагностику результатов инструментов без
  полного текста ответа. События получают id попытки и время; хранить только
  необходимые поля, не полную историю героя. Обновить API types при изменении schema.
- [x] Те же тесты → PASS; `npm.cmd --prefix web run typecheck` → exit 0.
- [x] Commit: `fix: require character review decisions and show retry state`.

### Task 8: Проверка качества и измерение реальной экономии

**Files:** Create `tools/eval_turn_efficiency.py`,
`tests/fixtures/turn_efficiency.json`, `tests/test_turn_efficiency.py`;
добавить результаты в `docs/superpowers/reviews/2026-10-15-llm-turn-efficiency.md`.

**Interfaces:** CLI `--mode scripted --cases PATH --output PATH`;
live-запуск отдельно `--mode live --campaign ID --max-cost-usd N`, без default
бюджета. Live исполняется только в изолированной тестовой кампании, не повторяет
мутации в текущей игре. CLI не заявляет измеренный кеш/качество по scripted-данным.

- [x] Написать минимум 20 сценариев: атака, промах, крит, move+attack, заклинание
  и отказ ресурса, AoE, реакция, разговор, social check, поиск с находкой/без,
  контейнер и ожидание подготовки, подбор/передача, неизвестная цель,
  неразобранная свободная заявка, две части/два героя, неверный ref, rollback,
  скрытый факт/разделённый отряд и переход. На каждом проверять события мира,
  ресурсы, терминальные части, вызовы моделей и public narration constraints.
- [x] Написать failing-тесты runner: malformed case отклоняется; live без бюджета
  не стартует; исчерпание бюджета запрещает новые запросы, но сохраняет usage
  уже оплаченного ответа; отчёт содержит failed, fallback и unknown usage.
- [x] Run `.venv\Scripts\python.exe -m pytest tests/test_turn_efficiency.py -n 0 -q` → FAIL.
- [x] Реализовать runner с неизменным seed/миром и одинаковыми моделями/голосом
  для legacy и optimized. Использовать реальные существующие механические
  фикстуры; `tools/eval_narrative.py` не является готовым live-evaluator хода.
- [x] Те же тесты → PASS; выполнить scripted CLI. Это проверяет протокол и
  количество обращений, а не экономию денег и литературное качество живой модели.
- [ ] Запустить согласованный набор проверок `.venv\Scripts\python.exe -m pytest -n 4 -q`,
  затем `.venv\Scripts\python.exe -m ruff check app tests tools` и
  `npm.cmd --prefix web test`, `npm.cmd --prefix web run build`.
  Отделить известные ранее failures от регрессий; новые failures исправить.
- [x] Выполнить `graphify update .`, проверить diff. Согласовать денежный потолок
  live-сравнения перед вызовами моделей. При его отсутствии записать «live не
  проведён», не объявлять цели по расходам достигнутыми.
- [ ] В живом сравнении записать холодный/прогретый кеш, actual tokens, cost coverage,
  median/p95 длительности, долю ошибок и полноту заявок. Отдельно сравнить
  стоимость создания кампании и стоимость ходов. Проверить целевые ≥40% экономии,
  ≥25% снижения p50 и отсутствие ухудшения p95; добавить ручную парную оценку
  атмосферы, связности и инициативы мастера.
- [ ] Оформить решение о включении каждого флага и способ отката. Не включать
  все флаги сразу в действующей игре только на основании scripted PASS.
- [x] Commit: `test: validate turn efficiency and quality gates`.

## Что сознательно оставлено на следующий план

Оптимизация sketch/plan/layout по их конкретным ошибкам; explicit cache с расчётом
стоимости хранения; Batch API; сравнение новых моделей. По текущему замеру decide,
narrate и voice_line вместе дают около 90% учтённых затрат — начать с них и
контракта исполнения действий. Сроки и гарантированную экономию не назначать до
задачи 1 и парного live-сравнения.
