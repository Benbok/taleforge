# Карты локаций TaleForge — поставка 2: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Показать на одном SVG-плане открытые конкретному герою участки комплекса, сохранить его последнюю известную геометрию и дать ему проходить через доступные проходы из интерфейса.

**Architecture:** Сервер хранит отдельные снимки карты и обнаруженные проходы по паре «герой — участок», независимо от готовности геометрии и знания об объектах. `party_map` собирает композицию только из разрешённых снимков; живые объекты и действия остаются в текущем участке. Общий SVG-рендерер рисует локальные клетки со смещением blueprint, а существующие серверные `map.step` и `map.traverse` подтверждают движения.

**Tech Stack:** Python 3.12, SQLAlchemy async, Alembic, Pydantic 2; React 19, TypeScript, Zustand, SVG, Vite, Vitest/jsdom. Использовать существующие зависимости.

**Spec:** `docs/superpowers/specs/2026-10-12-generative-location-maps-design.md`, §9, поставка 2; требования §4–7 и применимые пункты §8–10.

**Основа:** `main@8d05a22`; `docs/location-maps-delivery1.md` и образец `docs/superpowers/plans/2026-10-12-location-maps-delivery1.md`. Первая поставка уже дала blueprint, `mask`/`edges`/`terrain`, геометрию, общие состояния проходов, подготовку и `map.traverse`. Не реализовывать их повторно.

## Global Constraints

- Клетка — 5 футов; сторона участка не больше 30 клеток; в комплексе максимум 12 участков и 8 проходов на участок.
- Поворотов участков нет: север сверху, восток справа; `offset` — целые клетки, `level` — отдельный план уровня.
- Маска пола, стены и endpoints — физическая геометрия. Название формы и декоративный SVG её не подменяют.
- Трава, вода, дороги и мосты — визуальное поле; не вводить скорость, плавание, урон или новую стоимость перехода.
- Неизвестный участок не передаётся игроку: ни геометрия, ни имя, ни ID назначения, ни размеры/уровень/offset, ни сущности. Проверять весь `map.state`, включая старые `places`, `links`, `exits`, `sketch` и `book`, а также соседние `state.snapshot`/`scene.updated`: существующая плашка разделённого отряда не должна обходить фильтр через имя/ID чужой комнаты.
- Память содержит контуры и открытые постоянные детали. Ни Entity, ни существа, ни переносимые предметы, ни зоны эффектов не становятся частью сохранённого рисунка.
- Снимок обновляется при разрешённом наблюдении в игровой транзакции. `map.get`, панорамирование, масштаб и переключение уровней ничего не записывают и не запускают подготовку.
- Состояние двери остаётся в `state.passages` корня; blueprint не изменяется при обнаружении прохода. Знание конкретного героя хранится отдельно.
- Сетевые вызовы не держат транзакцию БД; сохранить world revision/CAS, lease, восстановление очереди и защиту ручных эскизов поставки 1.
- Игрок действует только в своей текущей сцене. Память соседней комнаты не даёт `map.step`, взаимодействия с её объектами или удалённого `map.traverse`.
- Книжные карты (`BookMap`) и старые эскизы без новых полей сохраняют свой путь отображения. Не строить blueprint из книги, не перегенерировать посещённые места.
- Использовать `MapGlyph`, `visual_key`, существующие CSS-переменные темы; материалы — локальные SVG-patterns. Не загружать картинки и не использовать LLM для рисунка.
- Тексты интерфейса, комментарии и коммиты — по-русски; Python ruff, длина строки 120.
- Не менять чужую рабочую копию: она может находиться на `feat/narrative-adaptation`. Исполнение — в новом worktree `feat/location-maps-delivery2`, созданном от актуального main.

**Вне поставки:** архитектор/`develop`, текстовый provider, подготовка первой сцены и вперёд, суммарные расходы, новые дальние ориентиры, видимость по клеткам/свету/высоте, бесшовное движение через границу, ротация и объединение разных комплексов в одну глобальную карту. Уже существующий ориентир раскрывается через `reveal_knowledge`; он не получает выдуманную точную клетку.

## Review Focus

1. **Разделённый отряд и замещение.** Открытие тайной двери героем A не открывает её B; смена `playAs` или кампании не показывает кадр чужой памяти. Tests: Tasks 4, 5, 9.
2. **Готовый, но неизвестный сосед.** Нельзя узнать его через `places`, ссылки выхода, SVG bounds, номера уровней, подписи или ошибку по угаданному passage_ref. Tests: Tasks 4, 5, 7.
3. **Изменения вне наблюдения.** Закрытие двери, новая вещь или перенос сундука после ухода не меняют старый снимок; возвращение обновляет доступное. Память не содержит действий над вещами. Tests: Tasks 2, 3, 5, 10.
4. **Координаты и уровни.** Отрицательные offsets, смена `party`, лестница и расширение известных bounds не сдвигают уже известное пространство и не посылают глобальную клетку в локальный `map.step`. Tests: Tasks 7, 10.
5. **Переход в процессе подготовки.** Дверь закрылась, герой ушёл, ответ задержался или связь оборвалась: нет оптимистического перемещения, повторного запроса от двойного клика и применения ответа другому герою. Tests: Tasks 9, 11, 13.

---

## Решения и совместимость

1. Добавить `MapMemory`, а не перегружать `Knowledge.observed_snapshot`: тот снимок описывает объект, имеет собственную policy и используется инспектором. Новая строка содержит знание пространства; запись с обнаруженным проходом может существовать **без** снимка участка.
2. Память относится к участкам с `state.complex`. Для обычного места/книжной комнаты сохраняются нынешние «Вокруг», «Места» и BookMap. В «Вокруг» комплекса появляется единый план; текущая комната дополнительно доступна через существующий `sketch`.
3. Снимок не содержит связанных с Entity features. Постоянные колонны/скалы и незакреплённый декор остаются; сундук, существо и текущее содержимое контейнера — только живой overlay после `object_policy`/`scene_view`.
4. Для изначально тайного прохода (`Passage.hidden`) глобального `live.hidden=False` недостаточно: нужен персональный grant. `edit_sketch reveal` выдаёт его присутствующим у выбранной стороны героям; `reveal_area` — явно указанным героям. `hide` продолжает скрывать физически доступный проход, но не стирает чужие исторические снимки.
5. Не восстановить «последнюю известную» геометрию из `visited_by`: там нет времени/снимка. Миграция создаёт пустую таблицу, не копирует текущие эскизы прошлых посещений. Текущий участок показывается сразу из разрешённой живой геометрии; перед уходом/при новом входе он сохраняется. Старую память и прежнее раскрытие секретов при необходимости восстанавливает мастер явным `reveal_area`. Существующий граф обычных мест сохраняется.
6. `map.traverse` по-прежнему принимает локальный `passage_ref`; добавить только необязательный `source_id` для защиты от устаревшего выбора. Не добавлять ID неизвестного назначения. Неоднозначная ссылка между комплексами остаётся безопасным отказом поставки 1, а не выбором произвольного пути.
7. Видимый проход в неизвестное место остаётся видимым, но `to=None`, `beyond=None`. После личного открытия назначения связь можно подписать его **сохранённым** именем. Сам `passage_ref` известного прохода — уже существующий операционный контракт; не выдавать `area_ref` неизвестного конца.
8. Мастер видит blueprint текущего комплекса, все уровни и отметки раскрытия по героям. Для ещё не построенной геометрии допустим чистый preview через `geometry.build_area`; он не резервирует/не активирует WGS и никогда не выдаётся игроку.

## Контракты, которые связывают задачи

**Проводной DTO (Task 1):**

- `MapKnownArea`: `id: str`, `name: str`, `offset: tuple[int,int]`, `level: int`, `status: Literal['here','remembered','prepared']`, `revision: int`, `observed_at: datetime | None`, `sketch: MapSketch`, `disclosed_to: list[str] | None = None`. `prepared` и `disclosed_to` — только мастеру.
- `MapLocationPlan`: `root_id: str`, `here_id: str | None`, `areas: list[MapKnownArea]`. `root_id` обозначает уже известный содержащий комплекс; raw blueprint/полный список IDs/общие bounds не передаются.
- `MapState.location_map: MapLocationPlan | None = None`, `request_id: str | None = None`, `as_seat: str | None = None`.
- `MapSketchEdge(side,start,length,meaning)` и `MapSketchTerrain(kind,cells)` заменяют `list[Any]` для edges/terrain. Значения — из `layout.contracts`, cells — прямоугольники включительно.
- `MapExit` получает optional `passage_ref`, `kind`, `state`, `width`, `cells`; они нужны и для подхода из обычного места, где `sketch` ещё нет.
- `MapTraverseResult` получает optional `moved`, `error`, `reason`, `area_id`, `area`, `passage`, `cell`, `from_cell`; остаётся `_Open` для нынешних дополнительных результатов боя.

**Сервер (Tasks 2–5):**

- `MapMemory(character_id, entity_id)`: составной PK/FK с CASCADE; `snapshot: dict | None`, `discovered_passages: list[dict[str,str]]`, `revision: int`, `updated_at: datetime`. Каждый grant — `{"root_id": str, "passage_ref": str}`: один локальный ref чужого комплекса не даёт доступ к одноимённому проходу. Строки grants допустимы и у обычного внешнего места, snapshots — только у complex area. Snapshot — версия 1, публичное имя, root/area_ref/offset/level, blueprint_revision/edit_rev, `observed_at`, очищенный `geometry` и приватные `connections` известных проходов. `connections` нужны для связывания позднее открытых концов и никогда не копируются в DTO напрямую.
- `map_memory.static_snapshot(place: Entity, root: Entity, bp: Blueprint, entities: dict[str,Entity], *, discovered_passages: frozenset[tuple[str,str]], revealed: frozenset[str]) -> dict | None`: чистая проекция без записи, timestamps и генерации. Observe helper читает grants/revealed, вызывает её и добавляет observed_at только при сохранении изменённого снимка; projection вызывает её с уже выбранными персональными разрешениями.
- `await map_memory.observe_area(ctx, place_id: str, hero_ids: list[str], inverse: list, *, explicit: bool = False) -> bool`: сохранить разрешённое наблюдение; обычно герой обязан находиться здесь. Возвращает факт изменения.
- `await map_memory.observe_present(ctx, inverse: list) -> bool`: только реальные текущие места PLAYABLE-героев, не все visited. Не вызывает `ctx.record`.
- `await map_memory.discover_passage(ctx, root_id: str, passage_ref: str, hero_ids: list[str], inverse: list) -> None`: grants обоих концов, но без открытия их геометрии.
- `await map_memory.known_passages(session, hero_id: str, place_id: str) -> frozenset[tuple[str,str]]`: известные `(root_id, passage_ref)` со стороны текущего места.
- `await map_memory.opened_areas(session, hero_id: str) -> frozenset[str]`: IDs строк с snapshot, а не grants-only. Task 2 добавляет `World.map_known: dict[str,set[str]]` с default_factory=dict; после observe_area обновляется этот локальный cache. Task 5 загружает его одним batch-query в load_world и использует для персональной сцены, без копирования геометрии в World.
- `await map_projection.location_plan(session, viewer, entities: dict[str,Entity], here_id: str | None) -> dict | None`: композиция текущего комплекса; не изменяет БД.

**Frontend (Tasks 6–11):**

- `Sketch` явно поддерживает mask/edges/terrain/material/environment; `SketchExit.kind` дополнительно `gate`/`edge`, а также width/passage_ref/cells.
- Task 6 экспортирует из `map.ts` `Point = [number,number]`, нормализованные `MapKnownArea = Omit<GeneratedMapKnownArea,'sketch'> & {sketch: Sketch}` и `MapLocationPlan = Omit<GeneratedMapLocationPlan,'areas'> & {areas: MapKnownArea[]}`. Task 7 импортирует эти типы и определяет `Segment = { a: Point; b: Point }`, `Bounds = { minCol: number; minRow: number; maxCol: number; maxRow: number }`.
- `locationGeometry.localToPlan(area: MapKnownArea, cell: Point): Point`; `mechanicalToPlan(area, party: Point, cell: Point): Point`; `planToMechanical(area, party: Point, cell: Point): Point`; `knownBounds(areas: MapKnownArea[], level: number): Bounds | null`.
- `locationGeometry.surfaceGeometry(sk: Sketch): { floor: Set<string>; contour: Segment[] }`; `exitSegments(sk: Sketch, exit: SketchExit): Segment[]` — локальные клеточные координаты, без DOM и масштаба.
- `SketchSurface({sk, offset: Point, idPrefix: string})`: SVG-слои без интерактивных объектов и токенов.
- `LocationMapSvg({map: MapLocationPlan, liveSketch: Sketch | null, tokens: Cell<SceneTokenView>[], activeLevel: number, idPrefix: string, onCell?: (areaId: string, planCell: Point) => void, onPassage?: (exit: SketchExit, areaId: string) => void})`: общий SVG для UI и экспорта; callbacks только для текущего участка. `Cell<T>` — существующий из map.ts; col/row токенов здесь ещё относительные механические клетки, renderer преобразует их через liveSketch.party и offset. Task 10 экспортирует чистый `locationTokens(m: MapState): Cell<SceneTokenView>[]` рядом с LocationMapSvg; он адаптирует текущий layoutGrid и используется также экспортером.
- `LocationMap({m: MapState})`: рамка, уровень, zoom/pan, выбор и живой overlay. `PassageBar({exit: SketchExit | MapExit, sketch: Sketch | null, hereId: string, canAct: boolean, onClose})`: подход, взаимодействие и переход.
- Store: `traverseTo(passageRef: string, sourceId: string): void`, `traverseResult(result: MapTraverseResult): void`, `resetForViewer(): void`. `traverse = {busy, requestId, sourceId, asSeat, note, error}`; сброс не отменяет действие на сервере.

## Карта файлов

| Файл | Ответственность |
| --- | --- |
| `app/db/models.py`, `alembic/versions/0022_map_memories.py`, `app/core/world_tx.py` | MapMemory, миграция и участие в guard |
| `app/core/map_memory.py` (новый) | Снимки, персональные grants, запись/чтение наблюдений |
| `app/core/map_projection.py` (новый) | Безопасная композиция и разрешённые связи для зрителя |
| `app/core/map.py`, `app/core/topology.py` | Включение композиции и passage metadata, фильтрация старых коллекций |
| `app/core/world.py`, `app/core/scene_view.py`, `app/tools/runtime.py`, `app/gateway/ws.py` | Те же ограничения для snapshot/scene.updated и плашки разделённого отряда |
| `app/tools/registry.py`, `app/tools/master/places.py`, `app/tools/plot.py`, `app/agents/surveyor.py`, `app/api/campaigns.py` | Наблюдения на границах игровых изменений |
| `app/tools/master/knowledge.py`, `app/core/master_panel.py` | Явное reveal_area и адресация получателей |
| `app/core/layout/transit.py`, `app/gateway/ws.py` | Проверка личного обнаружения, source_id и echo запроса карты |
| `app/gateway/protocol.py`, `web/openapi.json`, `web/src/lib/api.gen.ts` | DTO и сгенерированные типы |
| `web/src/game/map.ts`, `mapPresets.ts`, `web/src/lib/events.ts` | Адаптер, маска, store и реальные handlers |
| `web/src/game/locationGeometry.ts` (новый) | Чистые преобразования и контуры клетки |
| `web/src/game/SketchSurface.tsx` (новый) | Маска, материал, края, рельеф, постоянные детали и проёмы |
| `web/src/game/LocationMap.tsx`, `PassageBar.tsx` (новые), `MapWindow.tsx`, `MapZoom.tsx` | Композиция, viewport и действия текущего героя |
| `web/src/lib/useGameSocket.ts` | Сброс/перезапрос по кампании и playAs |
| `tests/map_memory_helpers.py` (новый) | Общая двухгеройная игровая заготовка |
| `tools/export_location_map_examples.py`, `web/scripts/export-location-maps.mjs`, `web/scripts/render-location-maps.tsx` (новые) | JSON из серверных проекций и SVG тем же рендерером |
| `docs/examples/location-maps/`, `docs/location-maps-delivery2.md` | Проверяемые JSON/SVG-примеры и итог поставки |

## Перед исполнением

Прочитать спеку, этот план и итог поставки 1. Проверить фактический main, дерево и Alembic head: если параллельная ветка уже заняла 0022, выбрать следующий номер и зафиксировать соответствующий `down_revision` в журнале. Не менять историю чужой миграции.

В новом worktree: `uv sync --extra dev`; в `web/` — `npm install`, если зависимостей нет. Baseline: `uv run pytest -q -n auto -rs`, `npm test`, `npm run build`. На базе 8d05a22 было 828 passed / 3 skipped и 128 frontend tests; третий skip — нет `pdftotext`, два — PostgreSQL. Считать skips по причине, не скрывать их. Старые ruff-ошибки в `test_tts`, `test_voicing`, `test_crits_advantage`, `test_game_screen`, `app/core/chat.py`, `app/core/linker.py` не исправлять в этой поставке.

Общий fixture Task 2: `memory_party(client, admin, settings) -> MemoryParty(campaign_id, heads: tuple[dict,dict], hero_ids: tuple[str,str], root_id, village_id, areas: dict[str,str])`. Использовать `party(..., players=2)`, второго FIGHTER создать/submit как в `test_party_split`, дождаться `quiet`, затем `_complex`, `_prepare`, `_areas`; подготовить геометрию пилота для тестов. Оба героя сначала в деревне, поэтому готовность всех участков не является раскрытием. `enter(settings, p, hero: int, area_ref: str)` вызывает настоящий master `move`; `read_memory(settings,p,hero,area_ref)` читает MapMemory. Карта — через существующий `_map(client,p.heads[hero],p.campaign_id)`.

---

### Task 1: Проводной контракт композиции и проходов

**Files:** Modify `app/gateway/protocol.py:342-365,486-542`, `web/openapi.json`, `web/src/lib/api.gen.ts`; Test `tests/test_location_map_contract.py` (новый), `tests/test_contract.py`.
**Interfaces:** Produces DTO из раздела «Контракты». Пока `location_map=None`; запись памяти и рендерер здесь не появляются.

- [ ] **Step 1: Написать failing tests.** `test_location_plan_contract_accepts_offsets_and_memory` валидирует plan с offset `(-6,-4)`, level `-1`, remembered, revision `2`, пустым списком `disclosed_to`; проверяет round trip. `test_typed_map_fields_reject_invalid_values` параметризовать `meaning='fog'`, `kind='lava'`, side `'up'`: `pytest.raises(ValidationError)`. `test_traverse_result_models_failed_finish`:
```python
r = MapTraverseResult.model_validate({"request_id": "t1", "ok": True, "moved": False, "reason": "дверь закрыта"})
assert r.moved is False and r.reason == "дверь закрыта"
```
- [ ] **Step 2: Проверить RED.** `uv run pytest tests/test_location_map_contract.py -q` — нет новых DTO/typed fields.
- [ ] **Step 3: Добавить DTO.** Все новые поля MapState/MapExit optional с совместимым default; не сужать существующие расширяемые строки kind/material у старого эскиза. У MapKnownArea статус prepared допустим только авторизованной серверной проекции.
- [ ] **Step 4: Проверить GREEN и типы.** `uv run python -m app.contract`; `npm run gen:api` из web; `uv run pytest tests/test_location_map_contract.py tests/test_contract.py -q`; `npm run typecheck` — PASS. Не редактировать api.gen.ts руками.
- [ ] **Step 5: Commit.** `git add app/gateway/protocol.py web/openapi.json web/src/lib/api.gen.ts tests/test_location_map_contract.py`; `git commit -m "Контракт карты описывает известные участки и результаты переходов"`.

### Task 2: Персональная память и очищенный снимок

**Files:** Create `app/core/map_memory.py`, `alembic/versions/0022_map_memories.py`, `tests/map_memory_helpers.py`, `tests/test_map_memory.py`; Modify `app/db/models.py:568`, `app/core/world_tx.py:45-64`, `app/core/world.py:353-369` (default map_known).
**Interfaces:** Produces MapMemory, static_snapshot, observe_area, observe_present, known_passages. Grants Task 4 используют этот же PK; nullable snapshot не означает раскрытую область.

- [ ] **Step 1: Написать failing tests.** `test_snapshot_is_personal_and_excludes_entities`, `test_same_observation_does_not_bump_revision`, `test_memory_write_rolls_back_with_world`, `test_map_memory_sqlite_upgrade_downgrade`, `test_map_memory_postgres_sql_render`. Setup — helper выше; A входит в road и явно вызывает observe_area через `_play`, B остаётся в village.
```python
row = read_memory(settings, p, 0, "road")
assert row.revision == 1 and row.snapshot["schema_version"] == 1
assert read_memory(settings, p, 1, "road") is None
assert all(not f.get("entity_id") for f in row.snapshot["geometry"]["features"])
assert "tokens" not in row.snapshot and "blueprint" not in row.snapshot["geometry"]
```
Добавить linked сундук с уникальным ID и скрытую постоянную деталь: ни ID, ни имя сундука/тайной детали не попадают в geometry; колонны нефа остаются стенами. Повтор того же observe_area оставляет revision=1 и updated_at. После rollback нет строки, WGS и world revision не изменены.
- [ ] **Step 2: Проверить RED.** `uv run pytest tests/test_map_memory.py -q` — модели/модуля ещё нет.
- [ ] **Step 3: Реализовать модель и helper.** Snapshot строить из `sketch.of_place` и `project_for_viewer`, затем whitelist постоянных полей; глубокая копия, без связанных Entity features и unplaced metadata. Сохранить приватные connections только у уже видимых проходов. Проверять кампанию, location kind, complex и реальное присутствие, если explicit=False. Создание/обновление пишет inverse и подчиняется world guard; добавить MapMemory в `_BY_CHARACTER`. Сравнивать содержимое без timestamps: no-op не пишет строку. Миграция не backfill'ит visited_by; downgrade удаляет только новую таблицу.
- [ ] **Step 4: Проверить GREEN.** `uv run pytest tests/test_map_memory.py tests/test_world_transactions.py -q`. PostgreSQL SQL — без пересоздания knowledge/characters и дублирования ограничений.
- [ ] **Step 5: Commit.** Добавить названные файлы; `git commit -m "Герой хранит собственный снимок геометрии участка"`.

### Task 3: Наблюдение на игровых границах, а не на чтении карты

**Files:** Modify `app/tools/registry.py:87-120`, `app/tools/master/places.py:272-336,1116-1142`, `app/tools/plot.py:219`, `app/agents/surveyor.py` (фиксация sketch), `app/api/campaigns.py:780-798`; Test `tests/test_map_observation.py` (новый).
**Interfaces:** Consumes observe_area/observe_present. `ToolContext.record` вызывает observe_present перед Event и передаёт общий inverse; helper не создаёт Event и не рекурсирует. Move/relocate отдельно сохраняют исходный участок **до** изменения места.

- [ ] **Step 1: Написать failing tests.** `test_entry_and_departure_capture_only_present_heroes`, `test_geometry_commit_does_not_open_unvisited_area`, `test_present_sketch_edit_refreshes_only_local_memory`, `test_session_start_observes_existing_current_geometry`, `test_departed_memory_does_not_follow_door_or_object_changes`. В последнем сохранить snapshot A, уйти на brook, закрыть двери road и перенести связанный сундук мастером, пока B там; сравнить с глубокой копией:
```python
assert read_memory(settings, p, 0, "road").snapshot == remembered_before
assert read_memory(settings, p, 1, "road").revision > b_revision_before
```
Вернуть A: его снимок получает новое состояние двери, геометрия/IDs WGS остаются прежними. Геометрия vault готова, но ни у A, ни у B нет её snapshot. Бросок/событие без изменения наблюдаемой геометрии не повышает revision.
- [ ] **Step 2: Проверить RED.** `uv run pytest tests/test_map_observation.py -q` — наблюдения ещё не подключены к реальным действиям.
- [ ] **Step 3: Подключить helper.** В move_heroes и relocate_scene сохранить source до ухода (relocate_scene станет async; обновить `enter_current` и вызов в `app/tools/plot.py`). Destination сохраняется после изменения, через record. Общий record покрывает master tools, завершение transit и публикацию геометрии WGS; не менять сетевые части world_generation. Surveyor и session/start, которые фиксируют без ToolContext.record, явно открывают локальный контекст и observe_present перед commit. При старте наблюдать только уже имеющуюся геометрию — не готовить первую сцену. Добавлять generic `map.changed` при реальном изменении памяти; inverse прикреплять к Event или транзакции команды.
- [ ] **Step 4: Проверить GREEN.** `uv run pytest tests/test_map_observation.py tests/test_layout_preparation.py tests/test_layout_transit.py tests/test_layout_turn.py tests/test_party_split.py -q` — PASS; проверить rollback move вместе со snapshot.
- [ ] **Step 5: Commit.** `git commit -m "Наблюдение карты фиксируется вместе со входом и изменениями сцены"` после добавления названных файлов.

### Task 4: Явное раскрытие и личное обнаружение тайных проходов

**Files:** Modify `app/core/map_memory.py`, `app/tools/master/knowledge.py`, `app/tools/master/places.py:706-731`, `app/core/master_panel.py`, `app/core/layout/transit.py:55-102,begin,finish`; Test `tests/test_map_reveal.py` (новый), `tests/test_layout_passages.py`, `tests/test_layout_transit.py`.
**Interfaces:** Produces discover_passage; `RevealAreaArgs(character_ids: list[str], location_id: str, passage_refs: list[str] = [], reason: str)` и tool `reveal_area`: 1–8 героев, до 8 refs длиной 1–64, reason 3–300 символов. `find_passage(..., *, known_passages: frozenset[tuple[str,str]] | None = None)` и `check(..., known_passages=...)`: None сохраняет прежний путь мастера.

- [ ] **Step 1: Написать failing tests.** `test_reveal_area_opens_only_named_heroes`, `test_reveal_area_never_prepares_missing_geometry`, `test_reveal_passage_does_not_open_other_end`, `test_discovery_is_checked_before_error_and_ambiguity`, `test_finish_rechecks_personal_passage_access`. A в sacristy, B у другого конца/в иной группе. После edit_sketch reveal у A известен p_vault, у B нет; B угадывает p_vault — тот же ответ, что p_missing:
```python
assert hidden_result["error"] == missing_result["error"] == "отсюда нет такого прохода"
assert read_memory(settings, p, 0, "vault").snapshot is None  # grant без геометрии
```
Явно reveal_area для A выдаёт vault snapshot без перемещения и без новых WGS. Переданный чужой campaign/не location/не готовый участок отклоняется и не меняет ни grants, ни world revision. Слух через reveal_knowledge не открывает геометрию.
- [ ] **Step 2: Проверить RED.** `uv run pytest tests/test_map_reveal.py -q` — отсутствует tool и персональная проверка.
- [ ] **Step 3: Реализовать раскрытие.** Подтвердить всех получателей/refs до записи, использовать inverse. Для явно обнаруженного секретного passage сохранить grants обоих концов, но snapshot только выбранного открываемого участка; оставить общую дверь и immutable blueprint. Reveal/hide сохраняют прежний live hidden для совместимости; reveal_area с passage_refs снимает live hidden явно, не создаёт связь. `edit_sketch reveal` выдаёт grants только присутствующим у выбранной стороны. Player begin/finish заново читают grants в своей транзакции; фильтруют недоступные секретные candidates **до** подсчёта неоднозначности и до текста о состоянии двери. Неизвестный passage не запускает request_area. Tool Event — hidden; персональные knowledge notices — только адресатам, broadcast map.changed без ID тайного участка.
- [ ] **Step 4: Проверить GREEN.** `uv run pytest tests/test_map_reveal.py tests/test_layout_passages.py tests/test_layout_transit.py tests/test_master_panel.py -q` — PASS. В панель добавить reveal_area в scene с IDs героев/локаций и русскими описаниями полей.
- [ ] **Step 5: Commit.** `git commit -m "Мастер раскрывает геометрию и тайные проходы выбранным героям"`.

### Task 5: Безопасная серверная композиция и старые коллекции карты

**Files:** Create `app/core/map_projection.py`, `tests/test_location_map.py`, `tests/test_map_scene_privacy.py`; Modify `app/core/map.py:113-218,285-420`, `app/core/topology.py`, `app/core/world.py:load_world`, `app/core/scene_view.py`, `app/tools/runtime.py:154-265`, `app/gateway/ws.py:_map,_scene`, `tests/test_map.py`, `tests/test_layout_topology.py`.
**Interfaces:** Produces location_plan, opened_areas и World.map_known. `LocationExit` получает optional passage_ref/kind/state/width/cells; прежние четыре позиционных поля сохраняются. `visible_scene` получает optional `known_places: frozenset[str]`, сохраняет его в VisibleScene вместе с viewer_hero_id; `scene_payload` использует это для неизвестных complex groups. В map.state echo optional request_id/as_seat из map.get; отправка вне read session.

- [ ] **Step 1: Написать failing tests.** `test_map_contains_current_and_personal_remembered_areas`, `test_unknown_area_is_absent_from_entire_packet`, `test_map_read_does_not_write_or_prepare`, `test_master_sees_prepared_plan_and_disclosure`, `test_viewer_without_hero_has_no_party_union`. A побывал на road/brook, B только в village:
```python
packet = _map(client, p.heads[0], p.campaign_id)
assert {a["id"] for a in packet["location_map"]["areas"]} == {p.areas["road"], p.areas["brook"]}
assert p.areas["vault"] not in json.dumps(packet, ensure_ascii=False)
assert p.areas["narthex"] not in json.dumps(packet, ensure_ascii=False)
assert all(not f.get("entity_id") for a in packet["location_map"]["areas"] for f in a["sketch"]["features"])
```
Unknown exit остаётся с passage_ref, но to/beyond=None; нет неизвестных уровней/bounds. Снимок после ухода не меняется от live root doors, текущих Entity и `_mentioned_ids`. Два map.get подряд не меняют row revision/count, WGS и campaign.world_revision. Master DTO содержит prepared preview и disclosed_to, player DTO — никогда. `test_split_scene_does_not_name_unknown_complex_area` проверяет initial snapshot и scene.updated для B после входа A в vault: строка группы содержит names, но id/place=None; ID/имени vault нет во всей scene. Master и герой, лично знающий этот участок, получают разрешённую подпись. `test_spectator_has_no_live_complex_union` не выдаёт содержимое чужих complex areas зрителю без героя. Обычные места из test_party_split сохраняют нынешние подписи.
`test_failed_tool_does_not_leave_opened_area_in_world_cache` проверяет откат savepoint: после неуспешной команды reload_world не оставляет область в map_known и следующая рассылка не раскрывает её.
- [ ] **Step 2: Проверить RED.** `uv run pytest tests/test_location_map.py -q` — location_map отсутствует/граф раскрывает соседний ID.
- [ ] **Step 3: Собрать проекцию.** Batch-read MapMemory только своего героя; current area — очищенный live snapshot, remembered — исключительно сохранённый JSON, grants-only строки не показывать. Использовать одну blueprint cache на запрос. Ребро/to разрешать только к personally opened area, имя назначения — из её snapshot; не смотреть её live name/state. Из legacy places/links/near для complex areas убрать автодобавление неизвестных соседей/тайных концов. Knowledge/упоминание даёт сведения обычного графа, но не открывает complex geometry. Для чужого героя в отдельной группе не выдавать ни geometry, ни актуальный overlay. Master full preview строится чистым build_area без phase activation; ручной sketch имеет приоритет. Если ручной sketch не соответствует размеру области blueprint и перекрывает соседей, сохранить его и вернуть location_map=None с текущим legacy Around; не исправлять sketch/offset молча. Добавить regression такого ручного эскиза. Для книги/обычного эскиза location_map=None, прежний путь остаётся.
  Загрузить IDs открытых участков по персонажам одним запросом в load_world, обновлять cache при новых наблюдениях. Runtime scene_public/scene_views передают в visible_scene персональный known_places; ws._scene делает то же для initial snapshot. У группы в неизвестном complex area оставить публичные names, но id/place=None (PartyPart уже допускает null). Зритель без героя не получает live entities/координаты этих участков. Обычный граф и мастерская проекция не меняются; никакие дополнительные запросы не открываются внутри сетевой рассылки.
- [ ] **Step 4: Проверить GREEN.** `uv run pytest tests/test_location_map.py tests/test_map_scene_privacy.py tests/test_map.py tests/test_layout_topology.py tests/test_party_split.py tests/test_adventure.py tests/test_modules.py tests/test_world_objects.py -q` — PASS. Проверить packet через MapState.model_validate.
- [ ] **Step 5: Commit.** `git commit -m "Карта объединяет только участки, открытые этому герою"` после добавления названных файлов.

### Task 6: Клиентский адаптер, маска пола и реальные клетки проходов

**Files:** Modify `web/src/game/map.ts:115-234,570-603`, `mapPresets.ts:52-61`, `map.test.ts`, `mapPresets.test.ts`; Test `web/src/game/locationTypes.test.ts` (новый).
**Interfaces:** Consumes generated DTO; produces Point/MapKnownArea/MapLocationPlan из общего контракта и `exitCells(sk: Sketch, exit: SketchExit): Point[]` в относительных механических координатах. `exitCell` для старого эскиза не менять.

- [ ] **Step 1: Написать failing tests.** `mask outside cannot be selected`, `wide exit uses stored inner cells`, `gate and edge keep their own presets`, `unknown future material falls back without changing floor`, `legacy sketch frame is unchanged`.
```ts
const sk: Sketch = {shape:"room",cols:3,rows:3,party:[1,1],walls:[],exits:[],features:[],mask:["###","#..","#.."]};
expect(sketchFrame(sk).allowed(-1,-1)).toBe(false);
expect(sketchFrame(sk).allowed(0,0)).toBe(true);
expect(exitCells(sk,{name:"Край",kind:"edge",side:"e",at:1,width:2,cells:[[2,1],[2,2]]})).toEqual([[1,0],[1,1]]);
```
Обе клетки широкого выхода лежат на допустимом полу; тест не использует cells за пределом маски.
- [ ] **Step 2: Проверить RED.** `npm test -- src/game/map.test.ts src/game/locationTypes.test.ts src/game/mapPresets.test.ts` — нет fields/helper, маска игнорируется.
- [ ] **Step 3: Обновить адаптер.** Описать новые поля через generated types/ограниченные визуальные enums без cast к any. `mapForDisplay` нормализует и location_map, не выкидывает mask/edges/terrain. `sketchFrame.allowed` исключает mask '#', стены и занятые features; старое отсутствие mask — прямоугольник. Gate/edge получают разные русские подписи и подходящие glyphs, без подмены edge узкой дверью. Не менять источник точных механических позиций.
- [ ] **Step 4: Проверить GREEN.** Те же Vitest-файлы и `npm run typecheck` — PASS; старые map tests по exact/book/schematic placement проходят.
- [ ] **Step 5: Commit.** `git commit -m "Клиент карты читает маску, широкие проходы и рельеф"`.

### Task 7: Чистая геометрия композиции и контуров

**Files:** Create `web/src/game/locationGeometry.ts`, `locationGeometry.test.ts`.
**Interfaces:** Produces преобразования, bounds, surfaceGeometry/exitSegments из общего контракта; SVG units — клетки, pixel scale применяется только renderer.

- [ ] **Step 1: Написать failing tests.** `negative offsets preserve mechanical coordinates`, `levels never share bounds`, `bounds use disclosed areas only`, `mask contour includes holes`, `nonrectangular entrance cuts actual inner boundary`.
```ts
expect(localToPlan(area, [3,1])).toEqual([-3,-3]); // area.offset=[-6,-4]
expect(mechanicalToPlan(area,[2,2],[1,-1])).toEqual([-3,-3]);
expect(planToMechanical(area,[2,2],[-3,-3])).toEqual([1,-1]);
```
Для двух полей 6×6 с offsets (0,0)/(6,0) общая граница x=6 совпадает; для level=-1 bounds не включают level=0. Контур rect 3×2 — внешние стороны; L-mask и отверстие — границы именно клеток, не bbox. Для выхода L-формы cells=[(3,2)], side=n, opening проходит от (3,2) до (4,2), а не по y=0.
- [ ] **Step 2: Проверить RED.** `npm test -- src/game/locationGeometry.test.ts` — модуля нет.
- [ ] **Step 3: Реализовать helpers.** Граница пола — стороны клеток с отсутствующим соседом, детерминированный порядок и слияние только коллинеарных смежных отрезков. Не строить контур из названия shape. Opening из side и каждой cells; fallback для legacy — at/width на стороне bbox. knownBounds фильтрует level и считает только полученные areas. Не брать root blueprint bounds/тайные уровни и не вращать геометрию.
- [ ] **Step 4: Проверить GREEN.** `npm test -- src/game/locationGeometry.test.ts src/game/map.test.ts` и `npm run typecheck` — PASS.
- [ ] **Step 5: Commit.** `git commit -m "Клетки участков образуют устойчивый план и физические контуры"`.

### Task 8: SVG-поверхность, материалы и открытая местность

**Files:** Create `web/src/game/SketchSurface.tsx`, `SketchSurface.test.tsx`; Modify `MapWindow.tsx:134-317` (геометрия текущего эскиза), `MapGlyph.tsx` только если нужен новый семантический glyph.
**Interfaces:** Consumes surfaceGeometry/exitSegments и fixed enums; produces SketchSurface. У компонента нет маршрутов, Entity actions и токенов.

- [ ] **Step 1: Написать failing tests.** `floor is clipped to mask`, `open continuation has no wall`, `obstacle edge draws only its segment`, `wide passage cuts full opening`, `bridge overlays stream`, `two surfaces do not share SVG ids`. Проверять DOM geometry/attributes, не полный string snapshot:
```ts
expect(svg.querySelectorAll("image,foreignObject")).toHaveLength(0);
expect(svg.querySelector('[data-edge-meaning="continuation"][data-wall="true"]')).toBeNull();
expect(svg.querySelector('[data-terrain="bridge"]')).not.toBeNull();
```
Два instance с разными idPrefix не имеют duplicate pattern/clip IDs. Fill/контур для L-mask не рисуют запрещённую клетку; indoor opening шириной 2 клетки удаляет обе части стены.
- [ ] **Step 2: Проверить RED.** `npm test -- src/game/SketchSurface.test.tsx` — renderer отсутствует/старый SketchLayer рисует прямоугольник поля.
- [ ] **Step 3: Реализовать слои.** Порядок: локальные defs/clip; пол с pattern stone/earth/grass/water/wood; road/path; stream; bridge; grid; физические стены/детали; проёмы; подписи. Indoor — толстый контур с openings и границами колонн. Outdoor — только obstacle как физическая ограда, continuation без стены, boundary как маркер перехода; не обводить bbox сплошной стеной. Рельеф clip'ить полом, мост поверх ручья; pattern phase привязать к общим координатам, чтобы seam соседей не ломал узор. Пятна и штрихи — локальный SVG, theme colors с fallback, React escaping текстов, namespace IDs через idPrefix. Старый SketchLayer использует ту же поверхность, но сохраняет существующие handlers живых features/exits и StepBar.
- [ ] **Step 4: Проверить GREEN.** `npm test -- src/game/SketchSurface.test.tsx src/game/map.test.ts src/game/BookMap.test.ts`; `npm run typecheck` — PASS. Механика клеток от материалов не меняется.
- [ ] **Step 5: Commit.** `git commit -m "SVG рисует материалы, маску и свободные края участка"`.

### Task 9: Состояние перехода, корреляция и границы зрителя

**Files:** Modify `web/src/game/map.ts:235-347`, `map.test.ts`, `web/src/lib/events.ts`, `web/src/lib/useGameSocket.ts:72-97`; Test `web/src/game/mapTraversal.test.ts`, `web/src/lib/useGameSocket.test.ts` (новые).
**Interfaces:** Produces traverseTo/traverseResult/resetForViewer, текущий pending request для map.get. Request scope — campaign и `useGame.playAs`; map.get и map.step также передают as_seat при замещении.

- [ ] **Step 1: Написать failing tests.** `one click sends one traverse`, `stale result does not release another request`, `failed finish shows reason`, `changing actor clears remembered geometry`, `disconnect never resends traversal`, `old map reply is ignored`.
```ts
expect(send).toHaveBeenCalledWith("map.traverse",expect.objectContaining({passage_ref:"p_cell",source_id:"hall",request_id:expect.any(String)}));
expect(useMapWindow.getState().data?.here?.id).toBe("hall"); // до подтверждения остаёмся здесь
```
Повтор while busy не посылает второй event. ok=True/moved=False показывает reason и перезапрашивает карту. Ответ с другим request_id не изменяет pending. После resetForViewer data=null, pending=null; response прежней карты не принимается. map.get response сверять по request_id и as_seat; scope ожидающего traverse хранит asSeat без необходимости нового поля в серверном result.
- [ ] **Step 2: Проверить RED.** `npm test -- src/game/mapTraversal.test.ts src/game/map.test.ts` — нет действия/корреляции.
- [ ] **Step 3: Реализовать store.** Отдельная последовательность `tN` и `mN`, busy до своего ответа; step и traverse взаимно исключаются. Никакого локального перемещения/добавления area/генерации. `map.traverse.result` зарегистрировать в events.ts как реальный handler. На ошибке/отказе/success — читаемый русский status, запрос актуального map.state; не показывать технические фазы/коды WGS. При разрыве снять UI ожидание с «Связь прервалась; проверьте положение героя», не повторять команду автоматически. На смене campaign/playAs сбросить данные и запросы, затем запросить карту нужного героя; hook cleanup не оставляет подписок. Старые generic scene updates лишь обновляют карту с тем же viewer scope.
- [ ] **Step 4: Проверить GREEN.** `npm test -- src/game/mapTraversal.test.ts src/game/map.test.ts src/lib/useGameSocket.test.ts`; `npm run typecheck` — PASS.
- [ ] **Step 5: Commit.** `git commit -m "Клиент подтверждает переход серверным ответом и разделяет память героев"`.

### Task 10: Единый план, уровни, память и живой overlay

**Files:** Create `web/src/game/LocationMap.tsx`, `LocationMap.test.tsx`, `MapZoom.test.tsx`; Modify `MapWindow.tsx:905-968`, `MapZoom.tsx`.
**Interfaces:** Produces LocationMapSvg и LocationMap. `MapWindow` выбирает LocationMap в around, когда location_map != null; иначе прежний Around/BookMap.

- [ ] **Step 1: Написать failing tests.** `current and remembered areas share offsets`, `only current area owns live tokens`, `remembered surface has no game actions`, `level picker contains disclosed levels only`, `viewport does not drift after reveal`, `current cell sends relative step`.
```ts
expect(svg.querySelectorAll('[data-area-status="remembered"]')).toHaveLength(1);
expect(screen.queryByRole("button",{name:/уровень -1/i})).toBeNull(); // его нет в разрешённом packet
```
Клик по remembered geometry не вызывает send/inspect/insert; тёмный участок не имеет списка существ/предметов. Точный токен [1,-1] при party=[2,2], offset=[-6,-4] рисуется в [-3,-3]; выбранная плановая клетка [-3,-3] отправляет map.step cell=[1,-1]. После добавления известной области слева тот же world point остаётся под прежней точкой viewport. Pan >4 px не вызывает floor/passage action.
- [ ] **Step 2: Проверить RED.** `npm test -- src/game/LocationMap.test.tsx src/game/MapZoom.test.tsx` — компонентов нет.
- [ ] **Step 3: Собрать композицию.** Area groups translate(offset); один масштаб клетки, активный level по умолчанию — текущий. Remembered — приглушённая поверхность/подписи и дата наблюдения, pointer events/keyboard actions выключены; prepared — только master styling. Текущая поверхность берётся из очищенного live geometry, а Entity features и токены — отдельно из текущих sketch/scene_view/around; не рисовать их дважды. `layoutGrid` сохраняет exact/book/schematic, для composition переводит лишь текущий overlay в общий план. Кнопки памяти переключают обзор, но не current here. Bounds только известных областей; сохранить camera для root_id/level в плановых координатах, компенсировать изменение minima, не подгонять под героя при каждом событии. Master отдельно показывает disclosed_to и секреты; без собственного героя не посылает player movement.
- [ ] **Step 4: Проверить GREEN.** `npm test -- src/game/LocationMap.test.tsx src/game/MapZoom.test.tsx src/game/BookMap.test.ts src/game/map.test.ts`; `npm run build` — PASS.
- [ ] **Step 5: Commit.** `git commit -m "Открытые участки видны на одном плане, память отделена от текущей сцены"`.

### Task 11: Подход и переход через проход в интерфейсе

**Files:** Create `web/src/game/PassageBar.tsx`, `PassageBar.test.tsx`, `tests/test_map_traverse_source.py`; Modify `MapWindow.tsx` (current/ordinary exits), `LocationMap.tsx`, `app/gateway/ws.py:_traverse`, `app/core/layout/transit.py:traverse`.
**Interfaces:** Consumes exitCells, store traverseTo, PassageBar props. `transit.traverse(..., *, expected_source_id: str | None = None)`; ws validates optional source_id (строка 1–64) и передаёт его.

- [ ] **Step 1: Написать failing tests.** UI: `unknown destination can be traversed without its id`, `closed passage offers interaction not optimistic opening`, `wide edge approaches all real cells`, `outside approach works without sketch`, `memory passage cannot traverse`. Server: `test_stale_source_cannot_traverse_back_through_same_passage` — герой уже на другой стороне p_brook, запрос указывает прежний source; никакого обратного движения/нового request_area.
```ts
expect(screen.getByText("Неизведанное место")).toBeTruthy();
expect(send).toHaveBeenCalledWith("map.traverse",expect.objectContaining({passage_ref:"p_brook",source_id:"road"}));
expect(send.mock.calls.at(-1)?.[1]).not.toHaveProperty("destination_id");
```
- [ ] **Step 2: Проверить RED.** `npm test -- src/game/PassageBar.test.tsx`; `uv run pytest tests/test_map_traverse_source.py -q` — нет панели/source guard.
- [ ] **Step 3: Подключить действия.** Passage selection показывает имя, тип, известное состояние, ширину в футах и только разрешённое название назначения. «Подойти» — map.step near по всем реальным cells; для внешнего подхода без cells не выдумывать позицию. «Взаимодействовать»/открывание — текст через useDraft и существующий игровой поток; «Перейти» — map.traverse, доступно лишь текущему управляемому герою при open и отсутствии pending. Во время запроса «Готовлю проход…», без раскрытия WGS. На смене here/level/viewer отменить выбор; mouse и keyboard запускают одинаковое действие. Source guard проверять **в первой транзакции**, до approach/request_area; повторная проверка finish остаётся. Closed/locked, out-of-turn, incapacitated, manual sketch и ошибки — решает сервер, клиент не обходится teleport/move. Выход без passage_ref сохраняет старое взаимодействие, а не притворяется server traverse.
- [ ] **Step 4: Проверить GREEN.** `npm test -- src/game/PassageBar.test.tsx src/game/mapTraversal.test.ts src/game/LocationMap.test.tsx`; `uv run pytest tests/test_map_traverse_source.py tests/test_layout_transit.py tests/test_layout_turn.py -q` — PASS.
- [ ] **Step 5: Commit.** `git commit -m "Игрок подходит к проходу и переходит с карты по серверной проверке"`.

### Task 12: Настоящие SVG-примеры из серверных данных

**Files:** Create `tools/export_location_map_examples.py`, `web/scripts/export-location-maps.mjs`, `web/scripts/render-location-maps.tsx`, `web/src/game/locationExamples.test.tsx`, `docs/examples/location-maps/README.md`, JSON/SVG рядом; Modify `web/package.json`, `.gitignore` (только временный SSR output).
**Interfaces:** Consumes location_plan, pilot_intent/build_area и LocationMapSvg. Produces `temple-known.json/.svg`, `field-stream-bridge.json/.svg`, `hero-memory.json/.svg`.

- [ ] **Step 1: Написать failing tests.** `exported fixture retains real terrain joints`, `export uses same floor and offset as interaction map`, `memory example excludes unknown and live entities`. JSON валидируется generated DTO/MapState, пример — тот же renderer, не вручную написанный path. Проверять буквальный стык полей по x=12, road rows 3/4, stream row 7; bridge присутствует; неизвестных vault/crypt IDs нет в player example. SVG parsed DOM содержит masked contour и remembered area, не image/foreignObject и не actor token другого участка.
- [ ] **Step 2: Проверить RED.** `npm test -- src/game/locationExamples.test.tsx` — fixtures/renderer export отсутствуют.
- [ ] **Step 3: Реализовать экспорт.** Python создаёт отдельную временную SQLite-кампанию из pilot_intent и выполняет реальные наблюдения/party_map для двух героев; не читает боевую БД и не вызывает LLM. При создании временной кампании задать стабильные demo IDs/seed; timestamps нормализовать **после** безопасной серверной проекции, а не заменять policy. Для храмового примера изменить в замысле sacristy.shape на circle до propose/validate/build_area и открыть её герою: пример действительно содержит mask. JSON — полный MapState, сохраняется в docs/examples. Node launcher вызывает установленный Vite для SSR-сборки render-location-maps.tsx во временный `web/.map-examples-build/`; renderer через react-dom/server экспортирует LocationMapSvg с явным idPrefix/level, mapForDisplay и locationTokens, затем standalone SVG с theme defaults. Без новых зависимостей, без обхода чистого core renderer и без изменения app/web/dist. `npm run map:examples` запускает launcher. README связывает JSON с SVG, enum материалов, команды и ожидаемые landmarks.
- [ ] **Step 4: Проверить GREEN и воспроизводимость.** `uv run python tools/export_location_map_examples.py`; в web `npm run map:examples`, `npm test -- src/game/locationExamples.test.tsx`; повторить экспорт — git diff examples пуст. Визуально открыть три SVG и проверить читаемость контуров, широкого края, моста и приглушённой памяти.
- [ ] **Step 5: Commit.** `git commit -m "Примеры SVG храма и поля строятся из серверной геометрии и личной памяти"`.

### Task 13: Пилот туда-обратно, итог поставки и полный прогон

**Files:** Create `tests/test_location_maps_delivery2.py`, `docs/location-maps-delivery2.md`, `web/src/game/locationPilot.test.tsx`; Modify `docs/README.md` (ссылка на итог).
**Interfaces:** Consumes все предыдущие задачи. Итог описывает публичный DTO, память, разрешённые точки записи, migration и границу поставки 3.

- [ ] **Step 1: Написать failing acceptance tests.** `test_two_heroes_field_temple_secret_and_return`, `test_preparation_failure_does_not_disclose_destination`, `test_reload_retains_personal_memory_without_new_generation`; UI `pilot traverses by click and displays both visited areas` и `door closed while preparing never paints destination as current`. A: road → narthex → nave → chapel → назад → brook; B остаётся в другом месте, затем раскрывается только выбранная area. Сравнить packet по героям, snapshot revisions, WGS count и blueprint IDs; p_vault для B отвечает как missing. После закрытия во время подготовки destination geometry ready, но у отказавшегося героя snapshot отсутствует. Новый socket/page reload восстанавливает снимки из БД, не повторяет prepare/traverse.
- [ ] **Step 2: Проверить RED.** Запустить только новые acceptance tests; если уже проходят, проверить, что они не обходят UI store/server projection прямой подстановкой here и не сравнивают результат helper с самим собой.
- [ ] **Step 3: Закрыть интеграционные разрывы и написать итог.** Зафиксировать решения по старым visited_by, тайным grants, неизвестным концам, источникам ревизии, as_seat и readonly map.get. Не улучшать отложенные коллизии feature IDs/provider и не включать задачи поставки 3. Указать примеры SVG и команды воспроизведения.
- [ ] **Step 4: Финальная проверка.** `uv run python -m app.contract --check`; `uv run pytest -q -n auto -rs`; ruff check/format --check только изменённых Python-файлов; в web `npm test`, `npm run build`, `npm run map:examples`; `git diff --check`. Отдельная регрессия: `uv run pytest tests/test_sketch.py tests/test_grid.py tests/test_world_objects_reach.py tests/test_adventure.py tests/test_modules.py tests/test_layout_pilot.py tests/test_layout_turn.py -q`. Все тесты PASS, дополнительные skips объяснены; старые количества — baseline, а не потолок. Перед завершением пройти пять Review Focus и проверить, что каждый имеет зелёный тест. Выполнить независимое ревью всей ветки с акцентом на приватность всего packet, CAS/inverse, grants до ambiguity и состояния reconnect.
- [ ] **Step 5: Commit.** `git commit -m "Пилот подтверждает личную память и SVG-переходы второй поставки карт"`. Merge/PR только по отдельному решению пользователя; не удалять worktree без его согласия.

---

## Порядок и зависимости

`1 DTO → 2 memory → 3 observation → 4 discovery → 5 projection`.
`1 DTO → 6 adapter/mask → 7 geometry → 8 surface`.
`1 + 5 + 6 → 9 store`; `5 + 7 + 8 + 9 → 10 composition`; `4 + 9 + 10 → 11 passages`.
`5 + 8 + 10 → 12 examples`; `3–12 → 13 pilot`.

Задачи разделены по проверяемым результатам, но server/client DTO и snapshot/knowledge тесно связаны. При inline исполнении проходить зависимости последовательно и вести журнал решений; при subagent-driven выдавать каждому исполнителю спеку, его Interfaces и ограничения, а не только имя компонента.

## Проверка покрытия плана

- §4: координаты/levels/revisions → Tasks 1, 2, 7, 10.
- §5: свободные края, широкие endpoints, стыки дороги/ручья и мост → Tasks 6–8, 11, 12.
- §6: персональная память, явное раскрытие, текущий/remembered/unknown, секреты, отсутствие живых объектов в памяти → Tasks 2–5, 9, 10, 13.
- §7: общий SVG, материалы, MapGlyph/visual_key, клетки и интерфейс перехода → Tasks 6–12.
- §8: запись до публикации, повторная проверка, отсутствие записи/подготовки при чтении, CAS и восстановление поставки 1 → Tasks 2–5, 9, 11, 13. Лимиты/стоимость LLM и подготовка вперёд — поставка 3.
- §9/§10: старые эскизы/книга, пилот, настоящие SVG из того же источника → Tasks 5, 6, 8, 12, 13.

План проходит inline self-review: имена DTO/helper/store согласованы между задачами; неизвестные bounds и переходы по памяти не оставлены на решение рендерера; новые наблюдения и grants имеют владельца транзакции. Перед кодом инженер перечитывает спеку и проверяет фактический head/migration; этот документ сам по себе не разрешает слияние и публикацию.
