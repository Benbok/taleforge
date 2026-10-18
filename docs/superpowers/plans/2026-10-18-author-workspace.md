# Author Workspace and Reusable Adventures Implementation Plan

> **For agentic workers:** Use `superpowers:executing-plans` to implement this plan task by task in the current session. `superpowers:subagent-driven-development` is an alternative only if the user explicitly selects agent delegation. Steps use checkbox syntax for tracking. This document authorizes no product implementation by itself.

**Goal:** Добавить отдельное пространство автора, подготовку и проверку всех предусмотренных карт и содержимого, публикацию приключения и независимый запуск игр из библиотеки, сохранив существующее создание кампаний.

**Architecture:** `AuthorProject` управляет изолированным рабочим миром, использующим существующие генераторы. Проверенный типизированный снимок публикуется в неизменяемой `AdventureVersion`; каждая новая игра получает новые ID и собственное состояние. География, проверки и явные точки подключения маршрутов связывают сюжетный каркас с детальными картами.

**Tech Stack:** Существующие Python >=3.11, FastAPI, SQLAlchemy, Alembic, Pydantic, PostgreSQL/SQLite, React, TypeScript, TanStack Query, React Router, pytest и Vitest. Новые библиотеки для графа, очереди и карт в MVP не нужны.

**Spec:** `docs/superpowers/specs/2026-10-18-author-workspace-design.md`.

## Global Constraints

- Существующие `/new`, создание `Campaign`, кабинет кампании и запущенные игры сохраняются.
- Backend-модель `Campaign` продолжает обозначать игровое состояние; существующая `GameSession` остаётся записью отдельной встречи внутри игры.
- Старые `/new`, `/c/:id`, `/c/:id/manage` остаются.
- Библиотека первой версии — свои опубликованные проекты; публичный маркетплейс не требуется.
- Не подставлять географический ID в `End.place_id`, ожидающий `Entity`.
- Нельзя заменять все строки по regex или слепо копировать Entity.state.
- Полный bundle и редактор не возвращаются в проекции без спойлеров.
- Все новые endpoints имеют типизированные Pydantic DTO и включаются в генерацию клиентских типов.
- Тесты используют существующую блокировку live LLM из `tests/conftest.py`. Платные пилоты не требуются для выполнения автоматических проверок.
- Публикация и запуск игры не вызывают LLM. Повествование конкретной игры начинается существующим игровым процессом после старта.
- После изменения кода запускать `graphify update .`; документационный этап этого плана не требует перестройки графа.

## Review Focus

1. Рабочий мир случайно попадает в игровые списки/recovery или запускает вступление: задачи 1–2, проверки API и фоновых служебных действий.
2. Ссылки внутри JSON и manifests остаются на IDs источника: задачи 7–8, проверка всех декларированных ссылок и независимых копий.
3. Авторский просмотр открывает карты в игре или выдаёт секреты через API/ошибки: задачи 9–10, тесты wire payload и отсутствия побочных записей.
4. Правка или второй worker завершает устаревшую задачу поверх нового результата: задачи 2, 4–5, 7, проверки lease/digest и публикации после редактирования.
5. Наличие маршрута в графе маскирует физически непроходимый выход: задачи 3, 6, 11, проверки клеточного пути и перехода в обе стороны.

## Поставка и зависимости

Задачи — части одного выпуска. API публикации/запуска включать для пользователей только после прохождения сценария задачи 11. Пустая библиотека и незавершённые этапы имеют обычные UI-состояния; они не обозначают готовность приключения.

```text
0 → 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8
                                  ↘ 9 → 10 → 11
```

Общий список повторно используемых узлов: `architect.generate`, `CampaignSecret.setting/plot`, `develop`, `WorldGenerationState`, `Orchestrator`, `location_exits`, `LocationMapSvg`, схемы инструментов мастера, `LlmCall`.

## Task 0: Проверить и привести к однозначности историю миграций

**Files:**
- Inspect: `alembic/versions/0031_llm_usage_coverage.py`, `alembic/versions/0031_party_map_memory_jsonb.py`.
- Modify after audit: конфликтующие revision declarations и новый forward-repair в `alembic/versions/authoring_schema_reconcile.py` при необходимости восстановления уже применённой схемы.
- Test: `tests/test_authoring_migrations.py`.

**Interfaces:** Produces единственную непротиворечивую Alembic head и известную базу для новой миграции `authoring_foundation`. Не затрагивает поведение создания кампаний.

- [ ] Запустить `python -m alembic heads` и сопоставить оба объявления `revision="0031"`, фактические колонки `llm_calls` и типы `party_map_memories` на копии базы. Не менять работающую базу для исследования.
- [ ] Добавить миграционные сценарии: чистая база, usage-изменения уже присутствуют, JSONB-изменения уже присутствуют, оба набора присутствуют. Для каждого upgrade должен привести к одной целевой схеме без потери строк.
- [ ] Исправить коллизию с сохранением применённых данных. Не ограничиваться переименованием версии в `alembic_version`: forward-repair обязан довести частичную схему до целевой. Проверить downgrade на одноразовой БД.
- [ ] Run: `python -m pytest tests/test_authoring_migrations.py -n 0 -q`; затем `python -m alembic heads`. Ожидаются PASS и одна head без предупреждения о повторном revision.
- [ ] Зафиксировать отдельным коммитом только исправление миграционной истории и проверки. Итоговый parent новой миграции определить из проверенной единственной head; не угадывать номер из имени файла.

## Task 1: Авторский проект, контракты и изолированный рабочий мир

**Files:**
- Modify: `app/db/models.py`, `app/core/campaigns.py`, `app/core/world_tx.py`, `app/agents/master/finish.py`.
- Create: `alembic/versions/authoring_foundation.py`, `app/core/authoring/__init__.py`, `app/core/authoring/contracts.py`, `app/core/authoring/projects.py`.
- Test: `tests/test_authoring_projects.py`, `tests/authoring_helpers.py`.

**Interfaces:**
- `create_project(session, owner: User, request: AuthorProjectCreate) -> AuthorProject`.
- `require_project(session, user: User, project_id: str) -> AuthorProject` проверяет admin и владение.
- Определить в `contracts.py` DTO: `AuthorProjectCreate`, `ProjectSummary`, `ProjectDetail`, `StageReceipt`, `DraftPatch`, `ValidationReport`, `AdventureBundle`, `InstanceOptions`, `LaunchReceipt`. Детальные секции расширяются соответствующими задачами.
- `Campaign.purpose` получает default `game`; `AuthorProject.workspace_campaign_id` указывает на `author_workspace`.

- [ ] Добавить тесты: создание проекта администратором; отказ игроку/чужому администратору; рабочий мир не возвращается `GET /api/campaigns`; старый `create_campaign` по умолчанию создаёт игру. Проверить отсутствие Character, GameSession, приглашений и вступления в рабочем мире.
- [ ] Run: `python -m pytest tests/test_authoring_projects.py -n 0 -q`; подтвердить падение из-за отсутствующей новой функциональности.
- [ ] Реализовать модели `AuthorProject`, `AdventureVersion`, `AuthorJob` и назначение Campaign. Включить persistent publish/launch request keys и input digest; у `LlmCall` добавить nullable author_job_id. Создание workbench использует общий низкоуровневый код настройки контента/модели, но не публичный endpoint и не заселяет игрока. Техническое место мастера допустимо для совместимости `model_of`, оно не открывает игровое лобби.
- [ ] Разделить guard игрового доступа и внутреннюю загрузку мира: обычный `get_viewer` отвергает author_workspace; авторский сервис открывает его после `require_project`. Отфильтровать workbench в игровых списках и recovery; все циклы, выбирающие Campaign/Scene для игровых действий, проверить поиском.
- [ ] Подключить новые мировые записи к `world_revision`, авторские мутации — к контролю `draft_revision`. Статусы очереди не должны ложно менять содержимое черновика.
- [ ] Повторить тесты задачи и существующие `tests/test_api.py`, `tests/test_plan.py`. Ожидается PASS. Commit: `feat: add isolated author projects`.

## Task 2: Сохранённый pipeline поверх существующего архитектора

**Files:**
- Create: `app/core/authoring/jobs.py`, `app/core/authoring/pipeline.py`, `app/core/authoring/runner.py`, `app/core/authoring/lore.py`.
- Modify: `app/agents/architect.py`, `app/core/world_generation/service.py`, `app/main.py`, `app/core/authoring/contracts.py`.
- Test: `tests/test_authoring_jobs.py`, `tests/test_authoring_pipeline.py`.

**Interfaces:**
- `request_stage(session, project: AuthorProject, stage: str, target_ref: str | None, expected_revision: int, request_key: str) -> StageReceipt`.
- `AuthorRunner.run_due(maker) -> None`; `AuthorRunner.prepare(job_id: str) -> None`.
- `stage_view(session, project_id: str, *, full: bool) -> PreparationView`.
- `architect.generate(..., prepare_intro: bool = True)` — additive keyword, legacy default сохраняется; авторский вызов передаёт False.

- [ ] Добавить проверки: повтор request_key возвращает ту же работу; один input_digest не запускается двумя workers; просроченный lease восстанавливается; старый worker не сохраняет результат; создание сюжетного каркаса не вызывает prelude/audio.
- [ ] Добавить проверку бюджета: до вызова резервируется верхняя оценка расхода; недостаточный остаток даёт `blocked/budget_exhausted`, предыдущие результаты сохранены. Неизвестная provider cost явно отображается, а не считается подтверждённым нулём.
- [ ] Run: `python -m pytest tests/test_authoring_jobs.py tests/test_authoring_pipeline.py -n 0 -q`; подтвердить FAIL новых сценариев.
- [ ] Реализовать очередь, lease и этапы `lore`, `plot`, `geography`, `materialize`, `maps`, `validate`. Лор — структурированный результат в `setting`; plot переиспользует архитектора, а не шесть независимых несогласованных генераций.
- [ ] Получать входной digest из зависимостей конкретного этапа. Применять результат в короткой транзакции с повторной проверкой входов и ревизии; сетевой LLM-вызов не удерживает транзакцию. Прокинуть author_job_id в прямые вызовы и дочерние generation-запросы для точного учёта расходов.
- [ ] Подключить author recovery к lifespan и общий preparer. Повтор готового этапа без изменения входов возвращает его результат. Explicit regeneration создаёт новый вариант, сохраняя предыдущий до успешного применения.
- [ ] Повторить тесты задачи и `tests/test_plan.py`, `tests/test_narrative_architect.py`. Ожидается PASS. Commit: `feat: coordinate author preparation stages`.

## Task 3: География, регионы и реальные порты маршрутов

**Files:**
- Modify: `app/db/models.py`, `app/core/world_tx.py`, `app/core/world.py`, `app/core/plot.py`, `app/core/layout/spatial.py`, `app/core/topology.py`.
- Create: `alembic/versions/authoring_geography.py`, `app/core/geography/__init__.py`, `app/core/geography/contracts.py`, `app/core/geography/compiler.py`, `app/core/geography/storage.py`, `app/core/geography/ports.py`.
- Test: `tests/test_geography_compiler.py`, `tests/test_geography_ports.py`.

**Interfaces:**
- `compile_plan(plan: dict) -> GeographyDraft` — чистое преобразование, без materialization.
- `sync_geography(ctx: ToolContext, draft: GeographyDraft) -> GeographyView`.
- `resolve_port(world: World, endpoint: RouteEndpoint) -> RoutePort`; порт содержит node_ref, area_ref, реальный area_id и проверенные клетки.
- `location_exits(..., *, geography: GeographyView | None = None)` — новое необязательное расширение, старые вызовы сохраняют поведение. `LocationExit.route_id` и `route_ref` необязательны.

- [ ] Добавить тесты: три региона/локации, асимметричная legacy ссылка нормализуется в один двусторонний маршрут; явный односторонний маршрут; неверный part_ref; цикл родителей; маршрут между разными кампаниями; два маршрута между одной парой мест.
- [ ] Проверить физический выход: `loc_cave/part_crawl` разрешается в Узкий лаз, а не в корень/Обвал; несогласованный порт не подменяется первым входом комплекса.
- [ ] Run: `python -m pytest tests/test_geography_compiler.py tests/test_geography_ports.py -n 0 -q`; подтвердить FAIL.
- [ ] Создать узлы/связи с ограничениями из spec и явным стартовым ref. Для региона разрешить отсутствие Entity. Для legacy без новых полей не требовать немедленной миграции географии.
- [ ] Добавить в мандат генерации обязательства по портам. Размещать и сохранять их как географические выходы, связанные с route_ref; внутренние passages не переименовывать и не наделять географическими IDs вместо Entity IDs.
- [ ] Проверить существующие `tests/test_topology.py`, `tests/test_layout_topology.py`, `tests/test_layout_passages.py` и новые тесты. Commit: `feat: connect authored regions and location ports`.

## Task 4: Подготовка всех локаций, NPC, предметов и контейнеров

**Files:**
- Create: `app/core/authoring/materialization.py`.
- Modify: `app/tools/plot.py`, `app/tools/master/places.py`, `app/core/layout/plan.py`, `app/core/authoring/pipeline.py`, `app/core/authoring/contracts.py`.
- Test: `tests/test_authoring_materialization.py`, `tests/test_authoring_full_preparation.py`.

**Interfaces:**
- `ensure_location(ctx: ToolContext, node_ref: str) -> MaterializationReceipt` — никакого переноса героев.
- `ensure_actor(ctx: ToolContext, plot_ref: str) -> str` — возвращает существующий/новый ID NPC.
- `prepare_world(maker, project_id: str, preparer) -> PreparationView` — координирует существующие фазы по всем целям.
- `ItemSpec` и `PlacementSpec` — типизированные ключевые предметы и исходные размещения; они входят в bundle.

- [ ] Добавить тест трёх локаций: материализованы все, у всех частей ready geometry, у обязательного наполнения и конечных контейнеров ready preparation. Нет героев, посещений карт и смены сцены от preparation.
- [ ] Добавить проверки повторного develop, конкурентной materialization, NPC в конкретной части, ключа в контейнере и blocked одного участка без утраты остальных карт.
- [ ] Run: `python -m pytest tests/test_authoring_materialization.py tests/test_authoring_full_preparation.py -n 0 -q`; подтвердить FAIL.
- [ ] Вынести идемпотентную материализацию из develop. Его старый параметр `here` сохраняет поведение через отдельное перемещение после materialization; авторский сервис не вызывает это перемещение.
- [ ] Подготовить все участки и ограниченно вложенные контейнеры через существующие WGS. Отделить «не запрошено» от «готово»; перечисление объектов в plot не засчитывает реальную materialization.
- [ ] Все NPC получают реальную исходную сущность и home. В MVP обеспечить исходное размещение; нестандартные автоматические условия появления принимать только при наличии исполняемого поддерживаемого контракта, иначе блокировать публикацию, а не обещать их выполнение текстом.
- [ ] Повторить новые тесты и `tests/test_layout_develop.py`, `tests/test_world_generation.py`, `tests/test_plot_anchors.py`. Commit: `feat: prepare complete authored worlds before play`.

## Task 5: Ручные правки, ограниченный AI-редактор и зависимости

**Files:**
- Create: `app/core/authoring/edits.py`, `app/core/authoring/dependencies.py`, `app/agents/author_editor.py`.
- Modify: `app/core/authoring/contracts.py`, `app/core/authoring/jobs.py`, `app/core/world_generation/storage.py`.
- Test: `tests/test_authoring_edits.py`, `tests/test_authoring_editor.py`.

**Interfaces:**
- `preview_edit(ctx: ToolContext, request: EditRequest) -> EditProposal` — только предложение, без мутации.
- `apply_edits(ctx: ToolContext, patch: DraftPatch, expected_revision: int, request_key: str) -> EditResult`.
- `affected_results(patch: DraftPatch, dependencies: DependencyView) -> tuple[ResultRef, ...]`.
- Операции DraftPatch ограничены `set_lore`, `update_plot_object`, `update_item`, `set_placement`, `upsert_route`, `remove_object`, `edit_map`; refs и изменяемые поля валидируются по типу.

- [ ] Добавить тесты: имя NPC меняется без повторной карты; удаление используемой комнаты возвращает зависимости; изменение частей помечает нужные layout/geometry/placements stale; stale-предложение ИИ даёт 409; отказ/ошибка предложения не меняет черновик.
- [ ] Run: `python -m pytest tests/test_authoring_edits.py tests/test_authoring_editor.py -n 0 -q`; подтвердить FAIL.
- [ ] Реализовать единый путь мутации и журнал авторских правок в Event рабочего мира с before/after и request key. Фоновые результаты не должны перезаписывать ручную правку с новым digest.
- [ ] Реализовать новую ревизию результата только для author_workspace: состояние stale хранится в author dependencies, а WGS получает допустимый переход ревизии. Прежняя карта доступна до проверки и атомарного применения кандидата. Тест повторной генерации должен доказать отсутствие дублей производных объектов и сохранность прежней карты при неудаче кандидата.
- [ ] Для edit_map адаптировать существующие команды sketch/layout к авторскому контексту с revision guard. Не разрешать произвольное изменение служебных JSON полей.
- [ ] Применение предложения ИИ проходит тот же валидатор, что и ручная форма. Инструменты боя, перемещение героев и изменение игровой истории авторскому редактору не выдаются.
- [ ] Повторить тесты задачи и связанные тесты существующего редактирования sketch. Commit: `feat: edit authored content with dependency tracking`.

## Task 6: Техническая проверка и отчёт готовности

**Files:**
- Create: `app/core/authoring/validation.py`.
- Modify: `app/core/authoring/contracts.py`, `app/core/authoring/pipeline.py`.
- Test: `tests/test_authoring_validation.py`.

**Interfaces:**
- `validate_project(ctx: ToolContext, project: AuthorProject) -> ValidationReport`.
- `ValidationIssue(code: str, object_ref: str | None, related_refs: tuple[str, ...], message: str)`.
- Report фиксирует source_revision/source_digest, errors, warnings и coverage по локациям/частям/NPC/предметам/маршрутам.

- [ ] Добавить проверки всех пунктов spec §7. Отдельные ошибки: `missing_location`, `missing_geometry`, `unresolved_route`, `unreachable_port`, `unplaced_actor`, `missing_item`, `stale_result`, `preparation_blocked`, `unsupported_reference`.
- [ ] Обязательные сценарии: маршрут есть в графе, но клетка выхода за стеной; ключ существует только в тексте; секретная необязательная зона не объявляется ошибкой только из-за секретности; условная закрытая дверь отличима от отсутствующего пути.
- [ ] Run: `python -m pytest tests/test_authoring_validation.py -n 0 -q`; подтвердить FAIL.
- [ ] Реализовать обход графа и клеточный поиск существующим кодом без LLM. Проверка не записывает посещения, не открывает контейнеры и не перемещает NPC.
- [ ] Сохранить отчёт с ревизией. Любая последующая мутация делает отчёт непригодным для публикации до повторной проверки. Семантическую проверку ИИ сделать отдельной opt-in работой с бюджетом; техническую публикацию не завязывать на бесконечные правки критика.
- [ ] Повторить тесты, убедиться, что тестовый запрет live LLM не срабатывает при validate. Commit: `feat: validate authored world completeness`.

## Task 7: Типизированный снимок и неизменяемая публикация

**Files:**
- Create: `app/core/authoring/snapshot.py`, `app/core/authoring/references.py`, `app/core/authoring/publication.py`.
- Modify: `app/core/authoring/contracts.py`.
- Test: `tests/test_adventure_snapshot.py`, `tests/test_adventure_publication.py`.

**Interfaces:**
- `export_bundle(ctx: ToolContext, project: AuthorProject) -> AdventureBundle`.
- `validate_bundle(bundle: AdventureBundle) -> tuple[ValidationIssue, ...]`.
- `publish_project(session, project: AuthorProject, expected_revision: int, request_key: str) -> AdventureVersion`.
- `AdventureBundle.schema_version=1`; refs разделены на entity, geography, route, generation и plot namespace.

- [ ] Добавить тесты: export включает карты, порты, содержимое закрытых контейнеров и anchor bindings; исключает героев, чат, explored state, leases, пользователей и LLM history. Ни один экспортируемый foreign ref не остаётся ID рабочего мира.
- [ ] Проверить отказ публикации при старом отчёте, blocked/stale подготовке и неизвестном ссылочном поле. Повтор request key возвращает ту же версию; правка проекта не меняет bundle/digest v1.
- [ ] Run: `python -m pytest tests/test_adventure_snapshot.py tests/test_adventure_publication.py -n 0 -q`; подтвердить FAIL.
- [ ] Реализовать whitelist/adapters для каждой ссылочной структуры из spec §8, включая текстовые ссылки `[[id|название]]`. Не использовать глобальную замену строк; реестр адаптеров явно перечисляет допустимые Entity.state-секции и generation manifests.
- [ ] Подготовить snapshot и публикацию под проверкой согласованности ревизии. Изменение состояния во время публикации приводит к конфликту и повторной проверке, не к смешанному снимку.
- [ ] Повторить тесты. Commit: `feat: publish immutable adventure versions`.

## Task 8: Независимый запуск игр и рабочие переходы

**Files:**
- Create: `app/core/authoring/instances.py`, `app/core/geography/travel.py`, `app/tools/master/travel.py`.
- Modify: `app/core/world.py`, `app/core/topology.py`, `app/tools/master/__init__.py`, `app/tools/master/places.py`, `app/agents/intent.py`, `app/agents/master/action_binding.py`, `app/agents/master/tool_profiles.py`, `app/agents/master/context_snapshot.py`, `app/agents/prelude.py`, `app/gateway/protocol.py`, `app/gateway/ws.py`.
- Test: `tests/test_adventure_instances.py`, `tests/test_geography_travel.py`.

**Interfaces:**
- `instantiate_adventure(session, owner: User, version: AdventureVersion, options: InstanceOptions, request_key: str) -> LaunchReceipt`.
- `travel_route(ctx: ToolContext, route_id: str, character_ids: list[str], action_ref: dict | None = None) -> TravelResult`.
- `TravelResult` содержит moved, source_area_id, destination_area_id, route_id и failure_code; source/destination фиксируются сервером.

- [ ] Добавить тесты двух запусков: все изменяемые IDs различаются; предмет из A остаётся в B; судьба NPC из A не меняет B/источник; actor placement, внешние End.place_id, manifests, anchors и география указывают только на локальные IDs.
- [ ] Проверить свежие knowledge/map memory, отсутствие истории подготовки, зафиксированную цепочку пакетов и ready WGS. Вход в исходную карту не вызывает генерацию. Обычное вступление не делает повторный develop стартового места.
- [ ] Проверить переход part_crawl → part_junction → обратно, закрытый/односторонний маршрут, попытку из другой комнаты, скрытый путь, разделённый отряд и повтор запроса. Выбор route_id нельзя подменить обратной лестницей; неопределённое «дальше» не закрывается произвольным успехом.
- [ ] Run: `python -m pytest tests/test_adventure_instances.py tests/test_geography_travel.py -n 0 -q`; подтвердить FAIL.
- [ ] Создать игру через общий внутренний service и импортировать bundle в одной транзакции. Настройки героев/мастера не импортируются из workbench; готовность мира восстанавливается из типизированных данных. Не копировать runtime NarrativeState: построить исходный индекс из сюжета.
- [ ] Реализовать атомарное движение по готовым маршрутам с существующими проверками сознания, боя, позиции и видимости. Использовать один resolver в gateway, контексте и инструменте. Не создавать state.links побочным эффектом такого перехода.
- [ ] Добавить происхождение событий и inverse для новых географических изменений, протестировать откат перемещения и безопасное повторное выполнение заявки. Описывать только применённый TravelResult; игровое состояние не публикуется обратно в авторский источник.
- [ ] Повторить тесты задачи и `tests/test_layout_transit.py`, `tests/test_layout_turn.py`, `tests/test_topology.py`, `tests/test_plan.py`. Commit: `feat: launch independent games from prepared adventures`.

## Task 9: Авторские API, библиотека и права

**Files:**
- Create: `app/api/authoring.py`, `app/api/adventures.py`.
- Modify: `app/main.py`, `app/api/schemas.py`.
- Test: `tests/test_authoring_api.py`, `tests/test_adventure_library.py`.

**Interfaces:** Все endpoints из spec §9. `summary` и `full` — разные DTO, не один JSON с клиентским скрытием. `POST /api/adventures/{version_id}/games` возвращает Campaign ID и ссылку на существующее lobby/manage.

- [ ] Добавить проверки доступа для владельца, игрока и чужого admin на каждом endpoint. В summary, списках jobs, validation/errors и библиотеке нет имён секретных NPC, тайных маршрутов и полного bundle.
- [ ] Проверить 409 stale revision, 202 принятой подготовки, 404 недоступного проекта/версии и идемпотентный запуск игры. GET не запускает генерацию и не меняет состояние мира.
- [ ] Run: `python -m pytest tests/test_authoring_api.py tests/test_adventure_library.py -n 0 -q`; подтвердить FAIL.
- [ ] Реализовать маршруты через сервисы предыдущих задач и типизированные DTO. Опубликованный bundle не доступен отдельным публичным endpoint; серверный importer читает его после проверки прав запуска.
- [ ] Подключить router, обновить OpenAPI существующим способом проекта, затем `npm run gen:api` в `web`. Проверить, что старые контракты не получили несовместимые обязательные поля.
- [ ] Повторить тесты. Commit: `feat: expose author preparation and adventure launch APIs`.

## Task 10: Отдельное пространство автора и создание игры из библиотеки

**Files:**
- Create: `web/src/pages/AuthorProjectsPage.tsx`, `web/src/pages/AuthorProjectPage.tsx`, `web/src/pages/NewGamePage.tsx`, `web/src/author/AuthorWorkspace.tsx`, `web/src/author/StagePanel.tsx`, `web/src/author/ContentEditor.tsx`, `web/src/author/GeographyView.tsx`, `web/src/author/MapPreview.tsx`, `web/src/author/ValidationPanel.tsx`, `web/src/lib/authoring.ts`, `web/src/components/CampaignBriefFields.tsx`.
- Modify: `web/src/App.tsx`, `web/src/components/Header.tsx`, `web/src/pages/NewCampaignPage.tsx`, `web/src/lib/campaign.ts`.
- Test: `web/src/author/AuthorWorkspace.test.tsx`, `web/src/author/MapPreview.test.tsx`, `web/src/pages/NewGamePage.test.tsx`.

**Interfaces:**
- `AuthorWorkspace({projectId}: {projectId: string})` использует только author query keys и API.
- `MapPreview({map, onSelect}: AuthorMapPreviewProps)` получает данные через props и переиспользует `LocationMapSvg`.
- `CampaignBriefFields` получает controlled draft/onChange; старый create handler, сохранение черновика и переход `/new` не переписываются.

- [ ] Добавить тесты этапов с состояниями running/blocked/stale, ручной правки, просмотра регион → локация → карта, повторной подготовки одного объекта, показа зависимостей и отказа публикации с ошибками.
- [ ] Проверить, что авторский просмотр не вызывает map.step/map.traverse, не создаёт героя и не меняет знания игрока. Summary по умолчанию не загружает full endpoints; раскрытие явно переключает режим и выполняет отдельный запрос.
- [ ] Проверить выбор приключения и версии в NewGamePage, параметры запуска и переход к полученному lobby. Двойной клик использует один request_key. Новая версия в библиотеке не заменяет автоматически выбранную старую.
- [ ] Run в `web`: `npm test -- src/author/AuthorWorkspace.test.tsx src/author/MapPreview.test.tsx src/pages/NewGamePage.test.tsx`; подтвердить FAIL.
- [ ] Реализовать новые маршруты и навигацию. На старой странице вынести только общую анкету и чистые helper-функции. Не переносить игровой Zustand store в author workspace.
- [ ] Реализовать схему регионов как детерминированный SVG/список с подписями и переходом по узлам. Глобальные координаты не обещаются; route inspector показывает оба конца и детали портов.
- [ ] Повторить целевые тесты, затем `npm run typecheck` и `npm run build`. Commit: `feat: add author workspace and prepared adventure picker`.

## Task 11: Полный сценарий, совместимость и подготовка выпуска

**Files:**
- Create: `tests/test_authoring_acceptance.py`, `tests/fixtures/authoring_adventure.json`, `docs/author-workspace.md`.
- Modify: затронутые файлы только для найденных дефектов; `.github/workflows/ci.yml` только если нужны дополнительные команды, а не дублирование существующих проверок.

**Interfaces:** Использует публичные API и те же операции, которые доступны UI. Сценарий не обращается к live LLM.

- [ ] Создать fixture: три региона, пещера с Обвалом и Узким лазом, Туннели с Развилкой, Зал Ничто, NPC, ключ, контейнер и улика. Наличие всех карт и реальных маршрутов проверяется через чтение подготовленных данных.
- [ ] Написать сценарий создания → полной подготовки → правки → validate → публикации v1 → запуска A/B → переходов → изменения NPC/предмета в A → проверки независимости B → публикации v2 → сохранения A/B на v1.
- [ ] Повторить сценарий с перезапуском между этапами, конкурирующими запросами подготовки, повтором публикации и повтором запуска. Проверить отсутствие дублей, stale-перезаписи и раскрытия секретов.
- [ ] Прогнать legacy `/new`, генерацию каркаса, существующее книжное приключение и обычное продолжение старой игры. Они не требуют авторского проекта.
- [ ] Run: `python -m pytest tests/test_authoring_acceptance.py -n 0 -q`; затем целевой набор всех новых authoring/geography/adventure тестов.
- [ ] Завершить стандартные проверки CI: `ruff check .`, форматирование изменённых Python-файлов, `pytest -q`, `python tools/eval_narrative.py --cases tests/fixtures/narrative_quality.json --mode scripted`, `python -m app.content validate content/dnd5e-srd --strict`.
- [ ] На отдельной тестовой PostgreSQL выполнить миграционный цикл и pytest с `TEST_DATABASE_URL`; не использовать игровую БД. В `web`: `npm run gen:api`, проверка актуальности типов, `npm test`, `npm run build`.
- [ ] Запустить `graphify update .` после кода. В документации описать новый и старый пути, отсутствие спойлеров по умолчанию, границы полной подготовки, бюджет и повторный запуск игр.
- [ ] Итоговый обзор diff и проверка R01–R16 по таблице ниже. Commit: `test: verify authored adventure reuse and legacy compatibility`.

## Покрытие требований и границы выпуска

| Требования | Основные задачи | Доказательство |
| --- | --- | --- |
| R01 | 1, 2, 8, 10, 11 | Старый create и вводная не изменились для обычной игры. |
| R02–R04 | 1, 2, 5, 9, 10 | Отдельные страницы, сохранённые этапы, правки и recovery. |
| R05 | 4, 6 | Ни одной отсутствующей карты/обязательного размещения в опубликованном объёме. |
| R06–R07 | 3, 8, 10 | Подписанная иерархия, маршруты конкретных зон и фактический переход. |
| R08 | 6, 7 | Публикация с технической ошибкой запрещена. |
| R09–R11 | 7, 8, 11 | Две независимые игры, immutable v1, отдельная v2. |
| R12 | 1, 9, 10 | Проверяется payload, а не только скрытый UI. |
| R13–R14 | 2–5, 7–9 | Общие генераторы, lease/digest, idempotency и revision guards. |
| R15 | 8–10 | Выбор опубликованной версии и обычное игровое лобби. |
| R16 | 4, 8, 11 | Постоянные NPC и размещения, исходное состояние и независимые события игр. |

Миграция уже сыгранной кампании в авторский источник, полноценный свободный чат редактора, рисование регионов и автоматический перенос сохранения на новую версию — отдельные планы после MVP. Для текущей проблемной кампании можно позже подготовить точечный инструмент восстановления, но этот выпуск не должен менять её данные побочным эффектом.

## Порядок исполнения и проверки самого плана

Перед кодом прочитать spec целиком. Выполнять задачи последовательно; каждая заканчивается своим осмысленным тестовым циклом и отдельным коммитом. Команды выше — план будущих проверок, они не заявлены выполненными при написании документа.

План проверяется на единые термины и интерфейсы: `CampaignPlan` не равен `AdventureVersion`; рабочий мир не равен игре; route_ref не равен Entity ID; summary не равен full; готовый plot не равен готовому приключению. Первый пользовательский выпуск включает полный путь подготовки и повторного запуска, а не только каркас нового UI.
