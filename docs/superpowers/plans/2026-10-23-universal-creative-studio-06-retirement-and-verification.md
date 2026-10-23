# Retirement and Final Verification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Удалить недействующий старый режим и проверить готовую игру целиком без повторного сброса данных.

**Architecture:** Универсальный runtime подключён во втором узле, схема развивается с первого. Здесь нет переключения на новую игру впервые: только аудит остаточных зависимостей, документация и итоговая проверка.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic 2, SQLAlchemy async, SQLite/PostgreSQL, pytest; React 19, TypeScript, React Query, Zustand, Vitest.

**Spec:** [Approved design](../specs/2026-10-23-universal-creative-studio-design.md)
**Index:** [Node order and shared contracts](2026-10-23-universal-creative-studio.md)

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

Скрытые legacy imports/route fallback — Task25; потеря созданных на узлах данных, настоящий startup и секретность — Task26.

## Проверка результата узла

На существующей новой БД открыть ранее созданного героя и приключение после обновления, продолжить игру, затем отдельно проверить установку на пустую БД. Проверить итоговый diff и фактические результаты всех проверок; публикация/деплой не входят.
Следующий узел начинается после зелёных проверок этого узла и просмотра его работающего сценария пользователем. Это проверка результата, а не требование создавать новое согласование каждой технической детали. Общая уборка старого кода не блокирует демонстрацию готовых сценариев.

### Task 25: Retire inactive D&D code

**Files:** Retire app/rules/dnd5e/ and app/tools/{rest,spells}.py after import audit; Modify app/content/{catalog,loader}.py, app/rules/base.py, pyproject.toml and named consumers found by audit; remove obsolete class/rest/spell-slot/initiative UI and tests after listing consumers; Create tests/test_universal_legacy_audit.py.
**Interfaces:** No new runtime API: get_engine already selects universal from Task10. Retain shared dice/death-save arithmetic and auth/privacy/provider/audio infrastructure.

- [ ] **Step 1: Write failing tests.** assert active_legacy_imports == []; assert legacy_registered_routes == []; universal boot succeeds with retired modules physically absent. Historical docs/reference numerical data are explicit exemptions, not runtime fallback.
- [ ] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_legacy_audit.py -q. Expected missing new contract or required behavior, not an environment failure.
- [ ] **Step 3: Implement.** Use rg consumer audit before removing files. Transfer retained shared behavior instead of importing old engine. Replace obsolete gameplay tests with universal equivalents; never delete retained transaction/provider/privacy tests just to pass. Preserve migration chain created during new development; old-data migration/backfill/archive remains out of scope.
- [ ] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_legacy_audit.py -q. Run universal runtime/vitality/playthrough/contract tests; regenerate contracts and frontend typecheck/build. Audit dnd5e/class_id/spell_slots/MAX_LEVEL/short_rest/long_rest in active imports/routes/UI; review precise exemptions. graphify update .
- [ ] **Step 5: Commit.** refactor: remove inactive legacy rules without resetting universal data. Stage only this task's files.

### Task 26: Upgrade preservation, clean install and final review

**Files:** Create tests/test_universal_boot.py, tests/test_universal_upgrade.py; Modify README.md; runtime files only for reproduced integration defects.
**Interfaces:** Existing app entry point and python -m alembic upgrade head. Fresh install and upgrading an already-created universal game are separate required scenarios.

- [ ] **Step 1: Write failing tests.** test_upgrade_keeps_node1_hero — assert after.id == before.id; description/scores and later game receipts preserved. test_fresh_boot_uses_universal — assert campaign.ruleset_id == 'universal'. Restart/replay never doubles debit/XP; incompatible legacy DB remains unchanged.
- [ ] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_boot.py tests/test_universal_upgrade.py -q. Expected missing new contract or required behavior, not an environment failure.
- [ ] **Step 3: Implement.** Document workspace/DB/provider setup and each available node scenario. Upgrade from initial new baseline through all additive revisions; do not regenerate final baseline in a way requiring deletion of Node1+ data. Fresh rehearsal uses named temporary DB, actual lifespan and migrations, not create_all bypass.
- [ ] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_boot.py tests/test_universal_upgrade.py -q. Full pytest -n auto; python -m ruff check app tests tools; python -m ruff format --check app tests tools; python -m app.contract; npm --prefix web run gen:api; npm --prefix web run typecheck; npm --prefix web test; npm --prefix web run build. SQLite plus configured test PostgreSQL. graphify update . and final spec/diff audit; report unavailable checks and live-model quality separately.
- [ ] **Step 5: Commit.** test: verify universal install upgrade and final playable result. Stage only this task's files.
