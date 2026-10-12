# Master Narrative Adaptation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Сделать мастера соавтором, который сохраняет и развивает решения игроков,
может перестроить основной сюжет и использует проверяемые основания без подмены
канона, игровых исходов и выбора героев.

**Architecture:** В модульном монолите появляется изолированное ядро narrative,
два источника предложений и общий путь проверки и применения. Локальная адаптация
использует текущую фазу решений; режиссёр работает с устойчивыми заданиями вне
длинных транзакций. Числа и игровые действия остаются в существующих инструментах,
публикация — после commit, чтение адаптированного материала — через единое представление.

**Tech Stack:** Python >=3.11 (CI: 3.12), Pydantic 2, SQLAlchemy AsyncSession,
Alembic, SQLite/PostgreSQL, pytest/xdist, Jinja2, существующий LLM Protocol.
Новые production-зависимости, отдельный сервис и новая очередь не требуются.

**Spec:** [Адаптация истории вслед за решениями игроков](../specs/2026-10-12-master-narrative-adaptation-design.md),
включая раздел 24 с первым игровым срезом и контрактом blueprint.
Связанный [спек локаций](../specs/2026-10-12-generative-location-maps-design.md)
используется только для used_fact_refs; SVG-генератор здесь не реализуется.

Статус: план для ревью. Задачи ещё не выполнены; команды ниже являются
будущими проверками, не отчётом об уже прошедших тестах.

## Global Constraints

- «Причина оправдывает авторское продолжение; она не доказывает его неизбежность».
- «Отсутствие загруженных данных не даёт творческой свободы».
- «Предложение модели не является принятым изменением».
- «Рассказчик и режиссёр не выбирают действие за героя и не переигрывают бросок».
- «Нераскрытый факт может быть committed. Одна отметка revealed=false не разрешает его переписать».
- «Все сохраняемые DTO имеют schema_version=1, запрещают неизвестные поля и используют закрытые enum».
- Домен app/core/narrative не импортирует app.db, app.tools, app.agents, SQLAlchemy,
  FastAPI и конкретного LLM-провайдера; входы и выходы — сериализуемые DTO.
- «Локальная адаптация не делает самостоятельный внешний commit».
- «Фоновая запись мира между effects_committed и завершением повествования
  откладывается для всей кампании в первом выпуске».
- Короткая запись использует Campaign.world_revision и world_tx; await LLM
  не удерживает транзакцию и campaign lock.
- Новые сущности создаются инструментами; новый сюжет не создаёт статистику,
  проход, предмет, укрытие или действие героя свободным текстом.
- Принятые переопределения сохраняются при переключении adaptive -> strict.
- Старые кампании и модули без валидированных разрешений остаются strict.
- Новый adaptive по умолчанию включается только после итоговой приёмки.
- Пределы: 8 операций, 8 grounds, новизна 3 на сцену / 12 на сессию,
  5 offered+active нитей группе, 2 LLM-вызова на задание, 1 новый снимок
  после конфликта, 16 зависимостей факта и 64 факта в обходе закрепления.
- Срез: 50 оснований, 80 фактов/участников/фронтов совокупно, 20 нитей,
  целевой вход 6000 токенов. Не поместившаяся обязательная зависимость
  исключает редактирование области или даёт context_incomplete.
- Задание: максимум 6 claim-попыток; временные повторы через 5, 15, 60 секунд.
  Deferred не запускает новый LLM-вызов и не расходует claim-лимит ожиданием.
- Встречи сохраняют существующий encounter_budget и действующие правила.
- Нет второго standing, полного event sourcing и обещания exactly-once WebSocket.

## Review Focus

1. Сохранённая реплика интереса ошибочно принята за выполненное соглашение:
   вопросы дают interest, но не доказательство союзного состояния — Tasks 2, 10, 11.
2. Два пути исполняют один standing-response или одну адаптацию: эффект,
   новизна и закрытие происходят один раз — Tasks 9, 16, 21.
3. Blueprint закрепил весь сюжет места вместо использованных пространственных
   фактов: геометрия защищена, независимый мотив сохраняет свободу — Tasks 5, 18.
4. Пока модель думает, начинается бой, раскрывается тайна или меняются
   разрешения: proposal не применяется по устаревшему основанию — Tasks 9, 14, 17.
5. Одна группа отвергла зацепку, другая не знает о ней: счётчики,
   карточки, narration, voice и summary не раскрывают чужой отказ — Tasks 6, 10, 20.

## Границы поставок

План реализует одну связанную функцию. Tasks 1–11 дают первый законченный
игровой срез; Tasks 12–15 добавляют устойчивого режиссёра; Tasks 16–19 расширяют
мир и адаптивные модули; Tasks 20–21 завершают настройки и общую приёмку.
У каждой поставки свой gate. Она не требует включать ещё недоступную часть.

| Gate | Проверяемый результат |
| --- | --- |
| A: Task 11 | Неожиданный союз меняет открытый основной сюжет и следующую сцену |
| B: Task 15 | То же продолжение подготовлено фоновым режиссёром, переживает рестарт |
| C: Task 19 | Адаптивный модуль, новый NPC и фронты используют единый принятый канон |
| D: Task 21 | Полная регрессия, качество, стоимость и включение режима |

До Gate A адаптация доступна только тестовым сценариям. Между A и D допустимо
явное preview-включение в процедурной кампании через проверенную настройку;
автоматическое изменение режима новых кампаний запрещено.

### Перед исполнением

- [ ] Прочитать спек и план; получить ревью плана и выбранный способ исполнения.
- [ ] Создать изолированный workspace/worktree по using-git-worktrees. В исходном
  дереве на момент планирования есть независимые изменения аудио и клиента.
- [ ] Проверить текущие alembic heads и git status. Базовый head при написании — 0020.
  Если head изменился, создать миграцию после актуального head и обновить
  ссылки плана до реализации; не создавать второй случайный Alembic head.
- [ ] В новом дереве установить существующие dev-зависимости и выполнить
  .venv/Scripts/python -m pytest -n 0 tests/test_resolution_policy.py
  tests/test_resolution_executor.py tests/test_plan.py tests/test_world_transactions.py -q.
  При исходном падении сначала определить его причину, не приписывать её адаптации.

В командах далее python означает Python виртуального окружения. На Windows
можно использовать .venv/Scripts/python.exe; команды записаны без shell-специфичных
цепочек. Миграции прогоняются только на отдельной тестовой БД.

## Карта файлов

Новые файлы создаются в задаче, которая даёт проверяемое поведение, без заранее
заполненного пустого scaffolding.

| Файлы | Назначение |
| --- | --- |
| app/core/narrative/contracts.py; ports.py | DTO и интерфейсы изоляции |
| app/core/narrative/policy.py; operations.py | Допуск и статический перечень операций |
| app/core/narrative/facts.py; threads.py | Закрепление и жизненный цикл |
| app/core/narrative/plan_patch.py; view.py | Адресное изменение и согласованное чтение |
| app/core/narrative/triggers.py; fronts.py | Основания подготовки и один источник прогресса |
| app/core/narrative/service.py | Workflow через порты, без ORM и конкретного LLM |
| app/db/narrative.py; app/db/narrative_jobs.py | Метаданные и отдельное хранение lease/заданий |
| app/tools/operation_group.py | Общая атомарная механика зарегистрированных вызовов |
| app/tools/narrative/context.py; sources.py | Проверенные снимки и стабильные источники |
| app/tools/narrative/compiler.py; executor.py; tools.py | Перевод операций и применение |
| app/tools/narrative/commitments.py | Связь закрепления с существующими инструментами и генерацией |
| app/tools/narrative/reader.py; runtime.py | Конкретные адаптеры портов и фоновое применение |
| app/agents/master/adaptation.py | Тонкое подключение к существующей фазе решений |
| app/agents/director.py; prompts/director.j2 | LLM-автор без права записи мира |
| tests/narrative_helpers.py | Детерминированные фабрики DTO и сценариев |
| tests/test_narrative_*.py | Проверки домена, адаптеров, гонок и поведения |
| tests/fixtures/narrative_quality.json; tools/eval_narrative.py | Небольшой оценочный набор и явный запуск |
| docs/master-narrative-adaptation.md | Использование, ограничения поставок и диагностика |

При реализации сериализуемые типы импортируются из core/narrative/contracts.py.
CompiledCall, GroupResult и адаптеры ToolContext остаются вне доменного ядра.
Новые модели размещаются в существующем app/db/models.py; разбиение всей ORM
на отдельные файлы не является условием этой функции.

## Общие имена и формы

Эта таблица определяет контракты для всех задач; название не выбирается заново
при переходе между поставками.

| Тип | Форма |
| --- | --- |
| NarrativePolicy | version, mode, разрешённые scope/operation kinds, точные пределы Global Constraints |
| NarrativeSource | campaign_id, scope: scene/future, source_kind: turn/work, source_id, stable_part >= 0 |
| EvidenceRef | campaign_id, kind: message/event/standing_response/time_interval, source_id |
| EvidenceRecord | ref, status, subject_refs, audience, game_time, применённый результат либо текст реплики |
| Ground | kind: consequence/relationship/interest/divergence/world_time, evidence_refs, subject_refs, confidence: explicit/inferred |
| FactRef | campaign_id, namespace: plan/module/campaign, subject_id, key, version, snapshot_ref |
| FactState | ref, kind: truth/testimony/intent, temporal_semantics, freedom, value, audience, depends_on |
| SnapshotRef | kind: package/plan/event, source_id, version при необходимости, typed_address |
| ReadRef | kind: fact/entity/front/thread/permission, id, version или стабильный digest |
| FrontRef | campaign_id, source_kind: antagonist/front, source_id |
| ThreadState | id, version, status, audience, subject_refs, plan_refs, parent_id, source_refs |
| VersionSet | world_revision, plan_version, narrative_revision, policy_version, operation_schema_version |
| SnapshotRequest | source, focus, audience, evidence_refs, mutable_subject_refs, feedback |
| NarrativeSnapshot | source, proposal_id, base: VersionSet, evidence, facts, actors, fronts, threads, read_set, permissions, budgets, content_chain, feedback, author_attempt |
| AdaptationProposal | schema_version=1, proposal_id, source, base, grounds, summary, operations, read_set |
| AdaptationAdmission | status: allowed/denied/deferred, reason_code, violations, read_set, novelty_cost |
| AdaptationResult | status, reason_code, event_ids, created_ids, versions, budgets_used, public_effects |
| WorkClaim | work_id, campaign_id, source, proposal_id, lease_token, lease_until, llm_calls, attempts, session_budget_ref |
| CompiledCall | tool, arguments, stable_key, local_bindings, visibility; не доступен модели |
| GroupResult | ok, raw_results, event_ids, bindings, failure, diagnostics |
| Violation | code: str, target_ref, expected, actual; только структурированные сведения |
| NarrativePermissions | anchors, mutable_fact_addresses, operation_kinds, supplement_scopes |
| LocalRef | actor_slot: str; принадлежит предыдущей операции текущего пакета |
| FutureSituationPatch | edits: tuple[FuturePlanEdit, ...]; точные edit kinds перечислены в Task 8 |
| FuturePlanEdit | kind, act_id, node_id при необходимости, значения разрешённых полей, проверенные ссылки |
| QuestionState | id, text, subject_refs, status: open/answered/obsolete, outcome |
| FrontView | ref, owner_ref, goal, resource_refs, progress, maximum, status, known_fact_refs, clock_at, period, milestones |

DTO неизменяемы: frozen Pydantic-модели, tuple для коллекций в домене, JSON-массивы
при сохранении. Operation является discriminated union закрытых моделей.
Свободный summary не расширяет разрешения.

Feedback — tuple[Violation, ...], по умолчанию пустой. Author_attempt=0 в
обычном снимке и получает номер уже зарезервированного вызова перед LLM.
Он служит учёту, не меняет source-key. DTO для всех заявленных видов операций
задаются в Task 1; последующие задачи реализуют их семантику и разрешение.

Во всех commit-шагах сначала выполнять git add только для файлов задачи,
сверять staged diff и затем указанный git commit. Не включать соседние изменения.

SnapshotRef всегда адресует реальную сохранённую версию. Текст сообщения является
EvidenceRecord, а не произвольным авторитетным FactState.

Сервер задаёт source/proposal_id/base. Автор возвращает grounds, summary и
operations; envelope с идентичностью собирает адаптер. Подмена полученных
server-owned полей при повторе отвергается.

---

### Task 1: Сериализуемые контракты и тестовые фабрики

**Files:** Create app/core/narrative/__init__.py, contracts.py, ports.py;
tests/narrative_helpers.py, tests/test_narrative_contracts.py.

**Interfaces:**
- Produces типы таблицы «Общие имена и формы».
- Produces NarrativeReader.snapshot(request: SnapshotRequest) -> NarrativeSnapshot,
  NarrativeAuthor.propose(snapshot: NarrativeSnapshot) -> AdaptationProposal,
  NarrativeApplier.apply(proposal: AdaptationProposal) -> AdaptationResult.
  Методы async; интерфейс NarrativeJobs добавляется Task 12.
- Фабрики tests/narrative_helpers.py: policy(**overrides) -> NarrativePolicy;
  snapshot(**overrides) -> NarrativeSnapshot; proposal(snap, *, operations=(),
  grounds=None, **overrides) -> AdaptationProposal; fact(**overrides) -> FactState;
  thread(**overrides) -> ThreadState; op(kind: str, **args) -> Operation.
  Defaults образуют разрешённый future-снимок процедурной кампании с одной
  подтверждённой divergence-причиной и одним существующим NPC.

- [ ] **Step 1 — tests.** Добавить roundtrip, неизвестное поле, неизвестный kind,
  изменяемость и отсутствие импортов инфраструктуры.
  ~~~python
  def test_proposal_roundtrip_without_actor_id():
      snap = snapshot()
      item = proposal(snap)
      assert AdaptationProposal.model_validate_json(item.model_dump_json()) == item
      assert "actor_id" not in item.source.model_dump()
      assert item.schema_version == 1
  ~~~
  AST-тест проверяет импорты доменного пакета, включая локальные relative imports.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_contracts.py -q.
  Ожидается ошибка отсутствующего нового модуля/контракта.
- [ ] **Step 3 — code.** Определить DTO, строковую форму source-key и порты с
  extra=forbid/frozen=True; не подключать SQL, LLM или регистрацию инструментов.
  В union уже объявить все операции спека, но не выдавать им runtime-разрешение
  до готовности соответствующей задачи.
- [ ] **Step 4 — green.** Повторить команду Step 2. Ожидается exit 0 и PASS;
  неизвестные поля, namespace и operation kind отвергаются.
- [ ] **Step 5 — commit.** git add только перечисленные файлы;
  git commit -m "feat(narrative): define isolated adaptation contracts".

### Task 2: Чистый допуск и расчёт бюджета

**Files:** Create app/core/narrative/policy.py, operations.py;
tests/test_narrative_policy.py.

**Interfaces:**
- Consumes DTO и фабрики Task 1.
- Produces admit_adaptation(snapshot: NarrativeSnapshot, proposal: AdaptationProposal,
  policy: NarrativePolicy) -> AdaptationAdmission.
- Produces operation_specs() -> tuple[OperationSpec, ...] и
  novelty_cost(operations: tuple[Operation, ...], existing_slots: frozenset[str]) -> int.
  OperationSpec содержит kind, version, scopes, ground_kinds, keys, cost.
- Для Gate A активны add_campaign_fact, develop_actor_role, revise_future_situation,
  change_front_intent для существующего antagonist, upsert_thread,
  transition_thread, reveal_fact. Остальные дают operation_not_available.

- [ ] **Step 1 — tests.** Покрыть все виды grounds, посторонний источник,
  реплику вместо исхода, явный/выведенный интерес, неизвестные данные, бой,
  group audience и комбинации операций.
  ~~~python
  def test_question_cannot_authorize_completed_alliance():
      snap = snapshot(evidence_status="question", ground_kind="relationship")
      decision = admit_adaptation(snap, proposal(snap), policy())
      assert decision.status == "denied"
      assert decision.reason_code == "source_not_applied"
  ~~~
  Точные пределы: 8/9 операций, 3/4 новизны в сцене, 12/13 в сессии;
  новая нить при 5 offered+active даёт attention_limit.
  Inferred interest требует два разных источника; один explicit inspection допустим.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_policy.py -q.
  Ожидается FAIL на отсутствующей политике.
- [ ] **Step 3 — code.** Реализовать проверку в порядке spec §10.1.
  Ссылки проверяются по верифицированному снимку, не по summary.
  Учитывать aggregate-cost пакета и одноразовый actor_slot; result существующих
  бросков неизменяем. Future + incomplete narration получает deferred.
- [ ] **Step 4 — green.** python -m pytest -n 0 tests/test_narrative_contracts.py
  tests/test_narrative_policy.py tests/test_resolution_policy.py -q.
  Ожидается exit 0; действующий admit не получает новый маршрут.
- [ ] **Step 5 — commit.** git commit -m "feat(narrative): validate grounded adaptation and budgets".

### Task 3: Метаданные в БД и общий world guard

**Files:** Modify app/db/models.py, app/core/world_tx.py;
Create alembic/versions/0021_narrative_foundation.py, app/db/narrative.py,
tests/test_narrative_storage.py, tests/test_narrative_migrations.py.

**Interfaces:**
- Produces NarrativeState, NarrativeFact, NarrativeThread.
  Fields соответствуют spec §15.1; NarrativeWork добавляется отдельно Task 12.
- Produces async ensure_state(session, campaign_id: str) -> NarrativeState;
  async load_subject_facts(session, campaign_id: str, subject_ids: tuple[str, ...],
  *, limit: int=80) -> tuple[FactState, ...].
- Produces async initialize_plan_metadata(session, campaign_id: str, plan: dict,
  *, mode: str) -> None. Исторические секреты legacy защищены, а допустимые
  текущие намерения и открытые ситуации описаны явно.

- [ ] **Step 1 — tests.** Реальная БД: unique key факта, foreign keys,
  audience, смена plan-state в одной транзакции, once-per-transaction revision,
  rollback savepoint, upgrade/downgrade отдельной БД.
  ~~~python
  def test_metadata_write_participates_in_world_guard(settings, client, admin):
      before, after, rolled_back = metadata_guard_scenario(settings, client, admin)
      assert after == before + 1
      assert rolled_back == after
  ~~~
  metadata_guard_scenario определяется в tests/test_narrative_storage.py:
  две async-сессии через существующий tests.game.run и make_sessionmaker.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_storage.py
  tests/test_narrative_migrations.py -q. Ожидается отсутствие таблиц/guard.
- [ ] **Step 3 — code.** Добавить индексы и ограничения спека; JSON используется
  только для ограниченных полей, не растущего журнала. Новые игровые метаданные
  добавить в world_tx._BY_CAMPAIGN. Данные не появляются у всех кампаний
  автоматически; initialize_plan_metadata вызывается при явном preview-включении.
  Номер миграции сверить по правилу перед исполнением.
- [ ] **Step 4 — green.** Команда Step 2 и python -m pytest -n 0
  tests/test_world_transactions.py -q. На отдельной БД: alembic upgrade head,
  alembic check, alembic downgrade 0020. Ожидается exit 0.
  Повторить интеграционные тесты с TEST_DATABASE_URL тестового PostgreSQL.
- [ ] **Step 5 — commit.** git commit -m "feat(narrative): persist facts threads and guarded metadata".

### Task 4: Единое представление и проверенный снимок

**Files:** Create app/core/narrative/view.py, app/tools/narrative/__init__.py,
context.py, reader.py; Modify app/core/world.py, app/core/plot.py;
Create tests/test_narrative_view.py, tests/test_narrative_context.py.

**Interfaces:**
- Produces compose_view(plan: dict, facts: tuple[FactState, ...],
  content_chain: tuple) -> CampaignNarrativeView, чистая функция.
- Produces async load_snapshot(ctx: ToolContext, request: SnapshotRequest,
  *, policy: NarrativePolicy) -> NarrativeSnapshot.
- Produces DbNarrativeReader, реализация NarrativeReader с maker и
  policy-provider; snapshot не сохраняет lease и не меняет мир.
- CampaignNarrativeView.resolve(ref: FactRef) -> FactState;
  plan_data() -> dict; permitted_subjects() -> tuple[str, ...].

- [ ] **Step 1 — tests.** План, текущая Entity и KnownFact имеют разные роли:
  опубликованный слух не заменяет truth; namespaces не дублируют значение.
  Чужая кампания/группа не входит в снимок; ошибка загрузки не открывает область.
  ~~~python
  def test_plan_value_is_read_from_plan_not_stale_metadata():
      view = compose_view(plan_with_goal("перемирие"), plan_fact_metadata(), ())
      assert view.resolve(goal_ref()).value == "перемирие"
  ~~~
  Три вспомогательные фабрики этого теста определить в test_narrative_view.py
  на основе tests/test_plan.py: good_plan и fact из Task 1.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_view.py
  tests/test_narrative_context.py -q. Ожидается отсутствующее представление.
- [ ] **Step 3 — code.** Добавить в World необязательную narrative-view,
  загрузить только нужные subjects. Domain compose не читает каталог самостоятельно.
  Context проверяет applied-события, Message kind/seat, crew, цепочку контента,
  версии и фактически использованный read_set.
  До Task 17 неизвестные module-переопределения не поддерживаются.
- [ ] **Step 4 — green.** Команда Step 2 и python -m pytest -n 0
  tests/test_plan.py tests/test_master_creative.py -q. Ожидается exit 0;
  strict не получает другой мир.
- [ ] **Step 5 — commit.** git commit -m "feat(narrative): build bounded verified campaign snapshots".

### Task 5: Закрепление фактов и минимальный контракт генераторов

**Files:** Create app/core/narrative/facts.py, app/tools/narrative/commitments.py,
tests/test_narrative_facts.py, tests/test_narrative_commitments.py;
Modify app/tools/master/knowledge.py, app/tools/plot.py, app/core/plot_anchors.py,
app/core/world_generation/contracts.py, storage.py,
app/agents/master/finish.py, checkpoint.py.

**Interfaces:**
- Produces seal_facts(facts: tuple[FactState, ...], used_refs: tuple[FactRef, ...],
  *, max_dependencies: int=16, max_visited: int=64) -> SealResult.
  SealResult: refs, violations; при нарушении список изменений пуст.
- Produces async record_commitments(ctx: ToolContext, refs: tuple[FactRef, ...],
  *, reason: str, snapshot_ref: SnapshotRef) -> tuple[FactRef, ...].
- Produces async reserve_narration_claims(maker, campaign_id: str, turn_id: str,
  refs: tuple[FactRef, ...], audience: tuple[str, ...]) -> tuple[FactRef, ...].
- Носители и reservation получают optional used_fact_refs с совместимым
  чтением пустого legacy-поля. Не создавать новый spatial blueprint.

- [ ] **Step 1 — tests.** Historical/current_state/draft_only, циклы, 16/17
  зависимостей, 64/65 посещённых фактов, скрытая созданная улика,
  независимый мотив NPC и резерв до narration.
  ~~~python
  def test_spatial_producer_seals_only_used_fact_and_dependencies():
      facts, room_ref, motive_ref = spatial_fact_fixture()
      result = seal_facts(facts, (room_ref,))
      assert room_ref in result.refs
      assert motive_ref not in result.refs
      assert result.violations == ()
  ~~~
  spatial_fact_fixture определяется в test_narrative_facts.py через fact;
  fake blueprint producer использует record_commitments без зависимости от SVG.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_facts.py
  tests/test_narrative_commitments.py -q. Ожидается отсутствие закрепления.
- [ ] **Step 3 — code.** Сохранять refs и before/after в скрытом Event.
  Plan-значение имеет snapshot в CampaignPlan/Event, module — пакет или Event.
  До LLM narration резервировать только допускаемые публичные утверждения;
  сбой не раскрывает Knowledge, уже committed-refs не создают лишний Event.
  Старые знания и генераторы без точной связи защищают затронутую область
  консервативно. Прямые plot_reveal/learn_fact и materialize тоже закрепляют.
- [ ] **Step 4 — green.** Step 2 и python -m pytest -n 0
  tests/test_plot_anchors.py tests/test_world_generation.py
  tests/test_world_transactions.py -q. Ожидается exit 0 и неизменность
  checkpoint effects_committed после ошибки описания.
- [ ] **Step 5 — commit.** git commit -m "feat(narrative): seal used facts before materialization and narration".

### Task 6: Жизненный цикл нитей и бюджет внимания

**Files:** Create app/core/narrative/threads.py, tests/test_narrative_threads.py;
Modify app/db/narrative.py.

**Interfaces:**
- Produces transition_thread(state: ThreadState, target: str,
  ground: Ground) -> ThreadTransition; результат содержит new_state/violation.
- Produces attention_count(threads: tuple[ThreadState, ...],
  audience: tuple[str, ...]) -> int.
- Produces async load_threads(session, campaign_id: str, *,
  statuses: tuple[str, ...], audience: tuple[str, ...], limit: int=20)
  -> tuple[ThreadState, ...].

- [ ] **Step 1 — tests.** Все переходы spec §14, отсутствие принятия по тексту
  просьбы, возврат abandoned как offered, дочерняя нить после resolved,
  приватный отказ и наложение audience.
  ~~~python
  def test_offered_does_not_become_active_without_player_choice():
      result = transition_thread(thread(status="offered"), "active",
                                 interest_ground())
      assert result.violation == "player_choice_required"
  ~~~
  interest_ground определить через Ground в test_narrative_threads.py.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_threads.py -q.
  Ожидается отсутствие переходов.
- [ ] **Step 3 — code.** Реализовать явную таблицу переходов. Для принявшего
  игрока нужен подтверждённый source; событие отказа сохраняется в source_refs.
  Active-count не включает hidden/dormant и не раскрывает чужие нити.
  Будущая подготовка хранится в плане; thread offered создаётся при предъявлении.
- [ ] **Step 4 — green.** Команда Step 2 и tests/test_narrative_storage.py;
  ожидается exit 0 и устойчивость статуса после новой сессии БД.
- [ ] **Step 5 — commit.** git commit -m "feat(narrative): track thread choices and audience attention".

### Task 7: Выделение общего атомарного runner

**Files:** Create app/tools/operation_group.py, tests/test_operation_group.py;
Modify app/tools/resolution/executor.py, context.py.

**Interfaces:**
- Produces async run_operation_group(ctx: ToolContext, calls: tuple[CompiledCall, ...],
  *, validate_step: Callable, annotate_event: Callable) -> GroupResult.
  Validate_step(ctx, call, bindings) -> None бросает ToolError при отказе;
  annotate_event(event, call) -> None задаёт только внутреннюю метаинформацию.
- CompiledCall и GroupResult определяются в app/tools/operation_group.py;
  compiler Task 8 импортирует эти внутренние типы оттуда.
- Existing execute_resolution(ctx, proposal, admission) -> ResolutionResult
  сохраняет подпись, источник, квитанцию, проверки и диагностический формат.

- [ ] **Step 1 — tests.** Настоящий инструмент успешно пишет Entity/Event,
  notices/outbox/audio/signals, следующий отказывает. SQL и transient
  возвращаются к снимку, потраченные попытки остаются в учёте.
  ~~~python
  def test_second_failure_restores_world_and_transient_channels(settings, client, admin):
      report = failed_group_scenario(settings, client, admin)
      assert report["world_after"] == report["world_before"]
      assert report["channels_after"] == report["channels_before"]
      assert report["calls_used"] == 2
  ~~~
  failed_group_scenario определить в test_operation_group.py через
  tests.test_tools.play и временные зарегистрированные тестовые обработчики.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_operation_group.py -q.
  Ожидается отсутствие runner.
- [ ] **Step 3 — code.** Выделить только общую механику savepoint и execute;
  source admission, combat guards, deed_key и receipt остаются в resolution.
  Снимок transient не копирует ORM. Обновление World после rollback сохраняет crew/focus.
  В CHANNELS включить operation_refs: группа, запросившая подготовку и
  затем отказавшая, не оставляет ссылку на откатившуюся подготовку.
  Проверить это отдельной веткой test_second_failure_restores_operation_refs.
  Runner не коммитит внешнюю транзакцию и не публикует bus.
- [ ] **Step 4 — green.** python -m pytest -n 0 tests/test_operation_group.py
  tests/test_resolution_executor.py tests/test_resolution_replay.py
  tests/test_resolution_busy.py tests/test_resolution_standing.py
  tests/test_resolution_visibility.py -q. Ожидается exit 0.
- [ ] **Step 5 — commit.** git commit -m "refactor(tools): share atomic registered operation groups".

### Task 8: Адресный патч основного сюжета и компиляция первого набора

**Files:** Create app/core/narrative/plan_patch.py,
app/tools/narrative/compiler.py, tools.py,
tests/test_narrative_plan_patch.py, tests/test_narrative_compiler.py;
Modify app/core/plot.py, app/tools/runtime.py.

**Interfaces:**
- Produces patch_future_plan(plan: dict, patch: FutureSituationPatch,
  facts: tuple[FactState, ...]) -> PlanPatchResult.
  PlanPatchResult: plan, changed_refs, violations.
- FutureSituationPatch имеет typed edits: update_open_node, add_open_node,
  bypass_open_node, update_open_act, retire_pending_act, update_question.
  Цели, summary и exit — текст; id-ссылки — проверенные; arbitrary JSON path нет.
- DTO patch/edit объявлены Task 1 в contracts.py; здесь определяется алгоритм.
- Produces compile_operations(snapshot: NarrativeSnapshot,
  proposal: AdaptationProposal) -> tuple[CompiledCall, ...].
- Регистрирует apply_narrative_fact, apply_narrative_thread,
  apply_future_situation, apply_existing_front_intent; инструменты не
  выдаются модели как альтернативный неограниченный интерфейс.

- [ ] **Step 1 — tests.** Активный частично пройденный акт допускает патч
  открытого узла; closed outcome и materialized anchors сохраняются.
  Отсутствие будущего злодея/прежнего числа актов не возвращает старый сюжет.
  ~~~python
  def test_open_node_changes_without_rewriting_closed_node():
      plan, patch, facts = partially_completed_plan_fixture()
      result = patch_future_plan(plan, patch, facts)
      assert result.violations == ()
      assert result.plan["acts"][0]["nodes"][0] == plan["acts"][0]["nodes"][0]
      assert result.plan["acts"][0]["nodes"][1]["summary"] == "Защита кладбища"
  ~~~
  Фабрику определить в test_narrative_plan_patch.py на основе good_plan;
  показать отдельный отказ на dangling clue/node_ref.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_plan_patch.py
  tests/test_narrative_compiler.py -q. Ожидается отсутствие патча.
- [ ] **Step 3 — code.** Добавить отдельную проверку адаптивного плана:
  целостность, опоры, templates и прежние верхние лимиты; стартовые minimum
  cardinalities не требуют восстановления прежнего конфликта.
  Регистрация работает через закрытый OperationSpec. Существующий antagonist
  меняет goal/stopped как текущее намерение, не текст прошлых threat-step.
  Story-hook создаёт thread и learn_fact в одной группе.
- [ ] **Step 4 — green.** Step 2 и python -m pytest -n 0 tests/test_plan.py
  tests/test_plot_anchors.py tests/test_narrative_policy.py -q.
  Ожидается exit 0; исходный strict merge_revision сохраняет поведение.
- [ ] **Step 5 — commit.** git commit -m "feat(narrative): patch open main-story situations through tools".

### Task 9: Применение адаптации, квитанции и конкурентная проверка

**Files:** Create app/tools/narrative/executor.py,
tests/test_narrative_executor.py, tests/test_narrative_replay.py;
Modify app/tools/narrative/tools.py, app/db/narrative.py.

**Interfaces:**
- Produces narrative_key(source: NarrativeSource) -> str (SHA-256).
- Produces async apply_in_context(ctx: ToolContext, proposal: AdaptationProposal,
  *, policy: NarrativePolicy) -> AdaptationResult.
- Produces async find_receipt(session, source: NarrativeSource) -> Event | None;
  async write_fact_snapshots(ctx, changed: tuple[FactState, ...]) -> SnapshotRef.
- Produces адаптер NarrativeApplier для локального и будущего runtime:
  квитанция сохраняется как Event.tool=adapt_story, hidden=True.

- [ ] **Step 1 — tests.** Повтор с другим proposal возвращает исходную
  квитанцию; no_change тоже имеет стабильный результат. Две настоящие сессии,
  проигранный guard, начало боя, изменение permission и нелокальные effects.
  ~~~python
  def test_changed_retry_returns_original_result(settings, client, admin):
      first, repeated, receipts = replay_scenario(settings, client, admin)
      assert first.status == "applied"
      assert repeated.status == "repeated"
      assert repeated.created_ids == first.created_ids
      assert receipts == 1
  ~~~
  replay_scenario определить в test_narrative_replay.py через play/run;
  отдельная гонка использует две сессии make_sessionmaker и async barrier.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_executor.py
  tests/test_narrative_replay.py -q. Ожидается отсутствие executor.
- [ ] **Step 3 — code.** Искать receipt до проверки уже закрытого источника.
  Получить world_write, перечитать затронутый снимок, проверить base/read_set,
  затем admission и compiler. Сохранить budgets, fact snapshots,
  narrative_revision и CampaignPlan в группе; parent receipt в той же транзакции.
  Неизвестные ошибки не конвертировать в новый creative/fallback.
  Механический результат другой ActionRef не закрывать.
- [ ] **Step 4 — green.** Step 2 и tests/test_operation_group.py,
  tests/test_resolution_end_to_end.py, tests/test_world_transactions.py.
  Ожидается exit 0 на SQLite и TEST_DATABASE_URL PostgreSQL;
  проигравшая операция не меняет новизну.
- [ ] **Step 5 — commit.** git commit -m "feat(narrative): apply adaptations with durable receipts and guards".

### Task 10: Локальный мастер, источники и безопасное повествование

**Files:** Create app/tools/narrative/sources.py,
app/agents/master/adaptation.py, tests/test_narrative_master.py;
Modify app/agents/master/turn.py, finish.py, narration.py, checkpoint.py,
app/agents/prompts/master_system.j2, narrate.j2,
app/core/campaigns.py, app/api/schemas.py, campaigns.py.

**Interfaces:**
- Produces async bind_scene_sources(ctx: ToolContext) -> tuple[NarrativeSource, ...];
  3 server-owned слота stable_part=0..2 на существующий MasterTurn,
  сохранённые в его trace. Слоты не сбрасываются при повторе.
- Produces async adaptation_prompt(ctx: ToolContext) -> str.
- Инструмент adapt_story принимает slot_ref, grounds, summary, operations;
  source/proposal_id/base собирает сервер из актуального слота.
- CampaignCreateIn/CampaignPatchIn получают optional narrative_mode:
  strict/adaptive. Пока default strict; module без metadata не принимает adaptive.
- Produces public_adaptation_effects(ctx: ToolContext, audience: tuple[str, ...])
  -> tuple[PublicEffect, ...].

- [ ] **Step 1 — tests.** Scripted LLM развивает NPC/открытый узел,
  провал проверки сохраняется, текст не создаёт факта, слоты не подделываются,
  приватный факт другой группы отсутствует в narration/voice.
  ~~~python
  def test_adaptation_does_not_complete_failed_player_action(game_client, admin_g, llm, settings):
      report = failed_check_with_new_opportunity(game_client, admin_g, llm, settings)
      assert report["check_success"] is False
      assert report["new_thread_status"] == "offered"
      assert report["player_accepted"] is False
  ~~~
  Определить сценарий в test_narrative_master.py на existing fixtures
  tests.test_master: act/rows/llm и tests.test_resolution_end_to_end.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_master.py -q.
  Ожидается отсутствие инструмента/контекста.
- [ ] **Step 3 — code.** Подключить адаптер в текущий decision-loop без нового
  mixin/LLM для каждой детали. Child-call budget учитывается как у resolution.
  Принятые effects входят в checkpoint и загрузку новой фазы описания.
  Резерв claims Task 5 выполняется перед LLM; публичный prompt не получает
  raw draft/receipt/secret grounds. Whisper не вызывает adapt_story.
  Настройка preview инициализирует данные Task 3, проверяет доступ owner/master,
  новый строгий режим не стирает принятые значения.
- [ ] **Step 4 — green.** python -m pytest -n 0 tests/test_narrative_master.py
  tests/test_master_creative.py tests/test_master_creative_world.py
  tests/test_resolution_visibility.py tests/test_whisper.py
  tests/test_world_transactions.py -q. Ожидается exit 0.
  Если публичная API-схема изменилась: python -m app.contract, npm run gen:api
  и npm run build из web; только соответствующие generated-файлы в коммит.
- [ ] **Step 5 — commit.** git commit -m "feat(master): adapt current scenes from verified player choices".

### Task 11: Gate A — первый законченный сценарий

**Files:** Create tests/test_narrative_first_slice.py;
Create docs/master-narrative-adaptation.md; Modify docs/README.md.

**Interfaces:**
- Consumes Tasks 1–10 и существующие player-message, tool, checkpoint пути.
- Produces run_alliance_story_scenario(...) -> dict только в тестовом файле:
  сохранённый союз, изменённый открытый узел, следующее описание, закрытый
  historical outcome, counts receipts, входы LLM после reconnect.

- [ ] **Step 1 — tests.** Один полный сценарий: переговоры по правилам →
  состоявшееся соглашение → изменение главного будущего узла →
  commit → новая группа сообщений/сцена → reconnect → повтор описания.
  ~~~python
  def test_alliance_changes_main_story_and_survives_reconnect(game_client, admin_g, llm, settings):
      report = run_alliance_story_scenario(game_client, admin_g, llm, settings)
      assert report["next_node"] == "Защита кладбища"
      assert report["closed_outcome_unchanged"]
      assert report["adaptation_receipts"] == 1
      assert not report["forced_kill_goal_in_next_prompt"]
  ~~~
  Параметризовать сбой narration после effects_committed; сравнивать
  сохранённый следующий prompt/план, не точную художественную фразу.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_first_slice.py -q.
  Если всё проходит сразу, сценарий уже подтверждён; не ломать код ради red.
  Проверить содержательность assert и отдельную ветку без адаптации.
- [ ] **Step 3 — code.** Исправить только выявленные разрывы интеграции.
  Документировать preview procedural-only, сохранённые исходы, действия
  управления режимом и пока недоступные draft/module операции.
- [ ] **Step 4 — gate.** Запустить first-slice и группы Tasks 7–10 на обеих БД.
  Ожидается exit 0, один принятый союз и реально другой следующий материал.
  Gate A не означает готовность режиссёра и адаптивных модулей.
- [ ] **Step 5 — commit.** git commit -m "test(narrative): verify player alliance changes the main story".

### Task 12: Устойчивые задания, lease и источник режиссёра

**Files:** Create alembic/versions/0022_narrative_work.py,
app/db/narrative_jobs.py, tests/test_narrative_jobs.py;
Modify app/db/models.py, app/core/narrative/ports.py, contracts.py,
tests/narrative_helpers.py.

**Interfaces:**
- Produces NarrativeWork по spec §15.1 и SqlNarrativeJobs(maker, *,
  max_author_slots: int=2), реализацию порта.
- Produces NarrativeJobs:
  async enqueue(boundary: BoundaryRecord) -> str;
  async claim(now: datetime) -> WorkClaim | None;
  async reserve_call(claim: WorkClaim, now: datetime) -> WorkClaim | None;
  async renew(claim: WorkClaim, now: datetime) -> bool;
  async save_draft(claim: WorkClaim, proposal: AdaptationProposal) -> None;
  async finish(claim: WorkClaim, result: AdaptationResult) -> None;
  async resnapshot(claim: WorkClaim, now: datetime) -> WorkClaim | None.
- BoundaryRecord: campaign_id, kind, source_id, evidence_refs, audience,
  focus, session_budget_ref, policy_version. SourceKey определяется границей.
- WorkClaim имеет phase: author/apply. Prepared claim не делает новый LLM-вызов.
- FakeClock в tests/narrative_helpers.py: __call__() -> aware UTC datetime,
  advance(seconds: int) -> None.

- [ ] **Step 1 — tests.** Duplicate enqueue, claim из двух сессий, истёкший
  lease, late answer, 2/3 вызова, 6/7 claim, один resnapshot,
  восстановление prepared, defer без нового авторства.
  ~~~python
  def test_old_lease_cannot_replace_saved_draft(settings, client, admin):
      report = lease_takeover_scenario(settings, client, admin)
      assert report["old_save_rejected"]
      assert report["active_draft_summary"] == "Новый владелец"
      assert report["llm_calls"] <= 2
  ~~~
  Сценарий определить в test_narrative_jobs.py с FakeClock и двумя сессиями.
  Job-only запись не увеличивает world_revision.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_jobs.py -q.
  Ожидается отсутствие таблицы и lease.
- [ ] **Step 3 — code.** Состояния — по spec §15.2; токены проверяются
  условной записью. Author lease=120 секунд, heartbeat=30; deadline сети
  будет 90 в Task 13. Общие 2 author-слота обеспечить capacity_slot и
  уникальным частичным индексом на занятый авторский slot; unique preparing
  по campaign_id исключает двух одновременных авторов одной кампании.
  Истёкшие lease освобождают слот и сохраняют израсходованные call reservations.
  SQLite и PostgreSQL используют один observable контракт.
  Work не включать в world_tx._BY_CAMPAIGN. Номер миграции сверить с актуальным head.
- [ ] **Step 4 — green.** Step 2 на обеих БД; миграционные проверки Task 3
  с новым head. Ожидается exit 0; повторный job не создаёт второй источник.
- [ ] **Step 5 — commit.** git commit -m "feat(narrative): persist recoverable director jobs and leases".

### Task 13: LLM-автор с ограниченным контекстом

**Files:** Create app/agents/director.py, app/agents/prompts/director.j2,
tests/test_narrative_director.py; Modify app/core/narrative/contracts.py.

**Interfaces:**
- Produces LlmNarrativeAuthor(llm: LLM, model_config, *,
  token_counter: Callable[[str], int], timeout_seconds: int=90,
  call_observer: Callable[[AuthorCallReport], Awaitable[None]]).
  Реализует NarrativeAuthor, не импортирует ORM и tools.
- Produces pack_director_input(snapshot: NarrativeSnapshot, *,
  token_counter: Callable[[str], int], max_tokens: int=6000) -> DirectorInput.
- Produces decode_director_reply(snapshot: NarrativeSnapshot,
  arguments: dict) -> AdaptationProposal.
- DirectorInput: messages, tool_schema, permitted_refs, complete_for_edit,
  estimated_input_tokens. Его источники принадлежат снимку.
- AuthorCallReport: source, author_attempt, model, tokens_in, tokens_out,
  cost, latency_ms, error. Runtime-observer обновляет зарезервированный LlmCall,
  автор передаёт отчёт через callback и не зависит от ORM.

- [ ] **Step 1 — tests.** Structured tool-call, unknown field, чужие refs,
  forged identity, no_change, непоместившаяся зависимость и ограниченный контекст.
  ~~~python
  def test_context_limit_does_not_turn_omitted_fact_into_freedom():
      snap = snapshot_with_required_dependency_too_large()
      packed = pack_director_input(snap, token_counter=len, max_tokens=6000)
      assert packed.estimated_input_tokens <= 6000
      assert not packed.complete_for_edit
      assert packed.permitted_refs == ()
  ~~~
  Фабрику определить в test_narrative_director.py; len — тестовый счётчик.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_director.py -q.
  Ожидается отсутствие автора.
- [ ] **Step 3 — code.** Существующий llm.complete: max_tokens=4096,
  сетевой deadline 90 секунд. В лимит входа включить system, tools и messages.
  Production использует token_counter LiteLLM, при неподдерживаемом
  tokenizer — консервативный счётчик UTF-8 bytes.
  Отбирать целые записи: grounds и необходимые зависимости → участники
  и результаты → связанные нити → вспомогательная память.
  Промпт требует подхватывать выбор, соблюдать независимость сторон,
  различать план/событие и допускает no_change.
  Автор не пишет LlmCall или мир; ошибка возвращается workflow.
- [ ] **Step 4 — green.** Step 2; ожидается exit 0, fake complete с bounded
  input, отсутствие DB-import и неограниченных аргументов автора.
- [ ] **Step 5 — commit.** git commit -m "feat(narrative): propose bounded story continuations with an LLM".

### Task 14: Оркестрация через порты и восстановление режиссёра

**Files:** Create app/core/narrative/service.py,
app/tools/narrative/runtime.py, tests/test_narrative_service.py,
tests/test_narrative_recovery.py;
Modify app/agents/master/service.py, finish.py.

**Interfaces:**
- Produces NarrativeService(reader: NarrativeReader, author: NarrativeAuthor,
  applier: NarrativeApplier, jobs: NarrativeJobs, clock: Callable).
  async prepare_once() -> PreparationReport;
  async run_due(*, limit: int=20) -> tuple[PreparationReport, ...].
- PreparationReport: work_id, status, reason_code, calls_reserved.
- Produces RuntimeNarrativeApplier(maker, bus, coordination, *,
  policy_provider), реализацию NarrativeApplier.
- MasterService получает optional narrative_preparer в конструкторе;
  прежние клиенты без аргумента продолжают работать.
- Runtime-адаптер резервирует LlmCall и проверяет spend_limit_usd перед сетью.

- [ ] **Step 1 — tests.** Pure service с fake-портами: no_change, отказ,
  correction, stale/resnapshot, exhausted budget, prepared defer.
  Реальный restart после draft/commit и бой во время LLM.
  ~~~python
  def test_prepared_deferred_work_does_not_call_author_again():
      service, author, jobs = prepared_service_fixture(pending_narration=True)
      report = run_service_once(service)
      assert report.status == "deferred"
      assert author.calls == 0
      assert jobs.saved_draft_unchanged
  ~~~
  Fake-порты и run_service_once определить в test_narrative_service.py
  через asyncio.run; никаких реальных sleep.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_service.py
  tests/test_narrative_recovery.py -q. Ожидается отсутствие workflow.
- [ ] **Step 3 — code.** Claim → snapshot → reserve_call до сети → author →
  save_draft → apply → finish. Correction использует stable source и
  structured reasons; общий LLM-limit 2. Prepared сразу идёт в apply.
  Перед внешним commit проверить lease, pending narration и свежий read_set.
  No_change имеет receipt без изменения мира.
  Ошибка одной работы не останавливает batch; due-scan ограничен limit.
  Подключить существующий recovery loop каждые 15 секунд и wake signal.
  Await сети не держит Coordination lock или AsyncSession.
  Heartbeat и учёт модели — инфраструктурные адаптеры, не импорты core service.
  Перед propose снимок получает author_attempt из reserve_call.
  Call_observer сохраняет метрики и сбой оплаченной попытки.
  Denied с оставшимся лимитом сохраняет violations как feedback следующего
  снимка; после рестарта feedback читается из bounded last_result работы.
- [ ] **Step 4 — green.** Step 2 на обеих БД, tests/test_narrative_jobs.py,
  tests/test_world_transactions.py. Ожидается exit 0 и одна квитанция
  после неопределённого commit.
- [ ] **Step 5 — commit.** git commit -m "feat(narrative): recover director preparation through injectable ports".

### Task 15: Триггеры и переход архитектора — Gate B

**Files:** Create app/core/narrative/triggers.py,
tests/test_narrative_triggers.py, tests/test_narrative_architect.py;
Modify app/agents/architect.py, app/agents/master/service.py, turn.py,
finish.py, app/tools/plot.py, app/core/narrative/contracts.py.

**Interfaces:**
- Produces derive_boundaries(events: tuple[EvidenceRecord, ...],
  turn: TurnBoundaryState, policy: NarrativePolicy) -> tuple[BoundaryRecord, ...].
- TurnBoundaryState: id, phase, session_id, focus, audience, external_boundary.
- Produces async enqueue_boundaries(ctx: ToolContext,
  boundaries: tuple[BoundaryRecord, ...]) -> tuple[str, ...].
- architect.revise(svc, cid) -> str | None остаётся совместимым:
  adaptive — future producer через новый путь; strict — прежняя область
  пересмотра с world guard и известными commitments.
- Boundary kinds: choice, relationship, situation_closed, act_closed,
  session_closed, opportunities_exhausted, front_threshold.

- [ ] **Step 1 — tests.** Dedup границы, coalesce pending, отсутствие рекурсии,
  отказ от главного узла, replan=false, pause и прежний strict replan.
  ~~~python
  def test_adaptation_events_do_not_spawn_recursive_director_jobs():
      boundaries = derive_boundaries((adaptation_evidence(),),
                                     turn_boundary(external_boundary=False),
                                     policy())
      assert boundaries == ()
  ~~~
  Фабрики определить через DTO в test_narrative_triggers.py.
  Сквозной alliance получает future-патч после восстановления задания;
  legacy-revise и adaptive не теряют обновление при гонке.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_triggers.py
  tests/test_narrative_architect.py -q. Ожидается отсутствие триггеров/cutover.
- [ ] **Step 3 — code.** Enqueue вместе с исходной границей; notify — ускоритель.
  Message/Event id не сортировать как курсор. Coalesce сохраняет grounds;
  claimed работа неизменяема. Старый full merge не является вторым
  независимым писателем adaptive-плана.
  Между сессиями future меняет невведённый материал, scene ждёт границы.
  Session_budget_ref не сбрасывается паузой и реальным временем.
- [ ] **Step 4 — gate B.** Step 2, tests/test_plan.py,
  tests/test_narrative_first_slice.py, tests/test_narrative_recovery.py.
  Ожидается exit 0 на обеих БД; deferred без lock,
  replan=false выключает режиссёра и сохраняет локальную адаптацию.
- [ ] **Step 5 — commit.** git commit -m "feat(narrative): ground director jobs in committed story boundaries".

### Task 16: Новые участники и совместимость standing

**Files:** Modify app/core/narrative/operations.py, policy.py,
app/tools/narrative/compiler.py, tools.py,
app/tools/master/entities.py, app/tools/resolution/creative.py;
Create tests/test_narrative_actors.py, tests/test_narrative_standing.py.

**Interfaces:**
- Реализует introduce_actor: actor_slot, template_id, place_ref, attitude,
  public_description, mode: sketch/materialize.
- Produces resolve_local_ref(bindings: dict[str, str], ref: LocalRef) -> str;
  LocalRef разрешён только для уже исполненной операции пакета.
- Produces async authorize_actor_slot(ctx, slot_id: str,
  args: SpawnArgs) -> ActorAdmission, с allowed/reason_code/existing_entity_id.
- Реализует settle_standing_response: фактические effects, затем resolve_response
  в одной группе; существующий ready -> done.

- [ ] **Step 1 — tests.** Reuse, future sketch вне сцены, идентичность
  materialize, neutral без hostile default, local_ref и encounter budget.
  ~~~python
  def test_materializing_existing_slot_does_not_charge_novelty_twice(settings, client, admin):
      report = actor_slot_scenario(settings, client, admin)
      assert report["distinct_entities"] == 1
      assert report["total_novelty"] == 1
      assert report["attitude"] == "neutral"
  ~~~
  Standing race normal vs narrative: один подарок/закрытие; отказ оставляет ready.
  Сценарии определить в соответствующих тестовых файлах через play/run.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_actors.py
  tests/test_narrative_standing.py -q. Ожидается operation_not_available.
- [ ] **Step 3 — code.** Compile в develop/spawn_entity и существующие
  standing-tools, не insert Entity. Actor-slot разрешение — server-owned
  token точной операции; сверять args и с turn_id=None.
  Local_ref не выдаёт произвольный доступ; повторный dead NPC не возрождается.
  Standing не создаёт вторую репутацию; status и guard защищают оба маршрута.
  Hostile materialize проходит бюджет и обычную инициативу,
  не наносит урон через narrative-путь.
- [ ] **Step 4 — green.** Step 2, tests/test_standing.py,
  tests/test_resolution_standing.py, tests/test_master_creative_world.py,
  tests/test_adventure.py. Ожидается exit 0 на обеих БД.
- [ ] **Step 5 — commit.** git commit -m "feat(narrative): introduce durable actors and reuse standing responses".

### Task 17: Пересмотр draft и согласованное модульное чтение

**Files:** Modify app/core/narrative/facts.py, view.py, policy.py, operations.py,
app/tools/narrative/compiler.py, tools.py, reader.py,
app/core/adventure.py, knowledge.py,
app/agents/master/creative.py, recall.py, app/core/world_generation/service.py;
Create tests/test_narrative_drafts.py, tests/test_narrative_module_view.py.

**Interfaces:**
- Produces revise_draft(current: FactState, new_value: str, ground: Ground,
  dependency_states: tuple[FactState, ...]) -> FactRevision
  с before/after/violations.
- Produces effective_module_entry(base_entry, view: CampaignNarrativeView)
  -> immutable представление Entry; пакетная Entry не мутирует.
- Namespace adapters поддерживают role, motivation, relationship,
  secret_truth, situation_premise по exact typed addresses.

- [ ] **Step 1 — tests.** Draft меняется, committed/anchor отказывают;
  current_state не меняет historical-прошлое; две кампании изолированы;
  fresh reveal во время автора даёт stale.
  ~~~python
  def test_unrevealed_materialized_secret_cannot_be_rewritten():
      old = fact(freedom="committed", audience=())
      result = revise_draft(old, "другая истина", divergence_ground(), ())
      assert result.violations == ("fact_committed",)
  ~~~
  divergence_ground определить через Ground в тестовом файле.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_drafts.py
  tests/test_narrative_module_view.py -q. Ожидается недоступный draft-пересмотр.
- [ ] **Step 3 — code.** Выдать revise_draft_fact только по разрешённому
  адресу. Adventure, lore retrieval, creative_opportunities, генерация и prompt
  читают одинаковое новое значение.
  Плановый namespace читает CampaignSecret.plot; module override — Fact.
  Raw catalog не переключать глобально; исторические версии — по snapshot_ref.
  Статистика, геометрия, DC и механические effects не входят в overrides.
- [ ] **Step 4 — green.** Step 2, tests/test_adventure.py, tests/test_modules.py,
  tests/test_world_generation.py, tests/test_narrative_commitments.py,
  tests/test_narrative_replay.py. Ожидается exit 0 и одинаковая трактовка
  разрешённого нового мотива всеми затронутыми читателями.
- [ ] **Step 5 — commit.** git commit -m "feat(narrative): revise permitted drafts through isolated module views".

### Task 18: Разрешения модулей и пространственные зависимости

**Files:** Modify app/core/modules.py, app/content/schema/core.yaml,
app/agents/translator.py, app/agents/architect.py,
app/core/plot_anchors.py, app/core/world_generation/contracts.py, storage.py;
Create tests/test_narrative_module_permissions.py,
tests/test_narrative_blueprint_contract.py.

**Interfaces:**
- Produces parse_narrative_permissions(module_data: dict,
  catalog) -> NarrativePermissions; missing metadata — strict-права.
- Produces validate_used_fact_refs(snapshot: NarrativeSnapshot,
  refs: tuple[FactRef, ...]) -> tuple[FactRef, ...].
- Metadata schema_version=1: anchors, mutable_fact_addresses,
  operation_kinds, supplement_scopes. Ссылки реальны в закреплённом пакете.
- Spatial producer передаёт used_fact_refs в record_commitments Task 5.
  Новый blueprint/старые sketch/anchor/reservation используют один контракт;
  SVG-генератор здесь не создаётся.

- [ ] **Step 1 — tests.** Legacy strict; неизвестный address/key/op/schema
  отклоняется на импорте; подготовленная геометрия не размораживается.
  ~~~python
  def test_blueprint_does_not_freeze_unrelated_npc_motive(settings, client, admin):
      report = blueprint_commitment_scenario(settings, client, admin)
      assert report["hidden_passage_freedom"] == "committed"
      assert report["unused_npc_motive_freedom"] == "draft"
      assert report["late_passage_revision_denied"]
  ~~~
  Fake producer определить через record_commitments в указанном тесте;
  тест не импортирует ещё не реализованный map-generator.
- [ ] **Step 2 — red.** python -m pytest -n 0
  tests/test_narrative_module_permissions.py tests/test_narrative_blueprint_contract.py -q.
  Ожидается отсутствие metadata parsing или неверный scope.
- [ ] **Step 3 — code.** Translator/architect предлагают permissions;
  импорт валидирует. Принятый старый пакет не изменять.
  Used refs закрепляются вместе с сохранением структуры.
  Неясные legacy-зависимости защищают свою область; независимые мотивы свободны.
  Документировать допустимые permissions и границу запрета геометрии.
- [ ] **Step 4 — green.** Step 2, tests/test_content.py, tests/test_modules.py,
  tests/test_plot_anchors.py, tests/test_world_generation.py;
  python -m app.content validate content/dnd5e-srd --strict.
  Ожидается exit 0; отсутствие metadata допустимо для legacy-импорта.
- [ ] **Step 5 — commit.** git commit -m "feat(narrative): validate module freedom and spatial fact dependencies".

### Task 19: Фронты и драматические вопросы — Gate C

**Files:** Create app/core/narrative/fronts.py,
tests/test_narrative_fronts.py, tests/test_narrative_adaptive_module.py;
Modify app/core/plot.py, app/tools/plot.py, app/gateway/ws.py,
app/core/narrative/contracts.py, operations.py, policy.py,
app/tools/narrative/compiler.py, tools.py.

**Interfaces:**
- Produces iter_fronts(plan: dict) -> tuple[FrontView, ...].
- Produces tick_fronts(plan: dict, game_time: int, *,
  length: str, mode: str) -> FrontTickResult с next_plan/progress_events/ready_intents.
- Produces advance_front(front: FrontView, ground: Ground,
  *, transition_key: str) -> FrontTransition.
- QuestionState: id, text, subject_refs, status: open/answered/obsolete, outcome.
  Реализует update_question существующего typed patch.

- [ ] **Step 1 — tests.** Legacy не дублируется; дни/события не тикают дважды;
  разговор сам не останавливает фронт, союз может; тайный союз не известен
  инквизиции; clock не материализует армию свободным текстом.
  ~~~python
  def test_progress_readiness_does_not_materialize_an_army():
      plan = plan_with_front_near_threshold()
      result = tick_fronts(plan, game_time=86400 * 3, length="short", mode="adaptive")
      assert result.ready_intents
      assert all(intent.kind != "entity_created" for intent in result.ready_intents)
  ~~~
  Фабрика явно задаёт clock_at/period/порог в test_narrative_fronts.py.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_fronts.py
  tests/test_narrative_adaptive_module.py -q. Ожидается отсутствие нового clock.
- [ ] **Step 3 — code.** Iter_fronts адаптирует antagonist.threat_step/stopped
  и plot.fronts без второго прогресса. Run_clock и human-master ws используют
  общий clock; strict сохраняет прежнюю семантику.
  Adaptive threshold создаёт намерение либо исполняет заранее типизированный
  эффект инструментом. World_time проверяет обработанный интервал;
  transition_key дедуплицируется. Outcome вопроса следует из событий.
- [ ] **Step 4 — gate C.** Сквозной adaptive module: союз → новое намерение →
  допустимый draft → один NPC → согласованные читатели → следующая сцена.
  Step 2 и tests/test_standing.py, tests/test_plan.py,
  tests/test_adventure.py, tests/test_narrative_first_slice.py.
  Ожидается exit 0 на обеих БД; улики и геометрия сохранены.
- [ ] **Step 5 — commit.** git commit -m "feat(narrative): evolve fronts and open campaign questions".

### Task 20: Настройки, безопасные статусы и контракт клиента

**Files:** Modify app/api/schemas.py, campaigns.py, plan.py,
app/core/campaigns.py, master_log.py, app/gateway/protocol.py,
web/openapi.json, web/src/lib/api.gen.ts, web/src/lib/types.ts;
Create tests/test_narrative_access.py;
Modify docs/master-narrative-adaptation.md.

**Interfaces:**
- Campaign.settings.narrative содержит только mode/policy_version.
- NarrativePreparationStatusOut: pending/preparing/ready/failed,
  без grounds/source refs/summary; доступ по existing manager-policy.
- Master-only подробности — existing plan_out/get-secrets/master-log;
  проверка места мастера, а не один is_owner.
- Domain status преобразуется в публичный централизованно.

- [ ] **Step 1 — tests.** Owner без master-seat не видит причины,
  другая группа не видит нити и counts, отключение сохраняет overrides,
  replan=false не отключает локальную адаптацию.
  ~~~python
  def test_owner_without_master_seat_cannot_read_director_reasons(client, admin, settings):
      response = owner_plan_status_scenario(client, admin, settings)
      assert "grounds" not in response
      assert "draft" not in response
      assert "secret_summary" not in response
  ~~~
  Сценарий определить с существующими viewer-fixtures.
  Проверить приватность voice/summary вместе с API.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_access.py -q.
  Ожидается отсутствие статуса либо утечка тестового секрета.
- [ ] **Step 3 — code.** Typed settings и вычисленный status; смена режима
  не удаляет данные. Причины работ/trace редактируются existing master-log.
  Использовать существующие state events, если их хватает;
  новый WS kind не обязателен. Нового экрана квестов в этой поставке нет.
- [ ] **Step 4 — green.** python -m pytest -n 0 tests/test_narrative_access.py
  tests/test_contract.py tests/test_resolution_visibility.py tests/test_whisper.py -q.
  python -m app.contract; из web: npm run gen:api, npm test, npm run build.
  Ожидается exit 0 и generated-типы без секретных fields.
- [ ] **Step 5 — commit.** git commit -m "feat(narrative): expose safe adaptation settings and diagnostics".

### Task 21: Качество, масштаб и итоговая приёмка — Gate D

**Files:** Create tests/fixtures/narrative_quality.json,
tools/eval_narrative.py, tests/test_narrative_quality.py,
tests/test_narrative_scale.py;
Modify tests/test_narrative_first_slice.py,
tests/test_narrative_adaptive_module.py,
app/core/campaigns.py, .github/workflows/ci.yml,
docs/master-narrative-adaptation.md, docs/README.md.

**Interfaces:**
- QualityCase: id, snapshot, reference_good, reference_bad, rubric,
  allowed_no_change, forbidden_effects.
- Produces score_structural_quality(case: QualityCase,
  proposal: AdaptationProposal) -> QualityReport
  с structural_pass/rubric_observations/requires_human_review.
- CLI python tools/eval_narrative.py --cases PATH --mode scripted|live --output PATH.
  Default scripted; live использует явно выбранный model-config,
  не работает в обычном CI.

- [ ] **Step 1 — tests.** 8 случаев: союз; второстепенный NPC; ошибочная
  догадка; отказ от главной зацепки; победа; тихая сцена; скрытая улика;
  конфликт интересов групп.
  ~~~python
  def test_valid_continuation_can_still_require_quality_review():
      case = load_quality_case("rejected_main_hook")
      report = score_structural_quality(case, case.reference_bad)
      assert report.requires_human_review
      assert "player_refusal_reused_as_mandatory_goal" in report.rubric_observations
  ~~~
  Load helper определить в тестовом файле; reference_bad имеет явные
  annotations кейса. Не обещать такой вывод для любой прозы автоматически.
  Scale: 10 000 посторонних Event/Message, bounded queries, 50/80/20 records,
  context cap и индексные чтения; без нестабильного wall-clock assertion.
- [ ] **Step 2 — red.** python -m pytest -n 0 tests/test_narrative_quality.py
  tests/test_narrative_scale.py -q. Ожидается отсутствие eval/selector
  либо нарушение ещё не реализованного предела.
- [ ] **Step 3 — code.** Добавить недостающие измеримые пределы и диагностику.
  Trace: source_key, proposal_id, версии, cost/calls, admission и budgets,
  без публичных секретов. Rubric — влияние выбора, развитие старого,
  самостоятельность сторон, отсутствие обязательного осложнения.
  Эстетика требует оценки, число новых NPC не считается качеством.
  После Gates A–C новые procedural получают adaptive default;
  legacy/module остаются strict без явного включения.
- [ ] **Step 4 — gate D.** python -m pytest -q; python -m ruff check .;
  python -m ruff format --check .; миграции и полный pytest PostgreSQL;
  server/client contracts, content validate, npm test/build.
  Scripted LLM — локальный. Live-прогон только с уже разрешённым
  model-config; отсутствие ключа не обозначать как PASS модели.
  Отдельно отчитаться о серверных гарантиях и творческом поведении.
- [ ] **Step 5 — commit.** git commit -m "test(narrative): validate creative quality recovery and bounded scale".

## Матрица покрытия спека

| Раздел спека | Задачи |
| --- | --- |
| 1. Цель | 11, 15, 19, 21 |
| 2. Существующая архитектура | 3–5, 7–10, 15–19 |
| 3. Подход | 1, 4, 7, 14 |
| 4. Инварианты | 2, 5, 6, 9, 10, 17, 20 |
| 5. Канон | 3–5, 9, 17, 18 |
| 6. Основания | 1, 2, 4, 10, 15, 19 |
| 7. Компоненты | 1, 4, 7, 12–14 |
| 8. Контракты | 1, 4, 9, 12, 13 |
| 9. Операции | 2, 8, 16–19 |
| 10. Применение | 2, 7–9, 14 |
| 11. Рассказчик/режиссёр | 10, 12–15 |
| 12. Фронты/вопросы | 8, 19 |
| 13. Представление | 4, 5, 10, 17, 18 |
| 14. Нити | 6, 8–10, 20 |
| 15. Данные | 3, 9, 12, 14, 15 |
| 16. Стоимость | 2, 6, 9, 12–15, 21 |
| 17. Совместимость | 3, 10, 15, 17, 18, 20, 21 |
| 18. Секретность | 4, 5, 10, 20 |
| 19. Тесты | Все; сквозные 11, 15, 19, 21 |
| 20. Эксплуатация | 9, 12–15, 20, 21 |
| 21. Поставки | Gates A–D |
| 22. Приёмка | 11, 15, 19, 21 |
| 23. Некромант | 11, 15, 19 |
| 24. Уточнения | 5, 11, 18, 21 |

## Ограничения и дальнейшее расширение

Все возможности спека имеют задачу, но rollout может остановиться на
работающем Gate A/B с явным набором операций. Частичный выпуск не выдаётся
за полную адаптацию готовых модулей.

Вне плана: SVG-генератор, распределённый запуск всего приложения, универсальный
откат опубликованной кампании, динамические плагины, новый экран нитей,
замена транспорта на transactional outbox. Для них сохранены точки расширения.

Изменения поведения или центральных контрактов возвращаются в спек и план.
Рутинное исправление теста/совместимого адаптера не требует согласования
каждого шага.

## Самопроверка и передача в исполнение

- [x] Сверить coverage со спеком, включая §24.
- [x] Проверить одинаковые типы/подписи Interfaces и последующих Consumers.
- [x] У каждой задачи есть результат, тесты и отдельный commit.
- [x] Review Focus имеет содержательные тесты.
- [x] Сверить миграции, существующие файлы и границу первого среза.
- [ ] Получить ревью плана и выбранный способ исполнения до изменения кода.

Рекомендуемый способ — native: задачи тесно связаны источниками, снимком,
закреплением и транзакцией. Последовательное исполнение с ревью каждого gate
уменьшает риск несогласованных контрактов.
Subagent-driven также допустим по выбору пользователя; нельзя одновременно
менять общий executor/checkpoint независимыми исполнителями без согласования.
