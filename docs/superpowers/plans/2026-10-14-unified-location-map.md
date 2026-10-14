# Unified Location Map Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Отображать постоянную общую карту комплекса и раскрывать интерьеры всем игрокам по мере исследования отрядом.

**Architecture:** Публичный план строится безопасной проекцией опубликованного blueprint. Отдельная общая память хранит наблюдённую геометрию и открытия проходов; живые сущности остаются в персонально разрешённом слое. Клиент рисует все разрешённые контуры в общей системе координат и сохраняет камеру при переходе между участками.

**Tech Stack:** Python, SQLAlchemy AsyncSession, Alembic, Pydantic, PostgreSQL/SQLite, React, TypeScript, Zustand, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-14-unified-location-map-design.md`.

## Global Constraints

- «Исследование общее для отряда»; одна группа исследования на кампанию.
- «Полный blueprint никогда не отправляется игроку».
- «Повторный GET не меняет БД».
- «Общая память не расширяет боевую видимость и не открывает удалённое управление героями».
- «Новые и существующие комплексы с blueprint получают единое отображение без перегенерации карт, изменения ID, NPC, объектов, anchors и passages».
- «Локации без blueprint и книжные карты продолжают существующее отображение».
- Работать в существующем worktree `.tmp/main-push`, ветка `main`, по предпочтению пользователя. Корневой dirty worktree `feat/multipart-actions` не менять.
- Изменение проекции и открытие неизвестного контура не вызывает LLM и не запускает генерацию всех помещений.
- Поклеточный туман, художественные ассеты и изменение композиции шаблонов не входят в план.

## Review Focus

- Два героя одновременно открывают разные проходы: оба открытия сохраняются; проверка в задаче 2.
- Удалён герой, исследовавший склад: общая память сохраняется; проверка в задаче 1.
- Старый снимок относится к другой ревизии blueprint или другому комплексу: перенос не раскрывает его; проверка в задаче 3.
- Неизвестный подвал и тайник примыкают к обычной комнате: пакет не выдаёт ни их координат, ни уровня, ни прохода; проверка в задаче 4.
- Карта обновляется, пока игрок вручную сдвинул и увеличил вид: камера сохраняется, в том числе при появлении секретной области; проверка в задаче 7.

## Файлы и границы ответственности

- `app/db/models.py`, новая миграция `alembic/versions/0029_party_map_memory.py`: долговечная общая память и открытия.
- `app/core/party_map_memory.py`: запись и чтение общей памяти в транзакции мира.
- `app/core/party_map_backfill.py`: проверка и перенос разрешённых персональных снимков при миграции.
- `app/core/map_outline.py`: чистая безопасная проекция внешней формы; без БД и живых сущностей.
- `app/core/map_projection.py`: объединение публичной основы, общей памяти и разрешённого текущего участка.
- `app/core/map_memory.py`, `app/core/world.py`, `app/core/world_tx.py`, `app/core/layout/transit.py`, `app/tools/runtime.py`: включение общей памяти в существующие наблюдения, переходы, защиту записи и уведомления.
- `app/gateway/protocol.py`, `web/openapi.json`, `web/src/lib/api.gen.ts`, `web/src/lib/socket.ts`, `web/src/game/map.ts`: согласованный контракт.
- `web/src/game/MapOutline.tsx`: неизвестные внешние контуры.
- `web/src/game/LocationMap.tsx`, `web/src/game/locationGeometry.ts`, `web/src/game/MapWindow.tsx`: единая карта, выбор места и уровней.
- `web/src/game/locationViewport.ts`: состояние камеры по комплексу и уровню, отдельно от данных карты.

## Команды проверки

Все Python-команды ниже запускаются из `.tmp/main-push` через абсолютный интерпретатор `D:\Workspace\Projects\taleforge\.venv\Scripts\python.exe` (далее **PY**). Для PowerShell: `& 'D:\Workspace\Projects\taleforge\.venv\Scripts\python.exe' -m pytest ...`.

Frontend-команды запускаются из `.tmp/main-push/web`: `npm.cmd run test -- <файлы>`, `npm.cmd run typecheck`, `npm.cmd run build`. Не скачивать новые зависимости без необходимости.

Перед созданием миграции проверить `PY -m alembic heads`: ожидается текущая голова `0028`. Если появилась новая миграция, выбрать следующий свободный номер и поставить фактический down_revision; не создавать вторую голову.

### Task 1: Схема общей памяти и участие в транзакциях мира

**Files:** Modify `app/db/models.py`, `app/core/world_tx.py`; Create `alembic/versions/0029_party_map_memory.py`, `tests/test_party_map_migrations.py`; Modify `tests/test_map_migrations.py`.

**Interfaces:**
- `PartyMapMemory`: PK `(campaign_id, root_id, entity_id)`, snapshot JSON, revision int, observed_at datetime; все три FK с удалением вместе с кампанией/локацией, без FK на персонажа.
- `PartyMapDiscovery`: PK `(campaign_id, root_id)`, discovered_passages JSON-список строк passage_ref, revision int.
- Зарегистрировать обе модели в `_BY_CAMPAIGN` world guard. Существующий механизм inverse должен разрешать новые таблицы и составные ключи через metadata; если использует allowlist, включить их там же.

- [ ] Написать `test_party_map_migrations_match_metadata`: upgrade head → `command.check` → downgrade 0028 → upgrade head → `command.check`; проверить составные PK и FK.
- [ ] Написать `test_party_memory_survives_observer_deletion`: после удаления Character `assert party_snapshot == previous_snapshot`; после удаления кампании `assert rows == []`.
- [ ] Запустить `PY -m pytest tests/test_party_map_migrations.py -o addopts='' -q`; подтвердить падение из-за отсутствующих таблиц.
- [ ] Добавить модели, миграцию и world guard по перечисленным интерфейсам; не менять персональную MapMemory.
- [ ] Повторить тесты и `PY -m pytest tests/test_map_migrations.py -o addopts='' -q`; ожидается PASS.
- [ ] Коммит: `feat: persist shared party map exploration`.

### Task 2: Наблюдение, открытия, откат и уведомление отряда

**Files:** Create `app/core/party_map_memory.py`, `tests/test_party_map_memory.py`; Modify `app/core/map_memory.py`, `app/tools/runtime.py`.

**Interfaces:**
- `async observe_area(ctx, place_id: str, hero_ids: Sequence[str], inverse: list[dict] | None = None) -> bool`.
- `async discover_passage(ctx, root_id: str, passage_ref: str, hero_ids: Sequence[str], inverse: list[dict] | None = None) -> bool`.
- `async read_snapshots(session: AsyncSession, campaign_id: str, root_id: str) -> dict[str, PartyMapMemory]`.
- `async known_passages(session: AsyncSession, campaign_id: str, root_id: str | None = None) -> frozenset[tuple[str, str]]`.
- `async opened_areas(session: AsyncSession, campaign_id: str) -> frozenset[str]`.

- [ ] Написать тесты: `test_observation_shared_between_heroes`, `test_draft_and_master_do_not_reveal`, `test_same_snapshot_is_noop`, `test_remote_entities_not_in_snapshot`, `test_discovery_union_under_concurrent_writes`, `test_undo_restores_shared_memory`. Проверки: один разрешённый посетитель создаёт общий снимок; повтор не увеличивает revision; ни entity_id, ни скрытых features в снимке; два открытия дают оба passage_ref; inverse возвращает предыдущее состояние.
- [ ] Запустить `PY -m pytest tests/test_party_map_memory.py -o addopts='' -q`; подтвердить RED.
- [ ] Реализовать helpers, переиспользуя `map_memory.static_snapshot` для разрешённой статической геометрии. Проверять кампанию, принадлежность участка корню, действительное присутствие и статус героев. Общую запись вызывать из существующих hooks наблюдения и открытия, один раз на участок за действие.
- [ ] Для записи использовать существующую сериализацию campaign world guard; брать её до read/merge общей записи, обрабатывать WorldConflict существующим механизмом повтора команды. Добавить inverse для snapshot, revision, observed_at и набора открытий, включая удаление впервые созданной строки.
- [ ] Ставить `ctx.signals.add('map.changed')` только при фактическом изменении. Рассылка — всей кампании через существующий bus, без содержимого снимка.
- [ ] Повторить тесты вместе с `tests/test_map_memory.py`; ожидается PASS, персональные знания сохраняются.
- [ ] Коммит: `feat: share observed map geometry and discoveries`.

### Task 3: Перенос безопасных снимков старых кампаний

**Files:** Create `app/core/party_map_backfill.py`, `tests/test_party_map_backfill.py`; Modify новую миграцию задачи 1.

**Interfaces:** `backfill_party_maps(connection) -> dict[str, int]` — синхронная SQLAlchemy Connection миграции, вставляет отсутствующие общие снимки/открытия, возвращает счётчики accepted/skipped; не использует ORM-сессию или сетевые вызовы.

- [ ] Написать тесты: `test_latest_valid_snapshot_wins`, `test_revision_and_root_mismatch_skipped`, `test_draft_snapshot_skipped`, `test_passages_union_scoped_to_campaign`, `test_backfill_does_not_replace_new_shared_memory`. Проверки: поздний updated_at, затем character_id определяют победителя; чужой root и старая ревизия отсутствуют; повторный перенос оставляет общий revision/snapshot неизменными.
- [ ] Запустить `PY -m pytest tests/test_party_map_backfill.py -o addopts='' -q`; подтвердить RED.
- [ ] Реализовать перенос из MapMemory joined Character/Entity с проверкой campaign_id, root_id, schema_version, blueprint_revision и безопасного формата snapshot. Допускать только approved/active; открытия отфильтровать по реально существующим passage_ref корня. Не использовать visited_by для восстановления интерьеров.
- [ ] Включить перенос в upgrade после создания таблиц. Новую таблицу не заполнять полным blueprint. Определение схемы миграции фиксировать локально, чтобы будущие изменения ORM не ломали upgrade.
- [ ] Повторить тесты и миграционный цикл задачи 1; ожидается PASS.
- [ ] Коммит: `feat: migrate existing exploration into party map memory`.

### Task 4: Публичные контуры и единая серверная проекция

**Files:** Create `app/core/map_outline.py`, `tests/test_map_outline.py`, `tests/test_unified_map_projection.py`; Modify `app/core/map_projection.py`, `tests/test_location_map_privacy.py`.

**Interfaces:**
- `public_outline(bp: Blueprint, area: Area) -> dict`: cols, rows, shape, environment, безопасный mask внешнего силуэта, material и terrain только для outdoor. Без walls, details, exits, features, anchors и внутренних level подсказок.
- Существующий `async location_plan(session, viewer, entities, here_id, blueprint_cache=None) -> dict | None` сохраняет сигнатуру.
- Пакет: root_id, root_name, here_id, active_level, bounds (список `{level,minX,minY,maxX,maxY}`), areas.
- Участок: id, name, offset, level, status (`unexplored|remembered|here`), outline, sketch (nullable), revision, observed_at; идентификаторы только обычных или реально раскрытых участков.

- [ ] Написать тесты: `test_root_and_child_share_public_plan`, `test_closed_outline_has_no_interior`, `test_secret_and_unknown_basement_absent_from_packet`, `test_discovered_secret_door_does_not_reveal_room`, `test_visit_reveals_snapshot_to_other_hero`, `test_corrupt_snapshot_returns_outline`, `test_get_does_not_write_or_generate`. Проверки: один root_id; у неизвестного sketch is None; сериализованный пакет не содержит secret name/ref/offset/level; публичные bounds не меняются при посещении обычной комнаты; генератор и LLM не вызваны.
- [ ] Запустить новые тесты; подтвердить RED.
- [ ] Реализовать публичные контуры отдельно от live sketch. Наземные non-secret части включать сразу; остальные только после действительного исследования. Публичные подписи не выводить из приватного описания. Для cave использовать грубую внешнюю форму без внутренней маски.
- [ ] Определять корень через complex либо собственный blueprint. Собрать контуры + общие снимки задачи 2; текущую геометрию добавлять только для разрешённого текущего участка. Для корня не создавать фиктивную party клетку. Полную проекцию мастера собирать отдельно без записи наблюдений.
- [ ] Валидировать сохранённые снимки; повреждённые и устаревшие заменить безопасным контуром с серверной диагностикой. Ручной sketch использовать через существующую безопасную проекцию лишь при совместимом размещении; иначе контур.
- [ ] Повторить тесты и `tests/test_location_map_privacy.py`; ожидается PASS.
- [ ] Коммит: `feat: project continuous location maps without revealing interiors`.

### Task 5: Согласованные права проходов и контракт клиента

**Files:** Modify `app/core/map.py`, `app/core/world.py`, `app/core/map_memory.py`, `app/core/layout/transit.py`, `app/gateway/protocol.py`, `web/src/game/map.ts`, `web/src/lib/socket.ts`, `web/openapi.json`, `web/src/lib/api.gen.ts`; Test `tests/test_location_map_contract.py`, `tests/test_location_maps_delivery3.py`, `web/src/lib/socket.test.ts`.

**Interfaces:** Обновить Pydantic/TS MapLocationPlan по пакету задачи 4. MapKnownArea получает nullable sketch и обязательный outline; discriminated union статусов на клиенте должна исключать использование sketch неизвестного участка. Существующие персональные `known_passages`/`opened_areas` для утверждённого героя дополняются общими данными только его кампании.

- [ ] Написать тесты: `test_shared_secret_passage_available_to_second_hero`, `test_known_remote_area_cannot_be_traversed`, `test_locked_door_still_denies_transition`, `test_other_campaign_memory_not_visible`, `test_unexplored_outline_contract_roundtrip`. Проверки: B может воспользоваться обнаруженным проходом, находясь у его входа; тот же запрос из удалённого места отклонён; locked остаётся locked; пакет проходит Pydantic и socket normalization без фиктивного sketch.
- [ ] Запустить целевые Python/Vitest тесты; подтвердить RED.
- [ ] Подключить общие открытия к спискам проходов, world.map_known и transit.find/check/execute. Оставить проверки текущего положения, клеток входа, дверей и владения героем.
- [ ] Обновить протокол и клиентские типы/нормализацию. Генерировать контракт `PY -m app.contract`, затем из web `npm.cmd run gen:api`; не редактировать generated файлы вручную.
- [ ] Запустить целевые тесты, `PY -m pytest tests/test_contract.py tests/test_location_map_contract.py -o addopts='' -q` и `npm.cmd run typecheck`. Исправить прежние frontend fixtures с prepared на новый контракт.
- [ ] Коммит: `feat: align shared exploration with map traversal and client contract`.

### Task 6: Постоянный общий план в интерфейсе

**Files:** Create `web/src/game/MapOutline.tsx`; Modify `web/src/game/LocationMap.tsx`, `web/src/game/locationGeometry.ts`, `web/src/game/MapWindow.tsx`; Test `web/src/game/LocationMap.test.tsx`, `web/src/game/locationGeometry.test.ts`.

**Interfaces:** `MapOutline({outline, areaId, name}: MapOutlineProps)` рисует внешний контур без интерьерной сетки. `knownBounds` использует серверные bounds по уровню; старый расчёт по sketch остаётся запасным только для старых fixtures. `LocationMapSvg` рендерит outline для unexplored и SketchSurface для remembered/here.

- [ ] Написать тесты: `test_root_uses_location_map`, `test_unexplored_building_has_outline_without_features`, `test_warehouse_opens_without_removing_port`, `test_root_has_no_fake_party_marker`, `test_unknown_levels_not_in_switcher`. Проверки: карта содержит обычные контуры и одну общую SVG; неизвестная комната не имеет furniture/cell action; корень показывает доступные входы без party-marker.
- [ ] Запустить `npm.cmd run test -- src/game/LocationMap.test.tsx src/game/locationGeometry.test.ts`; подтвердить RED.
- [ ] Добавить outline renderer и три состояния с подписями «Не исследовано», «Исследовано» и текущим местом; сохранить мягкое приглушение изученных участков. Заголовок — root_name плюс текущее место.
- [ ] В MapWindow выбирать LocationMap и для корня. Из «Места» фокусировать участок этого же комплекса; переход в другой комплекс переключает карту. Текущие passage/cell/entity actions оставлять только у разрешённого here участка; доступные входы корня используют существующий traverse.
- [ ] Повторить тесты, `npm.cmd run typecheck`; ожидается PASS. Книжный и запасной виды проверяются существующими map tests.
- [ ] Коммит: `feat: display the whole location with progressive interior reveal`.

### Task 7: Камера, уровни и действия обзора

**Files:** Create `web/src/game/locationViewport.ts`, `web/src/game/locationViewport.test.ts`; Modify `web/src/game/LocationMap.tsx`, при необходимости `web/src/game/MapZoom.tsx`; Test `web/src/game/LocationMap.test.tsx`.

**Interfaces:** `useLocationViewport(rootId: string, level: number)` хранит zoom и центр в координатах общего плана по root_id/level в состоянии UI. Методы `focusArea(areaId)`, `focusHero()`, `fitOverview()` не меняют игровое положение. Совместимость useMapZoom для других карт сохраняется.

- [ ] Написать тесты: `test_same_root_transition_preserves_camera`, `test_secret_bounds_growth_preserves_plan_center`, `test_level_camera_restored`, `test_focus_controls_do_not_send_movement`. Проверки: увеличение 2 и выбранный центр сохраняются при here_id смене/новом bounds/закрытии и открытии окна; новый root получает собственный вид; фокус не отправляет map.step или traverse.
- [ ] Запустить целевые frontend тесты; подтвердить RED.
- [ ] Реализовать состояние камеры. Сохранять центр в координатах плана, а не только процент scrollLeft: расширение bounds не должно сдвигать выбранное место. Отдельно сохранять вид уровней, начальный уровень определять текущим местом.
- [ ] Добавить кнопки «Вся местность» и «К герою». В корне вместо фокуса героя показать «Вы в общей локации; выберите доступный вход». Отключить неуместное центрирование при отсутствии клетки.
- [ ] Повторить целевые тесты, typecheck; ожидается PASS.
- [ ] Коммит: `feat: preserve location map camera during exploration`.

### Task 8: Полный сценарий, проверки и существующий контейнер app

**Files:** Create `tests/test_unified_location_map.py`; Modify этот план отметками выполнения, спецификацию — только если обнаружена согласованная необходимость уточнения.

- [ ] Написать интеграционный сценарий с двумя героями и blueprint порта: корень → причал → рынок → склад → причал. До посещения склад имеет только contour; после — общий snapshot; B после переподключения получает его без удалённых NPC. Открыть тайный ход и посетить тайник отдельно; проверить отсутствие утечек до каждого шага.
- [ ] Запустить `PY -m pytest tests/test_unified_location_map.py tests/test_party_map_memory.py tests/test_party_map_backfill.py tests/test_unified_map_projection.py tests/test_map_outline.py tests/test_location_map_privacy.py tests/test_location_map_contract.py tests/test_map_memory.py tests/test_map.py tests/test_location_maps_delivery3.py tests/test_map_migrations.py tests/test_party_map_migrations.py tests/test_contract.py -o addopts='' -q`. Все PASS, отсутствие дополнительных LLM-вызовов подтверждено тестом.
- [ ] Из web запустить `npm.cmd run test`, `npm.cmd run build`; выполнить ruff для изменённых Python-файлов и `git diff --check`. Не заменять визуальную проверку одним typecheck.
- [ ] Провести итоговое ревью реализации относительно спецификации; исправить обнаруженные дефекты и повторить только относящиеся к ним проверки.
- [ ] Подготовить применение к существующему `taleforge-app-1`: проверить compose project, фактические bind mounts приложения и web/dist, миграционную голову PostgreSQL. Сделать резервную копию БД перед upgrade; использовать исходный compose project, env и volumes. Не создавать второй app, БД или новый compose project из имени worktree.
- [ ] При применении выполнить upgrade head на существующей БД и обновить код/сборку в фактическом источнике существующего app. Если изменения входят в image, пересобрать и пересоздать только сервис app исходного проекта; если доступны bind mounts — обновить правильный источник и перезапустить app. Не переносить изменения поверх dirty корневого worktree без проверки.
- [ ] На кампании `c_f88b191291275647` проверить порт из корня и склада, сохранение камеры, общий снимок после выхода, перезагрузку страницы и отсутствие ошибок в логах. ID `en_a232a15b6bad95da`, все дочерние ID, NPC и предметы должны остаться прежними. Перегенерацию не выполнять.
- [ ] Коммит проверок: `test: verify unified party map exploration end to end`.

## Порядок и завершение

Выполнять задачи последовательно: 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8. Не объявлять готовность после появления общего SVG: нужны безопасное раскрытие, разделённый отряд, миграция и проверка реального перехода в комнате.

План подготовлен для выполнения в этой сессии через executing-plans. До реализации пользователь должен проверить план; выбор отдельного параллельного исполнения не требуется.
