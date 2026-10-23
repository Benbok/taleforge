# Progression and Balance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить опыт, распределение заработанных очков в игре и повышение входящей копии до уровня группы.

**Architecture:** Сервер хранит происхождение очков отдельно от отображаемых характеристик. Редактор из первого узла остаётся только у базового библиотечного героя. Игровая копия получает очки после level-up/catch-up и распределяет их через отдельное игровое действие, без общей правки карточки.

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

Повтор XP — Task18; повторная трата и обход через редактор — Task19; изменение оригинала и повтор catch-up — Task20; высокий уровень и баланс разных сборок — Task21.

## Проверка результата узла

Завершить событие → каждому получить одинаковую полную награду → повысить уровень → вложить два очка → убедиться, что общий редактор игровой карточки недоступен → добавить героя в развитую группу → проверить неизменность оригинала и сохранность прогресса.
Следующий узел начинается после зелёных проверок этого узла и просмотра его работающего сценария пользователем. Это проверка результата, а не требование создавать новое согласование каждой технической детали. Общая уборка старого кода не блокирует демонстрацию готовых сценариев.

### Task 18: Experience awards and uncapped thresholds

**Files:** Create app/rules/universal/progression.py, app/core/universal/progression.py; Modify app/rules/universal/contracts.py; Test tests/test_universal_progression.py, tests/test_universal_rewards.py.
**Interfaces:** level_threshold(level:int)->int; level_for_xp(xp:int)->int; grant_xp(sheet,amount:int)->UniversalSheet; award_xp(session,campaign_id,source_key,actor_ids:list[str],amount:int)->list[str].

- [ ] **Step 1: Write failing tests.** XP300 to4 yields [300,300,300,300], not divided; replay unchanged. Threshold21=410000,100=20555000; above20 no clamp. Crossing levels grants exactly2 points per level once.
- [ ] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_progression.py tests/test_universal_rewards.py -q. Expected missing new contract or required behavior, not an environment failure.
- [ ] **Step 3: Implement.** Master chooses award from quest/exploration/victory difficulty. Existing thresholds through20, proposed continuation355000+50000*n+2500*n*(n+1). Monotone search handles huge XP without arbitrary loop/level cap. Store unique source award and earned-point ledger server-side.
- [ ] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_progression.py tests/test_universal_rewards.py -q. Negative/foreign/duplicate recipients reject appropriately without double award; exact counts above2**53; multiple-level jump charges no extra XP event and earns correct budget.
- [ ] **Step 5: Commit.** feat: award full equal experience and uncapped growth. Stage only this task's files.

### Task 19: In-game allocation of earned points

**Files:** Modify app/core/universal/progression.py, app/rules/universal/mechanics.py, app/api/characters.py; Create web/src/game/LevelAllocation.tsx; Modify web/src/game/HeroWindow.tsx; Test tests/test_universal_level_allocation.py, web/src/game/LevelAllocation.test.tsx.
**Interfaces:** allocate_points(sheet,allocations:dict[AbilityKey,int])->UniversalSheet; spend_points(session,character_id,expected_revision,allocations)->UniversalSheet; resize_resources(old,before,after)->ActorResources. Effective base scores = permutation(start array) + saved nonnegative growth allocation.

- [ ] **Step 1: Write failing tests.** Two earned points both into wis accepted;3 rejected; reusing budget rejected. At L10 earned total18; player cannot spend point19. Master can propose allocation in game, but must use this same budget. General manual/chat card edits reject. Trusted growth5/20→9/24. Dead actor never resurrects.
- [ ] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_level_allocation.py -q; npm --prefix web test -- src/game/LevelAllocation.test.tsx. Expected missing new contract or required behavior, not an environment failure.
- [ ] **Step 3: Implement.** Keep initial base allocation, growth_total, allocated growth and unspent server-owned for each game copy. Only add newly earned points via this gameplay endpoint; do not reopen a library-style editor or silently refund already spent points. Master advice is a proposal, player confirms allocation in game. Temporary/item bonuses are not permanent points. Trusted level/stat increase partially refills only its actual new maximum once. Library original stays L1 and keeps no copy growth.
- [ ] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_level_allocation.py -q; npm --prefix web test -- src/game/LevelAllocation.test.tsx. Concurrent confirm/spend, stale in-game allocation proposal, double recalculation, manual/chat edit bypass attempts and unavailable reserve. Hero with0HP may recover from real level refill if alive; this is not an editing action or resurrection.
- [ ] **Step 5: Commit.** feat: allocate earned points in game without opening card editing. Stage only this task's files.

### Task 20: Catch up the admitted copy

**Files:** Modify app/core/universal/creation.py, app/core/characters.py, app/core/library.py, web/src/pages/CampaignHeroPage.tsx; Test tests/test_universal_catchup.py.
**Interfaces:** Extend admit_copy from Task7: party_level(session,campaign_id)->int; catch_up_copy(session,character_id,target_level:int,source_key:str)->UniversalSheet. Copy receives normal level-growth budget; library template stays L1.

- [ ] **Step 1: Write failing tests.** Create/import always yields L1 first. A separate catch-up event in L10 group then yields copied L10 with18 unspent earned points; assert library_after == library_before. Direct in-campaign creation follows the same two steps; constructor never returns allocated L10. Repeat admission/catch-up does not grant36 points. Other launched games unchanged.
- [ ] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_catchup.py -q. Expected missing new contract or required behavior, not an environment failure.
- [ ] **Step 3: Implement.** Use highest active group level as previously proposed default; exclude dead/archived/foreign copies when resolving active group. After L1 confirmation/admission, master triggers catch-up and suggests distribution through Task19 in-game allocation. Show earned/unspent points in game; do not return to the creation wizard or expose a general card editor. Catch-up source is one-time, not client-supplied arbitrary target level.
- [ ] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_catchup.py -q. No-active-group defaultsL1; concurrent join, stale target level and owner mismatch. Node4 walkthrough shows copied level and point explanation in existing card.
- [ ] **Step 5: Commit.** feat: catch up incoming hero copies without altering templates. Stage only this task's files.

### Task 21: Full balance report and fourth acceptance

**Files:** Extend tools/eval_universal_balance.py, tests/test_universal_balance.py; Create experiments/universal-rules/balance-v1.json and tests/test_universal_growth_playthrough.py.
**Interfaces:** simulate_build(level:int,allocation:str,seed:int)->dict; CLI python -m tools.eval_universal_balance --output experiments/universal-rules/balance-v1.json. Consumes actual growth/item/action rules rather than hand-built impossible budgets.

- [ ] **Step 1: Write failing tests.** Same build/seed identical; allocated_points == 2*(level-1). Test str/dex/con/wis specialists and even distribution at1/10/20/100/1000. Growth walkthrough awards once, allocates once, rejoins/reconnects without inflation.
- [ ] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_balance.py tests/test_universal_growth_playthrough.py -q. Expected missing new contract or required behavior, not an environment failure.
- [ ] **Step 3: Implement.** Report HP, all reserves, hit/control chances, damage quantiles, casts, heal efficiency, opposing actions and combined power across reserves. Include rarity, empty-resource fallback, multi-target/control and unequal defensive builds. Compare with preliminary Node2 report.
- [ ] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_balance.py tests/test_universal_growth_playthrough.py -q. Generate and inspect flags for runaway scaling/automatic hits/one-shots; record known tradeoffs and versioned coefficients. Manually demonstrate progression/catch-up and forbidden game-card editing. A changed agreed principle returns with reproducible evidence; arithmetic alone is not balance proof.
- [ ] **Step 5: Commit.** test: verify progression budgets and report universal balance. Stage only this task's files.
