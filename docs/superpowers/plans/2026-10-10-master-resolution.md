# Master Resolution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Связать обычные решения, внебоевой фолбек и творческое поведение мастера общими безопасными контрактами, сохранив действующие правила и единый мир.

**Architecture:** Модульный монолит: существующий реестр исполняет инструменты, небольшие адаптеры формируют контекст, проверяют допуск и применяют типизированные последствия. Общий фундамент используется двумя отдельными ветвями — фолбеком и творчеством; повествование не меняет мир.

**Tech Stack:** Python 3.12, Pydantic, SQLAlchemy AsyncSession, SQLite/PostgreSQL, pytest/xdist, Jinja2; существующие Event, MasterTurn, standing, fortune и память. Новых зависимостей нет.

**Spec:** `docs/superpowers/specs/2026-10-10-master-resolution-architecture-design.md`, `docs/superpowers/specs/2026-10-10-noncombat-adjudication-design.md`, `docs/superpowers/specs/2026-10-10-master-creative-agency-design.md`.

## Global Constraints

- «Мастер самостоятельно выбирает внебоевой исход и любые соразмерные последствия»; дополнительное подтверждение игрока не вводится.
- «Настоящий провал проверки не запускает фолбек»; ошибки исполнения отделены от отрицательных игровых результатов.
- «Канон, фактические результаты, воля игрока и боевые правила остаются обязательными».
- «Неразмеченная ошибка не допускает фолбек»; сообщение модели и текст исключения не являются разрешением.
- «Боевой жизненный цикл не переписывается»; атака до инициативы тоже является боевой заявкой.
- «Публикация ждёт commit существующего координатора хода»; успешный savepoint не равен сохранённому ходу.
- «Последствия и хуки не применяются дважды»; уже подтверждённый бросок не переигрывается.
- «Не создаются дублирующие репутация, генератор встреч, реестр NPC, память, событийное хранилище, транспорт сообщений или редактор политик».
- Существующие ответы `{ok, result, event_id}` и старые события читаются совместимо; новые JSON-контракты используют `schema_version=1`.
- В первом выпуске нет новых пользовательских настроек, миграций таблиц, динамических плагинов и универсального редактирования БД.
- Все новые изменяющие сценарии проверяются на SQLite и PostgreSQL; документы не являются доказательством работоспособности.

## Review Focus

1. Составная заявка содержит разговор и атаку: нельзя выдать разговорный фолбек на неотделённую боевую часть — тест Task 3.
2. Два обработчика одновременно получают одну заявку: цена и AFTER_CALL применяются один раз — тест Task 5 на PostgreSQL.
3. Последствие записало уведомление и сигнал, следующая операция отказала: ни SQL, ни контекст не должны сохранить частичный успех — тест Task 4.
4. Успешный фолбек и неудачный переход другой заявки оказались в одном ходе: первый не снимает защиту второго — тест Task 7.
5. При расколе отряда NPC узнал секрет одной группы: карта, голос и сводка другой группы не раскрывают его — тесты Tasks 7 и 10.

## Карта файлов и границы

Новые файлы добавляются по мере готовности задач, не заранее как пустой каркас.

| Файл | Ответственность |
| --- | --- |
| `app/core/resolution/contracts.py` | Чистые типы ссылки, отказа, предложения и результата |
| `app/core/resolution/policy.py` | Чистая политика по проверенному контексту и описанию способности |
| `app/tools/resolution/requests.py` | Привязка к сообщениям/ответам мира, проверенный контекст и попытки |
| `app/tools/resolution/capabilities.py` | Статический перечень способностей и их ограничений |
| `app/tools/resolution/operations.py` | Закрытая типизированная связь последствий с существующими инструментами |
| `app/tools/resolution/context.py` | Снимок и восстановление побочных эффектов ToolContext |
| `app/tools/resolution/executor.py` | Атомарное исполнение группы через registry.execute |
| `app/tools/master/adjudication.py` | Нативный инструмент внебоевого решения мастера |
| `app/agents/master/resolution.py` | Небольшой адаптер фазы решений, без нового координатора хода |
| `app/agents/master/creative.py` | Проверенные возможности импровизации и напоминания о последствиях |

Существующие `registry.py`, `turn.py`, `outcomes.py`, `narration.py`, `standing.py` и промпты меняются точечно. Нет обратной зависимости чистого `app/core/resolution` от инструментов или LLM.

## Очерёдность и точки остановки

Tasks 1–5: общий фундамент. Tasks 6–7: работающий фолбек. Tasks 8–10: творческое поведение. Task 11: сквозная приёмка. Это один маршрут с отдельными проверяемыми поставками, а не одновременная переделка мастера. После каждой задачи — тесты и отдельный коммит; интеграция в main только по отдельному указанию пользователя.

---

### Task 1: Типы и совместимые структурированные ошибки

**Files:** Create `app/core/resolution/__init__.py`, `app/core/resolution/contracts.py`; Modify `app/tools/registry.py`; Test `tests/test_resolution_contracts.py`, `tests/test_tools.py`.

**Interfaces:**
- `ActionRef(campaign_id: str, source_kind: Literal['message','standing_response','event'], source_id: str, actor_id: str, part: int)`; `part >= 0`.
- `FailureInfo(code: str, category: Literal['invalid_arguments','rule_denial','unsupported','technical_safe','unknown'], rolled_back: bool, attempt_id: str)`.
- `ResolutionResult(schema_version=1, execution: Literal['applied','denied','failed','repeated'], game_outcome: Literal['success','partial','failure'] | None, event_ids: list[str], completed_parts: list[int], failure: FailureInfo | None)`.
- `ToolError(message: str, *, code: str='unclassified', category: str='unknown')` сохраняет старые однопараметрические вызовы. `UnsupportedMechanicError` — типизированный ToolError, не произвольное исключение модели.
- `normalize_result(raw: dict, *, attempt_id: str) -> ResolutionResult` не меняет исходный словарь.
- Все сохраняемые контракты содержат `schema_version: Literal[1]=1`; внутренние CapabilitySpec/Admission не сохраняются как разрешение модели.

- [ ] **Step 1 — failing tests.** Добавить `test_check_failure_is_execution_success`, `test_legacy_tool_error_denies_fallback`, `test_invalid_args_have_stable_code`, `test_contract_rejects_extra_fields`. Ключевая проверка:
  ```python
  r = normalize_result({"ok": True, "result": {"success": False}, "event_id": "ev_1"}, attempt_id="a_1")
  assert r.execution == "applied" and r.game_outcome == "failure"
  assert r.event_ids == ["ev_1"]
  ```
- [ ] **Step 2 — red.** `pytest -n 0 tests/test_resolution_contracts.py -q`; новые проверки падают на отсутствующем контракте.
- [ ] **Step 3 — implementation.** Pydantic `extra='forbid'`; добавить в отказ registry поле `failure`, сохранив `ok/error`. Валидация аргументов → `invalid_arguments`; неверный id → `rule_denial`; старые исключения → `unknown`. Не классифицировать по русскому тексту и не перехватывать неизвестные исключения как безопасные.
- [ ] **Step 4 — green.** `pytest -n 0 tests/test_resolution_contracts.py tests/test_tools.py -q`; все проходят, старые проверки error остаются действующими.
- [ ] **Step 5 — commit.** `feat(resolution): add compatible execution and failure contracts`.

### Task 2: Стабильная заявка и проверенный контекст

**Files:** Create `app/tools/resolution/__init__.py`, `app/tools/resolution/requests.py`, `tests/resolution_helpers.py`; Test `tests/test_resolution_requests.py`; Modify `app/agents/master/turn.py` только для привязки заявок.

**Interfaces:**
- `bind_message_actions(message: Message, actor_id: str) -> list[ActionRef]` сохраняет индексы исходных действий в `Message.data`, не переписывая другие поля.
- `bind_world_action(campaign_id: str, response_id: str, actor_id: str) -> ActionRef` использует идентичность standing-ответа.
- `ActionContext(ref: ActionRef, verbs: tuple[str, ...], target_ids: tuple[str, ...], place_id: str | None, parsed: bool, affected_in_combat: bool, combat_related: bool, completed_parts: tuple[int, ...], module_data_known: bool, canonical_denial: bool)`; значения получены сервером, не из AdjudicationArgs.
- `load_action_context(ctx: ToolContext, ref: ActionRef) -> ActionContext` загружает сохранённую заявку и актуальные ограничения. Боевой характер проверки оценивается по её источнику, не только scene.mode.
- `action_key(ref: ActionRef) -> str` — SHA-256 канонических полей ссылки, до 64 символов, без turn_id/LLM-call-id.
- Тестовый `prepare_action(ctx, hero_id: str, actions: list[dict]) -> ActionRef` создаёт настоящее Message и привязку; `reload_context(settings, campaign_id: str, fn)` открывает новую сессию через существующие helpers.

- [ ] **Step 1 — failing tests.** `test_ref_survives_reparse_and_new_turn`, `test_wrong_campaign_or_actor_denied`, `test_cancelled_message_denied`, `test_standing_response_ref_is_stable`. Проверять `action_key(ref_before) == action_key(ref_after)` при изменившемся id хода и запрещать чужие источники.
- [ ] **Step 2 — red.** `pytest -n 0 tests/test_resolution_requests.py -q`.
- [ ] **Step 3 — implementation.** Валидировать сообщение, его автора/персонажа и отмену по существующей модели. Непонятная или отсутствующая структурированная заявка не превращается в автоматический `custom`-допуск. Сохранять привязку в транзакции координатора, без нового commit внутри helper.
- [ ] **Step 4 — green.** `pytest -n 0 tests/test_resolution_requests.py tests/test_intent.py -q`; ключ не зависит от повторного запуска.
- [ ] **Step 5 — commit.** `feat(resolution): bind durable action references to existing sources`.

### Task 3: Политика допуска и описания способностей

**Files:** Create `app/core/resolution/policy.py`, `app/tools/resolution/capabilities.py`; Extend contracts.py с ActionContext/CapabilitySpec/Admission; Test `tests/test_resolution_policy.py`.

**Interfaces:**
- `CapabilitySpec(id: str, action_class: Literal['noncombat','combat'], verbs: frozenset[str], operations: frozenset[str], atomic: bool, allow_unsupported: bool, allow_safe_failure: bool)`.
- `Admission(route: Literal['ordinary','repair','fallback','deny'], reason_code: str)`.
- `admit(context: ActionContext, capability: CapabilitySpec, failure: FailureInfo | None) -> Admission` — чистая функция.
- `assess_support(ctx: ToolContext, ref: ActionRef, capability_id: str) -> FailureInfo | None` — серверная проверка, не вывод LLM.

- [ ] **Step 1 — failing tests.** Таблица категорий из спека плюс `test_attack_before_initiative_denied`, `test_mixed_attack_and_social_action_denied`, `test_separate_noncombat_group_allowed`, `test_custom_or_parser_failure_is_not_permission`, `test_unknown_module_data_is_not_free_space`.
  ```python
  assert admit(combat_context, noncombat_capability, unsupported).route == "deny"
  assert admit(free_context, noncombat_capability, unknown).route == "deny"
  assert admit(free_context, noncombat_capability, rule_denial).route == "deny"
  ```
- [ ] **Step 2 — red.** `pytest -n 0 tests/test_resolution_policy.py -q`.
- [ ] **Step 3 — implementation.** Исключить боевые verbs `attack/cast/grapple/shove/dodge/dash/disengage`, боевые проверки и все затронутые стороны боя. `unsupported` допускается только описанием конкретной способности и подтверждённым серверным отсутствием её механической поддержки; отсутствие модели/цели/данных модуля не означает unsupported. Первый набор — `noncombat.interaction`, `creative.neutral_npc`, `standing.response`; последним двум аварийный допуск не нужен. Неподдерживаемый случай возвращает типизированный отказ только после обычной проверки целей/канона; неизвестные случаи закрыты. Весь `custom` автоматически не разрешать.
- [ ] **Step 4 — green.** `pytest -n 0 tests/test_resolution_policy.py tests/test_combat.py -q`; боевые ограничения не меняются.
- [ ] **Step 5 — commit.** `feat(resolution): enforce contextual noncombat admission policy`.

### Task 4: Типизированные последствия и полный откат группы

**Files:** Create `app/tools/resolution/operations.py`, `app/tools/resolution/context.py`, `app/tools/resolution/executor.py`; Extend contracts.py; Test `tests/test_resolution_executor.py`.

**Interfaces:**
- `Consequence` — discriminated union по `kind`; аргументы переиспользуют Pydantic-модели соответствующего инструмента.
- Начальное отображение: `time→advance_time`, `remove_item→take_item`, `drop_item→drop_item`, `move→move`, `enter_room→enter_room`, `reposition→reposition`, `hazard→apply_hazard`, `effect→apply_effect`, `entity_update→update_entity`, `fact→learn_fact`, `deed→record_deed`, `response→resolve_response`, `neutral_npc→spawn_entity`.
- `ResolutionProposal(ref: ActionRef, origin: Literal['normal','creative','fallback'], outcome: Literal['success','partial','failure'], reason: str, attempt_id: str | None, operations: list[Consequence], schema_version=1)`.
- `snapshot_context(ctx: ToolContext) -> ContextSnapshot`, `restore_context(ctx: ToolContext, snapshot: ContextSnapshot) -> None`.
- `execute_resolution(ctx: ToolContext, proposal: ResolutionProposal, admission: Admission) -> ResolutionResult`.

- [ ] **Step 1 — failing tests.** `test_second_operation_failure_rolls_back_first`, `test_rollback_restores_all_context_channels`, `test_arbitrary_tool_or_sql_rejected`, `test_take_item_and_drop_item_keep_distinct_semantics`, `test_hostile_spawn_cannot_hide_in_neutral_operation`. На реальной сессии: время до/после одинаково, предмет на месте, события группы отсутствуют; `closed/changed/outbox/notices/audio/signals/carded/call_key/_first_event` восстановлены.
- [ ] **Step 2 — red.** `pytest -n 0 tests/test_resolution_executor.py -q`.
- [ ] **Step 3 — implementation.** Внешний savepoint вокруг группы; каждый шаг вызывает только `registry.execute` с фиксированным отображением. `ok=false` превращается в отказ группы. Восстанавливать контекст и перечитывать World с сохранением focus/crew после отката. Не использовать ORM deepcopy как замену перечитыванию. Strict-обёртки аргументов Consequence не игнорируют лишние поля, даже если старая модель их игнорировала. Нейтральный NPC получает явный `attitude='neutral'`; никаких произвольных HP/урона. Деньги разрешаются только действующей предметной операцией, если такая форма присутствует в модели; иначе другой представимый исход. Новая репутация не добавляется.
- [ ] **Step 4 — green.** `pytest -n 0 tests/test_resolution_executor.py tests/test_tools.py tests/test_world_objects.py -q`; SQL и сообщения не содержат частичных изменений. Commit хода остаётся у координатора.
- [ ] **Step 5 — commit.** `feat(resolution): execute typed consequences atomically through registry`.

### Task 5: Идемпотентность, гонки и уже выполненные части

**Files:** Modify requests.py/executor.py/contracts.py; Test `tests/test_resolution_replay.py`; существующие Event и транзакционные блокировки без новой таблицы.

**Interfaces:**
- `resolution_receipt(ctx: ToolContext, ref: ActionRef) -> Event | None` ищет Event с `action_key(ref)`.
- `lock_resolution_source(ctx: ToolContext, ref: ActionRef) -> None` сериализует запись по существующему Message или Scene для world-response. PostgreSQL — row lock; SQLite — атомарный UPDATE существующей строки источника без изменения её содержимого, получающий write lock до операций. Busy завершается диагностируемым отказом, не повторным исполнением группы с новыми кубиками.
- Событие `resolve_action` содержит версию, fingerprint предложения, origin, исход и id дочерних событий. Дочерние ключи выводятся из ключа заявки и индекса операции.

- [ ] **Step 1 — failing tests.** `test_replay_after_new_session_does_not_charge_again`, `test_changed_proposal_returns_original_receipt`, `test_concurrent_same_action_runs_hooks_once`, `test_confirmed_roll_not_repeated`, `test_unknown_partial_completion_denied`, `test_sqlite_busy_does_not_reroll_group`. Проверки: одна receipt, одна цена, один поступок standing, тот же результат броска. Гонка запускается двумя настоящими сессиями; не симулировать её моками.
- [ ] **Step 2 — red.** `pytest -n 0 tests/test_resolution_replay.py -q`; PostgreSQL-сценарий дополнительно запускается с TEST_DATABASE_URL.
- [ ] **Step 3 — implementation.** Сначала блокировка источника и проверка receipt, затем актуальные предусловия, группа и receipt в одной транзакции. Не гасить IntegrityError до отката нужного savepoint. После гонки читать реально сохранённый результат. Сохранять/восстанавливать `_first_event` внешнего инструмента при дочерних registry.execute. Выполненные части и броски загружать по заявке, не по последнему инструменту всего хода. Неизвестное состояние не переисполнять.
- [ ] **Step 4 — green.** `pytest -n 0 tests/test_resolution_replay.py tests/test_resolution_executor.py -q` на обеих базах; существующий боевой action_plan сохраняет движение при отказе атаки.
- [ ] **Step 5 — commit.** `fix(resolution): make grouped decisions replay and concurrency safe`.

### Task 6: Инструмент внебоевого решения и интеграция фазы решений

**Files:** Create `app/tools/master/adjudication.py`, `app/agents/master/resolution.py`; Modify master/__init__.py, common.py, turn.py, contracts.py, registry.py и resolution/context.py; Test `tests/test_adjudication.py`, `tests/test_master.py`.

**Interfaces:**
- `record_attempt(ctx: ToolContext, ref: ActionRef, capability_id: str, result: ResolutionResult) -> str` сохраняет версионированную запись в trace текущего MasterTurn без потери calls/place.
- `eligible_adjudications(ctx: ToolContext) -> list[dict]` возвращает только разрешённые ссылки текущих заявок.
- `AdjudicationArgs(proposal: ResolutionProposal)`; `adjudicate_action(ctx: ToolContext, args: AdjudicationArgs) -> dict` — нативный зарегистрированный tool.
- `resolution_prompt(ctx: ToolContext) -> str` сообщает модели допуск и варианты, не сырые исключения.
- `ToolContext.resolved_actions: set[str]` хранит закрытые action_key текущего контекста; durable-источник — receipt. `mark_resolved(ctx: ToolContext, ref: ActionRef) -> None` добавляет геройский id в прежний ctx.closed только после разрешения всех требуемых частей его заявки. Snapshot Task 4 расширяется этим полем.

- [ ] **Step 1 — failing tests.** `test_allowed_failure_can_be_resolved_with_price`, `test_forged_or_cross_turn_attempt_denied`, `test_successful_retry_removes_fallback_permission`, `test_no_tool_call_does_not_grant_fallback`, `test_rule_denial_and_real_roll_failure_do_not_grant_permission`, `test_fallback_failure_cannot_fallback_again`, `test_resolving_one_part_does_not_close_other_parts`, `test_group_cannot_exceed_remaining_call_budget`.
- [ ] **Step 2 — red.** `pytest -n 0 tests/test_adjudication.py -q`; scripted LLM-тест показывает, что без admission инструмент не исполняет предложение.
- [ ] **Step 3 — implementation.** Фаза решений сначала исправляет обычный вызов максимум один раз на заявку, затем предлагает допустимый фолбек. Grant формируется сервером, принадлежит заявке и актуальной попытке; LLM не передаёт allow=true. Поддержку внебоевого взаимодействия оценивает Task 3; неизвестное отсутствие поддержки не выдумывается. Инструмент регистрируется с closes=False и использует mark_resolved, не закрывая другие части. MAX_CALLS=8/MAX_STEPS=12 не повышать; перед группой проверять оставшийся бюджет. Каждая дочерняя операция расходует одну попытку, оболочка не считается второй раз; группа без операций расходует одну. Не начинать превышающую бюджет группу. В final trace объединять записи, а не затирать их. При безопасно обработанном отказе сохранять диагностику обычным commit; при падении БД — серверный log без обещания записи.
- [ ] **Step 4 — green.** `pytest -n 0 tests/test_adjudication.py tests/test_master.py tests/test_combat.py -q`; исходная ошибка видна вместе с решением, боевые заявки остаются вне инструмента.
- [ ] **Step 5 — commit.** `feat(master): add server-admitted noncombat adjudication`.

### Task 7: Подтверждённый итог, журнал и защита публичной фазы

**Files:** Modify `app/agents/master/outcomes.py`, narration.py, turn.py, `app/agents/prompts/narrate.j2`, `app/core/master_log.py`; Test `tests/test_resolution_visibility.py`, tests/test_master.py, tests/test_memory.py.

**Interfaces:**
- `resolved_action_outcomes(ctx: ToolContext) -> dict[str, ResolutionResult]` читает подтверждённые события, ключ — action_key.
- `public_resolution(ctx: ToolContext, result: ResolutionResult, viewer_ids: set[str]) -> dict` использует действующую видимость.
- Дополнительные scalar-поля существующего журнального вызова: request_key, failure_code, failure_category, resolution_origin, resolution_outcome; прежняя форма API журнала сохраняется.

- [ ] **Step 1 — failing tests.** `test_fallback_success_does_not_mask_other_failed_transition`, `test_no_public_success_before_commit`, `test_secret_failure_not_in_narration_voice_or_summary`, `test_old_trace_is_readable`, `test_rolled_back_proposal_not_remembered`, `test_failed_turn_keeps_adjudication_diagnostics`. На смешанном ходе одна заявка разрешена, другой переход остаётся неуспешным и герой не телепортируется.
- [ ] **Step 2 — red.** `pytest -n 0 tests/test_resolution_visibility.py -q`.
- [ ] **Step 3 — implementation.** Сопоставлять попытки с заявками, не считать любой resolve_action исправлением последнего перехода. Генерировать черновик при необходимости, но не стримить и не публиковать новый значимый исход до commit. Для старых trace без action_key сохранить существующую консервативную защиту. В журнал выводить безопасные scalar-поля через существующий redaction; полные технические аргументы не отправлять клиенту. Память использует факты опубликованных результатов, не trace ошибок.
- [ ] **Step 4 — green.** `pytest -n 0 tests/test_resolution_visibility.py tests/test_master.py tests/test_memory.py -q`; отдельно проверить повторное подключение и карту из текущего мира.
- [ ] **Step 5 — commit.** `fix(master): narrate and expose only committed scoped outcomes`.

**Checkpoint:** внебоевой фолбек готов к отдельной поставке после полной проверки Task 11. Следующие задачи не являются условием его работоспособности.

### Task 8: Нестандартные действия, эмоции и темп без новых правил

**Files:** Create `app/agents/master/creative.py`; Modify `app/agents/prompts/master_system.j2`, narrate.j2, voice_line.j2, master/resolution.py; Test `tests/test_master_creative.py`, tests/test_master_temper.py, tests/test_rhythm.py.

**Interfaces:**
- `creative_context(ctx: ToolContext, ref: ActionRef | None) -> dict` содержит возможности и ограничения из актуального мира/модуля, текущую персону и реальные результаты; не raw trace.
- `creative_note(context: dict) -> str` — небольшая подсказка для существующего decision/narration потока; отдельного LLM-агента нет.

- [ ] **Step 1 — failing tests.** `test_nonstandard_social_request_uses_supported_check`, `test_failed_bribe_can_offer_new_opportunity_without_success`, `test_plain_success_needs_no_complication`, `test_combat_flavor_changes_no_mechanics`, `test_voice_matches_existing_persona_and_result`.
- [ ] **Step 2 — red.** `pytest -n 0 tests/test_master_creative.py -q`; scripted LLM нарушает границу результата, серверная проверка должна это обнаружить.
- [ ] **Step 3 — implementation.** Промпт разрешает нестандартный способ и трактовку без переигрывания результата, сохраняет волю героя и соразмерность цены. В бою — только подача. Использовать текущие persona/pacing и фиксированные результаты, без дополнительного запроса для каждой реплики. Проверки строятся на фактических инструментах/побочных эффектах, не точном художественном тексте.
- [ ] **Step 4 — green.** `pytest -n 0 tests/test_master_creative.py tests/test_master_temper.py tests/test_rhythm.py -q`; обычный успех и пустая комната остаются допустимыми.
- [ ] **Step 5 — commit.** `feat(master): ground creative interpretation in existing rules and persona`.

### Task 9: Значимые новые NPC и побочные истории

**Files:** Extend capabilities.py/operations.py/creative.py; Modify `app/tools/master/entities.py`, knowledge.py и `app/tools/plot.py` только при необходимости совместимого адаптера; Test `tests/test_master_creative_world.py`, tests/test_adventure.py, tests/test_world_generation.py.

**Interfaces:**
- `creative_opportunities(ctx: ToolContext) -> list[CreativeOpportunity]` возвращает привязанные к месту варианты, запреты модуля и существующие NPC/наброски.
- `validate_creative_proposal(ctx: ToolContext, proposal: ResolutionProposal) -> Admission` не принимает отсутствие загруженных данных за разрешение.
- `StoryHookOp(subject_id: str, character_ids: list[str], fact: str)` → существующий `learn_fact`; предложение, отказ и согласие — отдельные факты. Согласие требует сохранённой заявки игрока с этим намерением.

- [ ] **Step 1 — failing tests.** `test_neutral_npc_registered_before_narration`, `test_existing_npc_or_sketch_reused`, `test_empty_module_room_stays_empty`, `test_unknown_module_data_denies_creation`, `test_story_offer_is_not_player_acceptance`, `test_hook_persists_after_reload`.
- [ ] **Step 2 — red.** `pytest -n 0 tests/test_master_creative_world.py -q`.
- [ ] **Step 3 — implementation.** Публичный NPC — существующий шаблон, место и явное neutral/friendly, без произвольного боевого блока. Набросок — develop, новый NPC — spawn_entity. Если канон не допускает добавление либо данных недостаточно, предложить существующую возможность, не спавнить. Побочную линию хранить через субъект, известные факты/события и защищённый существующий сюжет для секретов; не вводить дублирующий quest-реестр. Если подходящего защищённого представления нет, не создавать несохраняемый тайный мотив. Не использовать публичную description для секретов. Не создавать новый проход/ключ ради удобного сюжета.
- [ ] **Step 4 — green.** `pytest -n 0 tests/test_master_creative_world.py tests/test_adventure.py tests/test_world_generation.py -q`; в новом контексте существует тот же NPC, предложение не считается принятым.
- [ ] **Step 5 — commit.** `feat(master): persist bounded creative NPCs and story opportunities`.

### Task 10: Поступки, отложенные ответы и память групп

**Files:** Extend capabilities.py/operations.py/requests.py; Modify `app/tools/standing.py`, master/creative.py, outcomes.py; Test `tests/test_resolution_standing.py`, tests/test_standing.py, tests/test_memory.py.

**Interfaces:**
- `standing_resolution(ctx: ToolContext, response_id: str, operations: list[Consequence], reason: str) -> ResolutionProposal` использует world ActionRef и capability `standing.response`.
- Операция `response` должна быть последней: после применённой благодарности/мести, в той же группе. `record_deed` получает связь с исходной заявкой в Event payload, не новые поля репутации.

- [ ] **Step 1 — failing tests.** `test_ordinary_and_fallback_count_deed_once`, `test_failed_gift_does_not_close_response`, `test_response_replay_does_not_give_second_gift`, `test_secret_deed_does_not_leak_to_other_party`, `test_reverted_deed_not_used_for_new_story`.
- [ ] **Step 2 — red.** `pytest -n 0 tests/test_resolution_standing.py -q`.
- [ ] **Step 3 — implementation.** Использовать существующие standing/fortune часы и события. Инициатива мира создаёт предложение, не цепочку автоматических вызовов. Возврат последствия проверяет существование NPC, место и круг знания. Откат синхронизирует standing и связанные факты через existing inverse. При открытии боя прекратить небоевой фолбек; дальнейшие действия идут обычным боевым маршрутом. Настройку random_events уважать.
- [ ] **Step 4 — green.** `pytest -n 0 tests/test_resolution_standing.py tests/test_standing.py tests/test_memory.py -q`; ответ не закрыт до фактического результата.
- [ ] **Step 5 — commit.** `feat(master): reuse standing responses as durable creative consequences`.

### Task 11: Сквозная приёмка и документация расширения

**Files:** Create `tests/test_resolution_end_to_end.py`, `docs/master-resolution.md`; Modify docs/README.md и сам план для отметок выполнения. API/TS-файлы — только если реальные внешние схемы изменились.

**Interfaces:** Документировать добавление способности: контракт, допуск, операции, регистрация и тесты. Привести пример neutral_npc без нового обработчика LLM/карты/памяти. Объяснить чтение ошибки и результата в существующем журнале.

- [ ] **Step 1 — failing tests.** Полный сценарий «внебоевая ошибка → решение с ценой → сохранение → reconnect → отложенный ответ → повтор заявки». Также «последствие отказало», «база потеряна», «атака в free», «выполненный бросок провален», «два источника одного героя», «тайна другой группы». Проверки: идентичность NPC, карта/сцена, инвентарь, standing, журнал, отсутствие дублирования и вымышленного успеха.
- [ ] **Step 2 — red.** `pytest -n 0 tests/test_resolution_end_to_end.py -q`; перечислить реальные причины падений, не ослаблять проверки.
- [ ] **Step 3 — implementation.** Исправить только обнаруженные интеграционные пробелы; написать документацию расширения и диагностики. Новых пользовательских функций в приёмке не добавлять.
- [ ] **Step 4 — green и полная проверка.** Запустить приведённые ниже команды и записать точные counts/exit codes. Существующие DeprecationWarning Alembic отметить отдельно от ошибок; PostgreSQL-пропуск SQLite-only миграционного теста не скрывать.
- [ ] **Step 5 — commit.** `test(resolution): verify replay persistence visibility and extension contract`. Перед push — review изменений; не объявлять GitHub CI зелёным только по локальным тестам.

## Команды проверки

Из корня checkout с его активированным Python-окружением:

```bash
ruff check .
ruff format --check .
pytest -q -n 4
python -m app.content validate content/dnd5e-srd --strict
```

PostgreSQL — тот же `pgvector/pgvector:pg16`, что в `.github/workflows/ci.yml`;
использовать отдельную тестовую базу, никогда не базу кампаний:

```bash
DATABASE_URL=postgresql+asyncpg://taleforge:taleforge@127.0.0.1:55432/taleforge_test alembic upgrade head
DATABASE_URL=postgresql+asyncpg://taleforge:taleforge@127.0.0.1:55432/taleforge_test alembic check
DATABASE_URL=postgresql+asyncpg://taleforge:taleforge@127.0.0.1:55432/taleforge_test alembic downgrade base
TEST_DATABASE_URL=postgresql+asyncpg://taleforge:taleforge@127.0.0.1:55432/taleforge_test pytest -q -n 4
```

Существующие клиентские проверки из `web`: `npm run gen:api` с проверкой diff api.gen.ts,
`npm test`, `npm run build`. Если backend-only изменения не меняют внешний контракт,
генерация не должна создавать diff. Проверить, что каталог/замки/версия SRD не изменены.

## Критерий завершения и handoff

### Выполнение

Задачи 1–10 реализованы в `feat/master-resolution`; сквозная приёмка и review
задачи 11 выполняются. Детальные чекбоксы выше оставлены как исходная матрица
приёмки: некоторые сценарии объединены в параметризованные и интеграционные
тесты, а не созданы отдельными функциями с исходными именами.

Дополнительные регрессии при интеграции: сохранение focus/crew после отказа
реестра; актуальный мир у конкурентного повторного вызова; запрет creative как
обхода rule_denial; только одно исправление аргументов; сохранение дочерней
диагностики после отката группы и failed turn; закрытый факт внутри общей группы;
SQLite busy без последствий и без списания кубиков.

Адаптер общего `unsupported` намеренно не выдаёт разрешения без конкретной
серверной механики. Event-source не разрешён без проверенного адаптера. Это
защитные ограничения первого выпуска, а не эвристики распознавания текста.
Проверки миграций выполняются в отдельной одноразовой базе
`taleforge_resolution_migrations`, поскольку pytest создаёт схему основной
тестовой базы через metadata, без alembic-version.

Результат — прошедшие сценарии общего механизма, отдельно работающий внебоевой
фолбек и творческие возможности без рассинхрона текста и мира. Ошибки и
неподдерживаемые случаи остаются видимыми, правила боя не обходятся.

Этот план передаётся пользователю на review и выбор способа исполнения.
Нативно: основной агент выполняет задачи последовательно; с делегированием:
отдельные исполнители и reviewers по задачам после явного выбора пользователя.
Рекомендуется нативный путь для тесно связанных контрактов, с независимым review
перед интеграцией. До одобрения плана продуктовый код не меняется.
