# Maps and Narration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Довести ориентацию, память и повествование в уже работающей игре.

**Architecture:** Карта показывает знания и окружение без игровых команд. Рассказ из второго узла получает более полный публичный контекст; механические решения остаются в сохранённых исходах.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic 2, SQLAlchemy async, SQLite/PostgreSQL, pytest; React 19, TypeScript, React Query, Zustand, Vitest.

**Spec:** [Approved design](../specs/2026-10-23-universal-creative-studio-design.md)
**Index:** [Node order and shared contracts](2026-10-23-universal-creative-studio.md)

## Исследовательская часть перенесена в проект2А — 2026-10-25

В [дизайне2А](../specs/2026-10-25-exploration-magic-design.md) раньше реализуются необходимые части Task23: подтверждённые изменения мира вместо свободных строк механических последствий, состояние объектов/наблюдателей для небоевых действий, доступные герою знания и художественное описание из сохранённых фактов. Полная задача23, расширенный retrieval/голосовые проверки и боевая приватность не считаются выполненными этим переносом.

Task22 (полная карта), оставшаяся часть Task23 и полный сквозной Task24 сохраняются в этом узле. В2А появляется собственная небоeвая приёмка — она не подменяет проверку боя/XP/карты из Task24. Существующие уже выполненные правки прозы, ссылок и знания сохраняются и получают новые фактические источники.

## Global Constraints

- 6 характеристик; 5 энергий; HP = 10 + CON + 6*(L-1); класс не требуется.
- Любой герой создаётся L1/xp0. Стартовый набор15,14,13,12,10,8: каждое значение один раз.
- Редактируется только базовый герой вне кампании: ручная перестановка и чат проходят одну серверную проверку. Готовый герой кампании изменяется только через игровые события и штатное распределение новых очков.
- Catch-up выполняется после создания/добавления игровой копии, распределение очков — в самой игре. Библиотечный оригинал всегда остаётся L1.
- Рост даёт 2 очка за уровень, оба допустимо вложить в одну характеристику; игрового предела уровня нет.
- Один игровой шаг допускает ход одного врага; повтор не дублирует расход, урон, эффекты, XP или освоение.
- Каждому участнику полная одинаковая награда. Авторская версия, прохождения и библиотечный герой изолированы.
- Новая ветка и новая БД в начале; старые игровые данные не переносим и не архивируем. Данные, созданные после начала новой разработки, сохраняются при всех следующих узлах.
- Сохраняем авторизацию, секретность, поиск/память, учёт LLM и аудио. Чужие незакоммиченные изменения не удаляем.
- Обычные тесты используют ScriptedLLM, без живых моделей. После изменения кода выполнить graphify update .

## Review Focus

Игровой клик/геометрия и секреты — Task22; повествование против сохранённых фактов — Task23; два запуска и восстановление — Task24.

## Проверка результата узла

Исследовать мир → осмотреть карту без перемещения → применить известное умение → получить подробный рассказ с сохранёнными последствиями → изменить мир в одном прохождении → убедиться в изоляции второго.
Следующий узел начинается после зелёных проверок этого узла и просмотра его работающего сценария пользователем. Это проверка результата, а не требование создавать новое согласование каждой технической детали. Общая уборка старого кода не блокирует демонстрацию готовых сценариев.

### Task 22: Orientation-only map

**Files:** Modify web/src/game/{LocationMap,MapWindow,BookMap,PassageBar}.tsx, app/core/{map,map_projection,reach,positions}.py, app/tools/{movement,grapples}.py, app/tools/master/{places,travel,checks,entities}.py; Test tests/test_universal_map.py, web/src/game/LocationMap.test.tsx.
**Interfaces:** Saved location/knowledge projection retains known entities/places and optional visual coordinates. Existing resolve_action already accepts no-cell actions from Node2; map does not mutate game state.

- [x] **Step 1: Write failing tests.** Ground/passage click: assert moveRequest not called; pan/zoom/entity inspection work. assert exchange_after_inspection == exchange_before. Secret/foreign objects hidden; valid move/action without cell accepted.
- [x] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_map.py -q; npm --prefix web test -- src/game/LocationMap.test.tsx. Expected missing new contract or required behavior, not an environment failure.
- [x] **Step 3: Implement.** Remove onCell/onPassage game commands and movement draft coupling, keep visual geometry optional. Audit leftover mandatory feet/cell/line-of-sight checks in active universal paths; retain world membership and master-confirmed reachability.
- [x] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_map.py -q; npm --prefix web test -- src/game/LocationMap.test.tsx. Author map inspection/generation still usable; missing coordinates do not create invisible fictional walls. Existing adventures and known location state survive.
- [x] **Step 5: Commit.** feat: present maps as non-tactical scene orientation. Stage only this task's files.

### Task 23: Richer narration, public context and memory

**Files:** Modify app/agents/master/{narration,helpers,finish,prompt_context}.py, app/agents/prompts/{narrate,narrator_system}.j2, app/gateway/protocol.py; Test tests/test_universal_narration.py.
**Interfaces:** Extend Task10 public_turn_view(ctx,audience)->dict. Existing narrator/retrieval/voice consume public outcomes and relevant memory; no new mechanics executor.

- [x] **Step 1: Write failing tests.** test_public_narration_excludes_saves — assert 'death_failures' not in payload. Vine resisted bind: damage present, cannot_move absent. Context preserves relevant world/hero facts and excludes other hero's secrets. Retry narration never adds a second spend/tick.
- [x] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_narration.py -q. Expected missing new contract or required behavior, not an environment failure.
- [x] **Step 3: Implement.** Supply scene details, dialogue, atmosphere and relevant retrieved facts rather than impose terse2–4 sentences. Preserve player agency, distinguish denial/miss/damage/resistance and unknown facts. Private adaptations/rescue counters never enter narrator/voice payload. Keep mechanics commit separate from text publication.
- [x] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_narration.py -q. Reconnect before publication, changed audience, privacy in voice and no hidden automatic rest. ScriptedLLM proves filtering/context; assess actual literary quality separately in a configured manual run.
- [x] **Step 5: Commit.** feat: enrich public narration with grounded world memory. Stage only this task's files.

### Task 24: Whole-adventure node acceptance

**Files:** Create tests/test_universal_playthrough.py, web/src/pages/UniversalPlaythrough.test.tsx; Modify app/core/views.py or frontend reducers only for reproduced integration defects.
**Interfaces:** Consumes all existing endpoints and view contracts; no new gameplay function.

- [x] **Step 1: Write failing tests.** Author accepted→two launches→library copy→invented ability→combat→effects/potion→XP300 each→level choices→map inspection→reconnect. Assert original/second game unchanged and all receipts replay once. Player and voice payload exclude foreign/private secrets.
- [x] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_playthrough.py -q; npm --prefix web test -- src/pages/UniversalPlaythrough.test.tsx. Expected missing new contract or required behavior, not an environment failure.
- [x] **Step 3: Implement.** Compose existing services in scenario fixtures; use real migrations and lifespan for at least one path. Fix only demonstrated integration gaps in their owning modules, not a new feature set.
- [ ] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_playthrough.py -q; npm --prefix web test -- src/pages/UniversalPlaythrough.test.tsx. Run node demo in browser, retain a created hero/campaign across upgrade from Node1 schema through current head. Record usability and prose observations before final cleanup.
- [x] **Step 5: Commit.** test: verify the complete persistent universal adventure. Stage only this task's files.

Implementation and verification: [Node5 report](../../universal-maps-and-memory.md). Active-module task mapping: [execution plan](2026-10-26-universal-maps-and-memory.md). Local runtime selection remains a separate delivery preference because the running container was moved to a parallel combined worktree.

Task24 Step4 automated checks are GREEN (310 backend /385 frontend); browser demonstration of this branch awaits runtime selection. No gameplay actions were sent to the existing combined runtime.
