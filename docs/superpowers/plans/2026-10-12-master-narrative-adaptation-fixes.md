# Narrative Adaptation Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Закрыть подтверждённые ошибки ревью адаптации сюжета и провести
приёмку Gate D по реальным пользовательским и фоновым путям исполнения.

**Architecture:** Сохранить существующие порты, доменное ядро, реестр и world guard.
Исправить границы доверия и подключение уже написанных компонентов, а не создавать
второй исполнитель, вторую очередь или ещё одну копию канона.

**Tech Stack:** Python/Pydantic/SQLAlchemy/Alembic, SQLite/PostgreSQL,
pytest/xdist, Jinja2, существующий LLM Protocol и клиент React/TypeScript.
Новых production-зависимостей не требуется.

**Spec:** [Спек адаптации](../specs/2026-10-12-master-narrative-adaptation-design.md)
и [исходный план Tasks 1–21](2026-10-12-master-narrative-adaptation.md).

База ревью: feat/narrative-adaptation, коммит f81c3a3.
План подготовлен для самостоятельной реализации пользователем.
Приведённые проверки являются требованиями будущего прогона; исправления
ещё не внесены. Слияние с main остаётся отдельным действием.

## Global Constraints

- Сохранить интерфейс «модель предлагает — сервер проверяет — инструменты применяют».
- Не считать скрытый или незагруженный факт свободным.
- Не переписывать committed/anchor, исторические результаты и выбор героев.
- Кампания определяется серверным контекстом, не вложенной ссылкой модели.
- Скрытие инструмента из схемы не заменяет серверную проверку права вызова.
- Доменное ядро не импортирует DB/tools/agents; ORM и сеть остаются в адаптерах.
- Ни транзакция, ни campaign lock не удерживаются во время LLM-вызова.
- Квитанция, изменение мира, бюджеты и состояние задания согласованы при commit.
- Фоновое изменение публикуется после commit и с действующей аудиторией.
- Лимиты: 8 operations, 8 grounds, 3 новизны на сцену, 12 на сессию,
  5 offered+active нитей группе, 2 LLM-вызова, 1 resnapshot после stale,
  16 зависимостей/64 посещённых факта, контекст 50/80/20 и 6000 токенов.
- Не включать в исправления независимые изменения интерфейса и аудио.
  При исполнении сверить git status и не коммитить чужое staged-содержимое.
- Для миграций использовать отдельную тестовую БД; не проектный taleforge.db
  и не действующий PostgreSQL приложения.

## Review Focus

1. Модель вызывает внутренний адаптер напрямую, в том числе в strict:
   отказ должен происходить до записи — F1.
2. Корректный внешний source содержит чужую или выдуманную вложенную ссылку:
   сервер отклоняет её независимо от summary — F1–F2.
3. Проверка домена существует, но реальный инструмент её не вызывает:
   регрессия проверяет сохранённую БД, а не только чистую функцию — F3–F6.
4. Пока автор думает, lease/тайна/политика изменились:
   поздний worker не фиксирует мир и не завершает чужое задание — F7–F9.
5. Два пути применяют одну инициативу, и отряд разделён:
   одна квитанция, одна цена, правильная публикация без чужих секретов — F4, F8, F12.

## Результат текущего ревью и проверки

Подтверждённые блокеры перечислены ниже. Существующие narrative-тесты и
8 scripted-эталонов не доказывают готовность всего пользовательского пути:
часть тестов вызывает вспомогательные функции напрямую, минуя интеграцию.

| Проверка | Что фактически проверено |
| --- | --- |
| База | Ветка и коммит f81c3a3 существуют; коммит не входит в main |
| Scripted quality | 8/8 PASS; это проверка эталонов, не качество реального LLM |
| Узкая проверка | Contracts + quality + scale: 15 passed |
| Ruff | 22 ошибки; format --check: 38 файлов требуют форматирования |
| Клиент | 36 файлов / 196 тестов PASS; build PASS в рабочем дереве с текущими UI-правками |
| Контракты/контент | app.contract --check PASS; SRD strict validate PASS, 857 записей |
| Полный pytest | Собрано 914 тестов; замечено падение; прогон остановлен по запросу пользователя, полного итога нет |
| PostgreSQL/миграции | Не выполнены; временный контейнер после смены задачи остановлен и удалён |

Повторное ревью должно использовать конкретный исправленный commit. Клиентские
проверки рабочего дерева не следует выдавать за проверки чистого f81c3a3.

## Реестр подтверждённых дефектов

| ID | Приоритет | Дефект | Исправление |
| --- | --- | --- | --- |
| R1 | P1 | Шесть внутренних apply_* инструментов доступны модели через decision_tools | F1 |
| R2 | P1 | Вложенный fact.ref.campaign_id позволяет писать в другую кампанию | F1 |
| R3 | P1 | Message/standing/time evidence объявляется applied без чтения источника | F2 |
| R4 | P1 | Разрешения модели/модуля не ограничивают операции; список mutable выводится из наличия фактов | F2 |
| R5 | P1 | add_campaign_fact заменяет committed historical факт и понижает freedom | F3 |
| R6 | P1 | Статус нити записывается напрямую, включая resolved -> active и принятие без игрока | F4 |
| R7 | P1 | record_commitments не закрепляет depends_on; чистая seal_facts не подключена | F5 |
| R8 | P1 | Пространственный путь создаёт FactRef без snapshot_ref и SnapshotRef(kind=turn) | F5 |
| R9 | P1 | develop_actor_role/модульные overrides не достигают реальных читателей World/adventure | F6 |
| R10 | P1 | Режиссёр не создаётся при startup, narrative_preparer остаётся None | F9 |
| R11 | P1 | WorkClaim теряет evidence/audience/focus, автор получает пустое основание | F7 |
| R12 | P2 | Immediate apply может применить proposal B и завершить job A | F8 |
| R13 | P2 | Разные boundary kinds с одним source_id получают одинаковую receipt identity | F7 |
| R14 | P2 | Нет публикации фоновых effects, no_change receipt, correction/resnapshot/heartbeat | F8–F9 |
| R15 | P2 | Ошибка одного автора прерывает весь run_due batch | F8 |
| R16 | P2 | reveal_fact выдаёт learn_fact аргументы без subject_id/fact | F6 |
| R17 | P2 | learn_fact закрепляет все свойства субъекта, включая несвязанные скрытые | F5 |
| R18 | P2 | Бюджеты scene/session — постоянные неразделённые счётчики кампании | F4 |
| R19 | P2 | Явные period/clock_at фронта игнорируются | F10 |
| R20 | P2 | Scale-тест проверяет другую кампанию и не проверяет совокупный предел 80 записей | F11 |

Ориентиры строк ниже относятся к f81c3a3; после исправлений искать по функциям.
Все задачи завершаются отдельным коммитом только своих файлов.
Новые regression tests сначала должны воспроизводить дефект на базе ревью.

## Порядок реализации

F1 → F2 → F3/F4 → F5 → F6 → F7 → F8 → F9 → F10 → F11 → F12.
До исправления границ доверия не следует включать адаптацию новым кампаниям
по умолчанию. Существующие принятые данные не удалять: временное ограничение
новых предложений не должно менять отображаемый мир.

### F1. Закрыть внутренний обход допуска и границу кампании

**Files:** app/tools/registry.py, operation_group.py,
app/agents/master/common.py, app/tools/narrative/tools.py, compiler.py, executor.py.
**Tests:** tests/test_narrative_access.py; новый tests/test_narrative_tool_boundary.py.

**Основание:** common.py:64 перечисляет зарегистрированные apply_* инструменты;
tools.py:35 использует args.campaign_id для поиска и записи.

**Решение:** в ToolSpec добавить признак internal, default=False. Все narrative
apply_* имеют internal=True и отсутствуют в публичных/LLM-схемах.
Registry.execute для internal требует отдельный server-issued InternalGrant,
переданный вне JSON-аргументов. Grant выдан после admission, ограничен кампанией,
конкретными compiled calls и временем жизни одной группы. Его нельзя получить
из реплики, trace модели или произвольного tool-name.
Все адаптеры используют ctx.campaign.id; несовпадающий args.campaign_id —
отказ до flush, а не молчаливое перенаправление.

- [x] Написать test_internal_tools_not_exposed и test_direct_internal_call_denied:
  все 6 apply_* отсутствуют в decision_tools, прямой execute не меняет БД даже в strict.
- [x] Добавить test_nested_foreign_campaign_rejected: предложение A с фактом B
  отклоняется; обе кампании, world_revision и журнал B неизменны.
- [x] Запустить новые тесты до исправления и сохранить подтверждённый FAIL.
- [x] Реализовать internal-проверку на стороне исполнения и рекурсивную проверку
  всех campaign refs; grant выдавать только общему принятому runner.
- [x] Запустить новые тесты и resolution executor/replay/visibility; коммит
  fix(narrative): enforce internal tool and campaign boundaries.

### F2. Проверять реальные основания и разрешения

**Files:** app/tools/narrative/context.py, reader.py, sources.py;
app/core/narrative/policy.py; app/core/modules.py.
**Tests:** tests/test_narrative_context.py, policy.py, module_permissions.py.

**Основание:** context.py:67 синтезирует applied для любого не-event источника;
context.py:168 выдаёт mutable всем загруженным фактам. Policy около :185
смотрит ACTIVE_OPERATION_KINDS вместо пересечения ограничений.

**Решение:** поддерживаемые EvidenceRef загружаются через отдельные resolver:
message — существующая реплика и её реальная аудитория/тип;
event — применённое доменное событие, не скрытая техническая квитанция;
standing — существующий ready ответ с реальными участниками;
time_interval — конкретный FrontRef и подтверждённый обработанный интервал.
Неизвестный/чужой source не включается как достоверный и даёт отказ.
Вопрос остаётся основанием interest, а не доказательством выполненного союза.

Допустимые операции = активный реестр ∩ серверная policy ∩ разрешения кампании/
модуля. Mutable-адреса берутся из валидированных metadata, не из наличия строки.

- [x] Добавить parameterized test_missing_or_foreign_evidence_denied по всем kinds,
  test_question_is_not_alliance, test_hidden_evidence_keeps_audience.
- [x] Добавить test_empty_policy_denies_operation, test_module_disallows_operation
  и test_existing_fact_does_not_imply_mutability.
- [x] Проверить исходный FAIL; реализовать resolvers и пересечение permissions.
- [x] Проверить ограничение refs до загрузки и фактический read_set валидаторов.
- [x] Прогнать context/policy/module permissions и локальный master; коммит
  fix(narrative): resolve durable evidence and honor permissions.

### F3. Защитить факты на реальном пути записи

**Files:** app/tools/narrative/tools.py, compiler.py;
app/core/narrative/facts.py, policy.py; app/db/narrative.py.
**Tests:** tests/test_narrative_executor.py, drafts.py, replay.py.

**Основание:** tools.py:60 безусловно заменяет value/freedom существующей строки.
Защита только revise_draft_fact не защищает add_campaign_fact.

**Решение:** создание по занятому адресу отказывает. Развитие существующего
свойства идёт через доменную проверку его временной семантики и актуальной версии:
historical committed и anchor неизменны; current_state меняется новым событием
с сохранением предыдущей версии; draft_only пересматривается до закрепления.
Historical draft тоже допускает обоснованный пересмотр до закрепления;
одна метка historical не должна запрещать изменение свободной заготовки.
Модель не выбирает новую семантику/freedom для обхода защиты.
Для изменения сохраняются before/after и inverse. Snapshot_ref новой версии
должен адресовать именно её; историческое чтение не ссылается на старое значение.

- [x] Добавить test_add_cannot_replace_committed_history: «герцог умер» не
  заменяется на «не умирал» и не становится draft.
- [x] Добавить test_current_intent_changes_preserving_previous_version,
  test_cannot_change_fact_semantics и test_fact_update_event_has_inverse.
- [x] Воспроизвести FAIL через apply_in_context/реальную БД, не только revise_draft.
- [x] Провести все замены через один валидатор; проверить версии и dependency refs
  по сохранённому состоянию после world guard.
- [x] Прогнать executor/drafts/replay/facts и сохранение после рестарта; коммит
  fix(narrative): preserve committed truth and fact history.

### F4. Подключить жизненный цикл нитей и разделить бюджеты

**Files:** app/tools/narrative/tools.py, executor.py, context.py, compiler.py;
app/core/narrative/threads.py, policy.py; app/db/narrative.py.
**Tests:** tests/test_narrative_threads.py, executor.py; новый budget scope test.

**Основание:** tools.py:120–129 присваивает status напрямую;
executor.py:270/context.py:141 используют вечные novelty_scene/novelty_session.

**Решение:** существующая нить меняется через transition_thread с реальным
основанием; upsert не обходной путь активации/смены terminal status.
Создание нити — offered, принятие — только подтверждённый выбор.
Resolved продолжается дочерней нитью. Attention рассчитывается по конечному
состоянию всего пакета с учётом переходов и аудитории.

Счётчики имеют server-owned scene_boundary_ref/session_budget_ref.
Future-заготовка не тратит лимит текущей сцены: её новизна учитывается в
исходной сессии и bounded пакете. Materialize оплаченного actor_slot не
списывает сессионную новизну второй раз, но учитывает появление нового
участника в конкретной сцене. Повтор и reconnect ничего не сбрасывают.
Правило закрепить в спеке и тестах; legacy totals переносить консервативно
в текущую область, не выдавать бесплатный reset активной сцены.

- [x] Добавить test_persisted_resolved_cannot_reactivate,
  test_interest_cannot_accept_thread и test_transition_respects_attention_limit.
- [x] Добавить тесты: новая сцена получает 3, новая сессия 12, retry не reset,
  будущая подготовка не закрывает текущую сцену, materialize не double-charge.
- [x] Воспроизвести FAIL на реальном адаптере и сохранённых counters.
- [x] Применить domain transitions; хранить scope ключи и spent actor_slots
  в устойчивых ограниченных данных, с inverse/atomic rollback.
- [x] Прогнать threads/master/replay/actors и разделение групп; коммит
  fix(narrative): enforce thread choices and scoped novelty.

### F5. Исправить закрепление и пространственные refs

**Files:** app/tools/narrative/commitments.py; app/core/narrative/facts.py;
app/core/world_generation/storage.py, contracts.py;
app/tools/master/knowledge.py; app/core/plot_anchors.py.
**Tests:** tests/test_narrative_commitments.py, blueprint_contract.py,
tests/test_world_generation.py, tests/test_plot_anchors.py.

**Основание:** commitments.py:33 закрепляет только переданные строки;
storage.py:464 не задаёт snapshot_ref, :491 использует запрещённый kind=turn;
knowledge.py:98 закрепляет все факты одного субъекта.

**Решение:** record_commitments загружает точные версии и bounded зависимости,
вызывает seal_facts и атомарно записывает все результаты.
Foreign/stale ref, пропавшая зависимость, цикл или превышение лимита —
отказ без частичного закрепления.
Draft_only может стать committed при введении: этот статус запрещает
последующий реткон, а не само закрепление заготовки.

Строка namespace:subject:key разрешается сервером в полный актуальный FactRef.
SnapshotRef — package/plan/event с реальным сохранённым source; turn_id
остаётся метаданными события и не новым kind.
Learn_fact использует exact used refs; имя/свидетельство не закрепляет
несвязанные motive/secret и не превращается в truth.

- [x] Добавить реальный A -> B -> C materialization test: все зависимости
  committed; независимый мотив остаётся draft.
- [x] Добавить тесты версии/campaign/cycle/16–64 лимитов и draft_only sealing.
- [x] Добавить world_generation commit_result с непустым used_fact_refs:
  проверить оба формата refs и отсутствие ValidationError.
- [x] Исправить resolver/снимки/транзитивную запись и knowledge-hook.
- [x] Прогнать реальную подготовку, anchors, commitments и guard rollback;
  коммит fix(narrative): seal exact dependencies through spatial preparation.

### F6. Подключить единое чтение канона и раскрытие

**Files:** app/core/world.py, narrative/view.py, adventure.py, knowledge.py;
app/db/narrative.py; app/tools/narrative/compiler.py;
app/agents/architect.py, master/finish.py, master/creative.py, master/recall.py.
**Tests:** tests/test_narrative_module_view.py, adaptive_module.py,
master.py; tests/test_adventure.py.

**Основание:** effective_module_entry/initialize_plan_metadata/
reserve_narration_claims не имеют production caller; World.narrative_view пуст.
Compiler.py:143 передаёт learn_fact неподдерживаемый fact_address.

**Решение:** инициализация метаданных происходит при подготовке/включении
кампании, чтение — в load_world и используемых adventure/knowledge adapters.
Не мутировать общий CatalogView. Публичные свойства и скрытые мотивы
проецируются с собственной аудиторией; роль NPC не остаётся только в receipt.
Reveal_fact разрешает FactRef и вызывает learn_fact с subject_id, fact,
character_ids, затем точный commitment; лишние/чужие refs запрещены.
Reserve_narration_claims вызывается до LLM и publication по spec §5.4.

- [x] Добавить end-to-end test через обычный ход: новая роль/мотив видны
  в следующем master prompt, разрешённой карточке и adventure reader.
- [x] Добавить successful reveal через runner: знания правильных героев,
  exact sealing, отсутствие секрета в чужом голосе/summary.
- [x] Добавить две кампании одного пакета и reveal-vs-revise гонку.
- [x] Подключить существующие view/init/reservation helpers в runtime;
  не считать ручной вызов effective_module_entry интеграционным тестом.
- [x] Прогнать module/master/adventure/visibility/narration recovery;
  коммит fix(narrative): use accepted canon in real readers and revelations.

### F7. Сохранить идентичность и контекст задания

**Files:** app/core/narrative/contracts.py, ports.py;
app/db/narrative_jobs.py; app/core/narrative/service.py;
app/tools/narrative/triggers.py, reader.py.
**Tests:** tests/test_narrative_jobs.py, service.py, architect.py.

**Основание:** WorkClaim теряет boundary metadata; service.py:53 выдаёт
пустой SnapshotRequest. Source построен из boundary.source_id и теряет kind.

**Решение:** source.source_id для work = устойчивый NarrativeWork.id.
Boundary source_key остаётся ключом дедупликации enqueue, но не receipt.
WorkClaim передаёт evidence_refs, audience, focus, mutable_subject_refs,
feedback и session_budget_ref из сохранённого задания.
SnapshotRequest строится из этого claim, не из пустых defaults.
Schema_version меняется/мигрируется совместимо; уже применённые legacy
квитанции не теряют identity при переходе на новую форму.

- [x] Добавить choice:npc-1 и relationship:npc-1: два job, два source-key,
  две разные receipt после применения.
- [x] Добавить production enqueue → SQL claim → reader → author spy:
  реальное событие союза/аудитория/место не потерялись.
- [x] Добавить restart/coalesce сохранённых grounds и legacy receipt replay.
- [x] Обновить claim DTO и оба пути claim, source binding, request composition.
- [x] Прогнать jobs/service/architect/replay; коммит
  fix(narrative): preserve work identity and boundary evidence.

### F8. Довести workflow, lease и публикацию

**Files:** app/core/narrative/service.py, ports.py;
app/db/narrative_jobs.py; app/tools/narrative/runtime.py, executor.py.
**Tests:** tests/test_narrative_service.py, recovery.py, jobs.py, replay.py.

**Основание:** service.py:101 может завершить A с proposal B; no_change
обходит receipt; renew/resnapshot не вызываются; now остаётся прежним.
Runtime.py:62 фиксирует БД без publish_changes; исключение автора прерывает batch.

**Решение:** после save_draft вернуть prepared; следующая apply-итерация
использует исключительно claim.draft того же work_id. Убрать nested claim
и применение прежней локальной переменной proposal.
No_change сохраняется/applies тем же путём и получает receipt.

RuntimeNarrativeApplier.apply(proposal, *, claim: WorkClaim) и соответствующий
порт принимают server-owned claim для work-пути. Перед commit проверяются
совпадение work/source/proposal и действующий lease_token. Обновить fakes.
Clock перечитывается на каждой стадии; heartbeat использует jobs.renew.
LeaseLost не превращается в успешное применение.

Один stale может resnapshot, model-correctable denial — одна корректирующая
попытка с persisted feedback, максимум 2 вызова. Security/policy/source denial
не превращается в творческий обход. Deferred освобождает lease и ждёт
без новой генерации. Failure одного job фиксируется отдельно; batch продолжает
следующую кампанию. После commit — publish_changes с прежними фильтрами audience.

- [x] Добавить author B / apply A race; applied proposal всегда принадлежит
  завершённому job. No_change имеет один Event и receipt_event_id.
- [x] Добавить first-campaign author error + second-campaign success,
  correction, один stale/resnapshot и retry после restart.
- [x] Добавить heartbeat/late-worker takeover во время network и world commit;
  просроченный worker не пишет мир.
- [x] Добавить recording bus: событие видно нужным клиентам после commit,
  rollback ничего не публикует.
- [x] Прогнать jobs/service/recovery/receipts на обеих БД; коммит
  fix(narrative): make director workflow recoverable and observable.

### F9. Собрать и проверить режиссёра в приложении

**Files:** app/main.py, agents/master/service.py, finish.py, architect.py;
app/agents/director.py; app/tools/narrative/runtime.py, reader.py.
**Tests:** новый tests/test_narrative_startup.py; existing architect/recovery.

**Основание:** main.py:99 не передаёт narrative_preparer; нормальный startup
не создаёт NarrativeService/LlmNarrativeAuthor. Adaptive revise только enqueue.

**Решение:** composition root создаёт reader/jobs/author/applier/service,
внедряет service в MasterService и использует существующий recovery/wake loop.
Настройка модели выбирается по кампании через действующий model_of, а не
единый фиксированный model_config для всех кампаний.
Call_observer обновляет зарезервированный LlmCall; spend_limit проверяется
до сети. Ошибка/неизвестная стоимость не означает нулевую цену.
Replan=false и ended campaign выключают новые фоновые изменения.

- [x] Добавить тест через create_app с fake LLM: закрытие акта создаёт job,
  штатный recovery доводит его до receipt и другого будущего узла.
- [x] Добавить restart, session close/open, replan=false и отсутствие
  доступного модельного бюджета; fake LLM не вызывается сверх лимита.
- [x] Проверить calls/cost/error и отсутствие транзакции/turn_lock во время LLM.
- [x] Подключить composition; восстановить adaptive default только после
  исправленных gate-проверок, сохранив strict для неподдерживаемых модулей.
- [x] Прогнать startup/architect/first-slice/recovery; коммит
  fix(narrative): wire the director into application startup.

**Проверено 2026-10-13:** tests/test_narrative_startup.py — 8 тестов через create_app:
ход с end_act → задание act_closed → штатный recover → квитанция и изменённый узел act3;
во время вызова модели нет turn_lock и удержанной транзакции записи; LlmCall(purpose=director)
с токенами; replan=false / spend_limit=0 / ended — модель не вызывается, задание ждёт;
рестарт применяет готовый черновик без нового вызова; ответ «без изменений» — одна
квитанция без сдвига ревизии мира; пауза сессии готовит следующую, end — нет.

Попутно найдены и исправлены дефекты подключения:
- D: адаптивный revise ставил act_closed без основания — любая операция отклонялась.
  Основание — событие end_act; тот же ключ, что у границы хода.
- E: act_closed из хода получал постоянный source_id "act" — второе закрытие акта
  сливалось с первым. Ключ — id события.
- F: пустое предложение отклонялось как missing_ground (лишний платный вызов) и брало
  захват мира, сдвигая ревизию под параллельным ходом. Теперь no_change — до захвата.
- Конец сессии (spec §16.1) не создавал границу: пауза ставит session_closed.
- Ворота replan/ended/strict/spend_limit — до claim и сети, задание не сгорает;
  ошибка одной кампании не прерывает обход; выдуманная цена 0.0001 убрана.
- Тестовая инфраструктура: ScriptedLLM отвечает режиссёру отдельно (director_requests),
  общий client с реальным LiteLLM не запускает фонового режиссёра.

### F10. Уважать индивидуальные часы фронтов

**Files:** app/core/narrative/fronts.py; app/tools/plot.py; app/gateway/ws.py.
**Tests:** tests/test_narrative_fronts.py, adaptive_module.py.

**Основание:** fronts.py:105–121 и :161–171 рассчитывают один интервал
длительности кампании для всех фронтов, игнорируя period/clock_at.

**Решение:** для explicit-front использовать его собственные period/clock_at;
для legacy antagonist сохранить прежний интервал через адаптер.
Первая точка отсчёта, несколько прошедших периодов, stopped и transition_key
проверяются по одному авторитетному прогрессу.

- [x] Тест hourly-front: 3599 секунд — 0, 3600 — 1; повтор — 1,
  7200 — 2; stopped не тикает.
- [x] Тесты двух front с разными period, legacy strict и clock_at после restart.
- [x] Исправить per-front расчёт без второго timer и без создания армии текстом.
- [x] Прогнать front/plot/standing/adaptive module и human-master route.
- [x] Коммит fix(narrative): advance each front on its own clock.

**Проверено 2026-10-13:** 49 passed в front/adaptive module/standing/plan/master panel;
Ruff check и format --check для изменённых Python-файлов — PASS.
Регрессии часов, загрузки из БД и WebSocket живого мастера подтверждены RED → GREEN.
Новые paused/completed фронты не тикают; legacy oneshot/module сохраняют отсутствие
автоматического продвижения антагонистов. Изменять plot.py/ws.py не потребовалось:
оба существующих маршрута используют общий run_clock.

Общий pytest с ограничением числа ошибок остановился: 203 passed, 3 failed
(test_schema_is_fresh, test_ai_player_answers_once_after_master,
test_master_leads_by_plan). Все три отдельно воспроизведены с прежним fronts.py
из fb6a7d8 при остальных текущих изменениях рабочего дерева; исправления относятся
к другим задачам. Полный Gate D этим запуском не подтверждён.

### F11. Проверять реальные ограничения и убрать ложные зелёные сигналы

**Files:** tests/test_narrative_scale.py, quality.py;
app/tools/narrative/context.py; tools/eval_narrative.py;
файлы, указанные Ruff; docs/master-narrative-adaptation.md.

**Решение:** 10 000 шумовых записей в той же кампании плюс соседняя кампания
для изоляции. В запросе есть действительно существующие релевантные основания.
Проверять 50 grounds, 80 facts+actors+fronts совокупно, 20 threads и
6000 токенов, а не только len(facts). SQL читает bounded нужные записи;
проверять statement/result shape и индексный план, не нестабильный таймер.

Ruff из текущего ревью сообщает, среди прочего, undefined game в turn.py:878,
E402 в entities.py:103, imports/длинные строки; format требует 38 файлов.
Не делать массовое форматирование поверх независимых пользовательских правок.
Повторить проверку на чистом исправленном commit.

Scripted quality не выдаётся за оценку автора. Live CLI сейчас пропускает
все случаи независимо от model-config: реализовать разрешённый режим либо
явно документировать его недоступность; не печатать PASS модели без вызова.

- [x] Дополнить scale-тест реальными grounds и combined caps, подтвердить FAIL
  на старой сборке снимка с 120 subject refs.
- [x] Ограничить source/fact/actor/front выборку и сохранить необходимые
  зависимости; недостающий контекст не становится разрешением.
- [x] Исправить конкретные lint/type ошибки; форматировать только проверенный
  набор файлов вне чужих изменений.
- [x] Проверить quality fixture/CLI, status skipped для отсутствующей модели
  и отсутствие секретов/ключей в отчёте.
- [x] Прогнать scale/quality, ruff check, ruff format --check; коммит
  test(narrative): verify realistic bounds and honest quality reporting.

**Проверено 2026-10-13:** scale, context, director и quality — 22 passed;
scale использует реальные события/сообщения текущей кампании, соседнюю кампанию,
EXPLAIN QUERY PLAN и один батч-запрос на тип evidence. Scripted CLI — 8/8 PASS;
live CLI — 0/8 PASS, 0 failed, 8 skipped без разрешённой модели и без ключей в
отчёте. `ruff check .` — PASS; `ruff format --check` для всех изменённых F11-файлов —
PASS. Полный формат репозитория намеренно не расширялся на 23 независимых файла,
которые уже были вне F11 и содержат изменения других задач.

### Дополнительная сверка A–C перед F12

- [x] A: подстановка источника сообщения только для явного `"current"`;
  `None`, пустая строка и выдуманный ID отклоняются. Регрессии с реальным
  ходом мастера подтверждены RED → GREEN.
- [x] B (остаток F4): произвольное применённое событие не принимает нить.
  `EvidenceRecord` содержит server-derived связь с выполненной заявкой
  игрока и её целями; `offered → active` требует совпадения с `subject_refs`.
  Проверяются сохранённые ref, кампания, персонаж, место игрока, часть
  заявки, завершённый результат и принадлежность события результату.
  Существующие resolution-данные читаются пакетно, без N+1.
- [x] C (остаток F8): обработка охватывает все стадии после claim; при
  доступной БД сбой освобождает lease/слот и назначает retry, ID задания
  не теряется. `renew=False` прекращает исполнение. Коды ошибок стабильны,
  сырые исключения исключены из отчётов, диагностики сервиса и `LlmCall.error`.
- [x] Финальное ревью: временный сбой `finish()` после успешного apply
  повторяет исходный результат и feedback, сохраняя receipt/draft.
  SQL-регрессии `applied`/`no_change` с исчерпанными двумя вызовами и
  регрессия корректирующего feedback подтверждены RED → GREEN.

**Ruling:** принятие выводится из уже выполненной заявки игрока, отдельный
LLM-классификатор или новый UI не вводятся. Нить без предметных `subject_refs`
и событие без сохранённого player provenance остаются предложенными;
это консервативное поведение для legacy-данных. При полном отказе БД
невозможно надёжно освободить lease: возвращается `failure_recording_error`,
сохраняется штатное восстановление по сроку lease.

**Проверено 2026-10-13:** `pytest -n 4 -k narrative` — 264 passed,
1 skipped; `app.contract --check` и `ruff check .` — PASS.
Тесты включают реальную запись статуса нити и освобождение SQL-задания
при сбое snapshot до резервирования LLM-вызова.
Изменённые Python-файлы — `ruff format --check` PASS; scripted quality —
8/8 PASS. Независимое ревью изменений A–C нашло один Important-дефект
финализации; он закрыт регрессиями сохранения результата/feedback.
Полная приёмка F12 этим прогоном не заменяется.

### F12. Полная приёмка и пакет для повторного ревью

**Files:** тесты предыдущих задач; docs/master-narrative-adaptation.md;
при необходимости исправленный спек/план и CI.

Этот шаг выполняется после F1–F11 на чистом commit, а не на рабочем дереве
с независимыми UI-правками. Если проверки выявили дополнительный дефект,
добавить воспроизводящий тест и отдельное исправление, затем повторить
затронутые проверки.

- [ ] SQLite: полный python -m pytest -q; сохранить summary и skipped reasons.
- [ ] PostgreSQL: отдельная test database + TEST_DATABASE_URL;
  alembic upgrade head, alembic check, downgrade base и повтор upgrade head,
  полный pytest с настоящими двухсессионными гонками.
- [ ] Ruff: check и format --check всего проверяемого commit;
  app.contract --check; SRD content strict validate.
- [ ] Клиент: npm test, npm run gen:api + проверка отсутствия нового diff
  generated-типов, npm run build. Указать commit и окружение.
- [ ] Реальный create_app сценарий: союз → future job → режиссёр →
  исправленный план → следующая сцена → reconnect; no_change/error/lease
  варианты не создают повторного эффекта.
- [ ] Обновить ограничения/статус документации и checklist исходного плана
  по реально выполненным пунктам. Изменившиеся контракты F4/F7/F8 зафиксировать
  в спеке; не заменять отчёт обещанием «всё должно пройти».
- [ ] Коммит test(narrative): complete repaired Gate D verification.

## Что прислать на повторное ревью

1. Ветку и полный SHA финального commit; отдельный список коммитов F1–F12.
2. Краткое соответствие R1–R20 → исправление → regression test.
3. Результаты полного SQLite и PostgreSQL pytest, миграций, Ruff,
   server/client contracts, content, клиентских тестов и сборки.
4. Причины skipped/непроведённых проверок; версия Python/Node/PostgreSQL.
5. Результат startup-сценария режиссёра, проверки двух кампаний и stale lease.
6. Какие изменения поведения/контрактов пришлось внести относительно спека.

Не нужно заранее сливать main. Повторное ревью проводится по исправленному
commit и заявленному diff. Положительный результат scripted-эталонов отдельно
отделяется от результата полного пользовательского сценария.

## Самопроверка плана

- [x] Каждый подтверждённый дефект R1–R20 связан с задачей.
- [x] Исправления границ доверия предшествуют подключению фонового автора.
- [x] Тесты проверяют реальные tools/startup/storage, а не только helpers.
- [x] Описаны отдельные source identity, lease, receipt и публикация.
- [x] Остаток Gate D и данные для повторного ревью перечислены.
