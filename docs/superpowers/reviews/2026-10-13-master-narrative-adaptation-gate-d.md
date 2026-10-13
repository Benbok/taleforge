# Narrative Adaptation: отчёт повторной приёмки Gate D

Дата: 2026-10-13. F12 завершён: полные SQLite и PostgreSQL прогоны зелёные.
Ветка: `feat/narrative-adaptation`; слияние с `main` не выполнялось.
База исходного ревью: `f81c3a3`. Проверенный код:
`413eb8b` (fix(narrative): show the master the adapt_story operation format).
Финальный коммит приёмки содержит только документацию поверх этого кода.

Полные серверные прогоны выполнены в отдельном detached worktree на
`413eb8b`, без незакоммиченных изменений рабочего дерева.

## Проверки

| Проверка | Результат |
| --- | --- |
| SQLite, весь pytest, xdist 4, `--timeout 300` | 1024 passed, 3 skipped, 0 failed, 405.52 s |
| PostgreSQL 16, весь pytest, xdist 4, `--timeout 300` | 1025 passed, 2 skipped, 0 failed, 870.48 s; workers завершились штатно |
| PostgreSQL migrations | upgrade head (0023), check, downgrade base, upgrade head: PASS |
| Ruff check / format --check | PASS по всему дереву, включая Markdown (481 files) |
| `python -m app.contract --check` | PASS, сохранённый контракт соответствует серверу |
| `python -m app.content validate content/dnd5e-srd --strict` | PASS |
| `python tools/eval_narrative.py` | 8/8 scripted scenarios PASS |
| Клиент: vitest | 38 файлов, 202 теста PASS |
| Клиент: `npm run gen:api` и diff generated-файлов | PASS, нового diff нет |
| Клиент: `npm run build` | PASS; предупреждения о размере chunk и сочетании static/dynamic import `api.ts` |

С `82e71ad` (последняя регенерация контракта) в `app/api`, `web` и `alembic`
менялось только форматирование двух файлов API; повторный `contract --check`
и gen:api подтвердили отсутствие изменений контракта.

Окружение: Windows, Python 3.12.13, pytest 9.1.1, pytest-xdist 3.8.0,
pytest-timeout 2.4.0, Node 24.18.0, ruff 0.16.9, PostgreSQL 16.15
(`postgres:16-alpine`, временный контейнер `tf-gate-d-pg`). Production pooling
не отключался: `NullPool` используется только тестовой фикстурой при наличии
`TEST_DATABASE_URL`.

Пропуски SQLite: три теста настоящих гонок блокировок
(`test_narrative_replay::test_concurrent_two_sessions_race`, две гонки
`test_resolution_replay`) требуют PostgreSQL — на PostgreSQL они прошли.
Пропуски PostgreSQL: `test_resolution_busy` (SQLite locking behavior),
`test_tails` (блокировка файла SQLite).

## Закрытие промежуточных находок

- `first_slice` на PostgreSQL (`be30787`): фоновое вступление кампании
  публиковало повествование в уже открытый сокет; `act()` принимал его за ответ
  на первое действие, сценарные ответы хода сдвигались во второй ход, и
  проверяемый prompt предшествовал адаптации. Дефекта продукта нет; тест ждёт
  завершения фоновых задач мастера. Та же гонка объясняла редкое мерцание на SQLite.
- G (`403070a`): живой режиссёр был фактически слеп — во входе не было открытых
  будущих ситуаций и фронтов, доказательства шли без содержания, а схема
  инструмента описывала операции как произвольные объекты. Сценарные тесты
  этого не ловили, потому что ответ модели был написан вручную. Теперь снимок
  несёт ограниченные `situations`, вход содержит адреса и содержание, схема
  строится из контрактов операций без `$ref`.
- H (`403070a`): бюджет 6000 «токенов» считался в символах, и реалистичный
  снимок молча превращался в `no_change` без вызова модели.
- G2 (`413eb8b`): мастер в сцене видел только имена операций `adapt_story`;
  подсказка содержит образцы аргументов, тест сверяет их с контрактами.

Качество живого авторского продолжения (реальная модель, latency, стоимость)
по-прежнему не оценивалось: G/G2 устраняют структурную невозможность валидного
ответа, а не доказывают качество текста.

## Соответствие замечаний исправлениям

Имена ниже относятся к тестам в каталоге `tests/`; полный набор выполняется
при общей приёмке. Таблица связывает первоначальные замечания с изменениями,
но не заменяет отдельное ревью всей исходной реализации.

| Замечание | Исправление / коммит | Регрессионное покрытие |
| --- | --- | --- |
| R1: внутренние apply доступны модели | F1, `c68c0db`: internal schema filtering и server grant | `test_narrative_tool_boundary`: `test_internal_tools_not_exposed`, `test_direct_internal_call_denied` |
| R2: вложенные ссылки другой кампании | F1, `c68c0db`: рекурсивная граница и контекстная campaign | `test_nested_foreign_campaign_rejected` |
| R3: непроверенные основания | F2, `e1b08d7`; A, `fb6a7d8` / `98ead38`: только явный `current` | `test_narrative_context::test_missing_or_foreign_evidence_denied`; `test_narrative_master::test_adapt_story_binds_current_message_marker`, `test_empty_message_id_is_not_current` |
| R4: policy/module не ограничивают операции | F2, `e1b08d7`: пересечение разрешений и проверка mutability | `test_narrative_policy::test_empty_policy_denies_operation`, `test_module_disallows_operation`; `test_narrative_context::test_existing_fact_does_not_imply_mutability` |
| R5: переписывается закреплённая история | F3, `f325f78`: admission и реальные write guards | `test_narrative_drafts::test_add_cannot_replace_committed_history`, `test_revise_committed_fact_in_context_denied` |
| R6: нить принимается без выбора игрока | F4, `0c523ba`; B, `98ead38`: подтверждённая заявка и предметная связь | `test_narrative_threads::test_interest_cannot_accept_thread`; `test_narrative_review_fixes::test_master_event_cannot_activate_thread`, `test_persisted_player_action_controls_thread_activation` |
| R7: зависимости не закрепляются транзитивно | F5, `0209b62` | `test_narrative_commitments::test_record_commitments_transitive_dependencies`, `test_record_commitments_violations_atomic_rollback` |
| R8: пространственные refs отсутствуют | F5, `0209b62`: точные used_fact_refs и зависимости | `test_narrative_facts::test_spatial_producer_seals_only_used_fact_and_dependencies` |
| R9: overrides не доходят до читателей | F6, `d9df5ec`: единое чтение actor/module | `test_narrative_canon_readers::test_role_and_motive_reach_master_prompt_and_hero_card`, `test_module_override_reaches_book_reader_and_stays_in_its_campaign` |
| R10: режиссёр не собран в startup | F9, `e73eda1`: create_app lifecycle; G/H `403070a`: полноценный вход живого режиссёра | `test_narrative_startup::test_act_close_reaches_receipt_and_changes_future_node`, `test_restart_applies_prepared_draft_without_new_author_call` |
| R11: claim теряет evidence/audience/focus | F7, `2654863`: полный сериализуемый контекст | `test_narrative_jobs::test_claim_carries_evidence_audience_focus`, `test_enqueue_claim_roundtrip_preserves_evidence` |
| R12: предложение B завершает job A | F8, `cc36a4a`: связь claim/source/lease | `test_narrative_jobs::test_applied_proposal_strictly_belongs_to_claimed_job`, `test_late_worker_cannot_write_world_on_expired_lease` |
| R13: boundary kinds делят identity | F7, `2654863`: kind входит в ключ границы | `test_narrative_jobs::test_boundary_kinds_produce_distinct_receipt_sources` |
| R14: неполный durable workflow | F8–F9, `cc36a4a` / `e73eda1`; F12, `cbe27c6`: parent receipt | `test_narrative_jobs::test_no_change_creates_single_event_and_receipt_event_id`, `test_recording_bus_publishes_only_after_successful_commit`, `test_finish_links_parent_receipt_instead_of_first_child`; `test_narrative_service` stale/correction cases |
| R15: ошибка прерывает весь batch | F8, `cc36a4a`; C, `98ead38`: стадии сбоя и безопасные reason codes | `test_narrative_service::test_batch_isolates_author_error_and_allows_subsequent_campaign`; `test_narrative_review_fixes::test_snapshot_failure_releases_sql_job_before_lease_expiry`, `test_transient_finish_failure_preserves_committed_result` |
| R16: reveal_fact не вызывает learn_fact корректно | F6, `d9df5ec`: subject, fact и аудитория | `test_narrative_canon_readers::test_reveal_fact_teaches_exact_heroes_and_seals_exact_ref`, `test_reveal_fact_rejects_foreign_audience_and_stale_ref` |
| R17: learn_fact закрепляет лишние секреты | F5, `0209b62`: только точные использованные refs | `test_narrative_commitments::test_learn_fact_seals_only_exact_used_refs` |
| R18: бюджеты постоянны на всю кампанию | F4, `0c523ba`: scene/session identity и отдельная future preparation | `test_narrative_budget_scope::test_new_scene_gets_fresh_budget_3`, `test_new_session_gets_fresh_budget_12`, `test_retry_does_not_reset_budget_counters` |
| R19: individual front clocks игнорируются | F10, `d73e3e9`: отдельные period/clock_at/remainder | `test_narrative_fronts::test_explicit_fronts_have_independent_periods_and_persist_remainder`, `test_explicit_zero_clock_survives_global_initialization_and_view` |
| R20: scale не проверяет реальную кампанию/общий предел | F11, `4a8db4c`; F12, `cbe27c6`: PG EXPLAIN | `test_narrative_scale::test_scale_bounded_queries_under_10k_history` |

## Дополнительные исправления, обнаруженные F12

- `ac8e51b`: тестовое повторное использование asyncpg-соединений между event loop
  приводило к ошибкам и зависаниям. Регрессия `test_db_test_loops` воспроизводит
  чтение одного app engine из разных циклов; тестовый `NullPool` устраняет причину.
- `cbe27c6`: `NarrativeWork.receipt_event_id` теперь указывает на родительскую
  квитанцию `adapt_story` с matching campaign, source-key и возвращёнными event IDs.
  Регрессия сначала обнаружила ссылку на дочернее событие, затем прошла.
- PG race действительно запускает две сессии с сохранённым основанием и проверяет
  ровно один `applied` и один `stale`; прежний SQLite skip скрывал неверный вызов helper.
- Scale EXPLAIN использует синтаксис своей БД; SQLite write-probe в `test_tails`
  работает в отдельном потоке, позволяя независимой presence-транзакции завершиться.
  Проверка отсутствия write lock во время model review сохранена.

## Сквозной сценарий и границы доказательства

`test_narrative_gate_d::test_alliance_future_job_next_scene_and_reconnect`
использует настоящий `create_app`, tools, durable jobs, storage, startup service
и WebSocket. Подменён только LLM-порт. Союз меняет намерение антагониста;
закрытие акта создаёт future job; режиссёр меняет будущий узел; последующие
ходы используют обновлённый план; новый экземпляр приложения и reconnect
сохраняют сцену, сообщения и квитанцию без повторного вызова режиссёра.
`no_change`, ошибки, stale lease и восстановление сохранённого draft также
проверяются отдельными startup/jobs/service/review-fixes тестами.

Это проверка нового экземпляра приложения и переподключения, не принудительное
завершение OS-процесса. Scripted 8/8 измеряет структурные инварианты;
качество живого авторского продолжения и реальные provider latency/cost здесь
не оценивались. Ограниченные запросы на 10 000 событий не являются общей
нагрузочной сертификацией приложения.

При сверке документации обнаружена ещё одна граница исходного плана:
`advance_front` имеет DTO/адаптер, но отсутствует в `ACTIVE_OPERATION_KINDS`.
Автоматические часы `tick_fronts` покрыты тестами и работают; продвижение
фронта предложением LLM не объявляется реализованным. F12 не расширяет
allowlist без отдельной проверки требований и оснований.

Независимое ревью F12 (`44622b6..cbe27c6`) не обнаружило Critical/Important.
Оставлены два небольших улучшения тестов: выбирать исходный work по ID вместо
первого элемента списка; добавить прямые negative cases поиска parent receipt
с чужими campaign/source-key. Основные границы покрывает общий набор тестов.
