# Hero Workshop Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Первым готовым результатом дать создание, сохранение и редактирование полной карточки героя.

**Architecture:** Авторизация и библиотека работают с новой схемой с первого узла. Описательное создание, ручной редактор и чат мастера используют единый валидатор; игровой движок и кампании для этого не требуются.

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

Чужой герой/устаревшая ревизия — Tasks 1,4; неверный набор и накрутка — Tasks 2,4; повтор подтверждения — Task 3; обе формы редактирования и перезагрузка — Task 5.

## Проверка результата узла

В браузере: описать героя → ответить мастеру → увидеть полную карточку → изменить описание вручную → переставить характеристики → попросить мастера о другой версии → подтвердить → перезагрузить. Все данные сохраняются, HP/ресурсы/КД пересчитываются; недопустимые значения не сохраняются.
Следующий узел начинается после зелёных проверок этого узла и просмотра его работающего сценария пользователем. Это проверка результата, а не требование создавать новое согласование каждой технической детали. Общая уборка старого кода не блокирует демонстрацию готовых сценариев.

### Task 1: Fresh workspace schema and hero storage

**Files:** Modify app/db/models.py, app/db/session.py, alembic/env.py, app/main.py; Create app/core/universal/state.py, alembic/versions/0001_universal_initial.py, tests/test_universal_schema.py, tests/test_universal_state.py.
**Interfaces:** load_library_hero(session,owner_id:str,hero_id:str)->LibraryCharacter; verify_universal_schema(engine)->None. Baseline preserves auth/authoring/knowledge/audio tables and adds universal hero/dialogue state. Later nodes own additive revisions for their new tables.

- [ ] **Step 1: Write failing tests.** test_fresh_schema_has_one_head — `assert len(heads) == 1`; test_foreign_library_hero_hidden — `assert response.status_code == 404`; test_restart_keeps_hero — `assert after.id == before.id`. Nonempty legacy schema is rejected before bootstrap writes; original rows remain unchanged.
- [ ] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_schema.py tests/test_universal_state.py -q. Expected missing new contract or required behavior, not an environment failure.
- [ ] **Step 3: Implement.** Start on a newly named isolated DB and retire superseded migrations in the same baseline change, without copying old game data. Preserve pre-existing edits via isolated-workspace workflow. Hero-only entry points use universal storage; no old-rule selector is offered. Later changes use migrations instead of recreating this DB.
- [ ] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_schema.py tests/test_universal_state.py -q. Rehearse alembic upgrade head and actual startup/restart with the isolated SQLite DB; configured PostgreSQL separately when available. Never delete arbitrary configured DBs.
- [ ] **Step 5: Commit.** feat: initialize universal hero storage and fresh schema. Stage only this task's files.

### Task 2: Hero math and authoritative card

**Files:** Create app/rules/universal/{__init__,contracts,mechanics}.py; Modify app/api/library.py, app/core/library.py, app/core/views.py, app/api/schemas.py; Test tests/test_universal_hero_math.py, tests/test_universal_card.py.
**Interfaces:** AbilityKey, AbilityScores, HeroDescription, UniversalSheet and HeroBudget from index. validate_starting_scores(scores:AbilityScores)->AbilityScores; derive(sheet,defense_bonuses:list[int])->ActorDerived; hero_card(session,owner_id:str,hero_id:str)->dict.

- [ ] **Step 1: Write failing tests.** test_start_array_is_exact — reject all15 and same-sum non-permutation; assert sorted(scores.values()) == [8,10,12,13,14,15]. CON14 at L1/5/10/100 gives HP24/48/78/618. A14 at L1 gives five energy_max24 and DEX14 gives AC14. Public card excludes private history and death counters.
- [ ] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_hero_math.py tests/test_universal_card.py -q. Expected missing new contract or required behavior, not an environment failure.
- [ ] **Step 3: Implement.** M(A)=floor((A-10)/2), Emax(A)=L*(10+A), AC12+M(DEX)+compatible equipped bonuses. Use exact integers, decimal strings for unbounded wire counts. Full card includes identity/appearance/personality/capabilities, scores/modifiers, level/XP, HP/five reserves, equipment and learned abilities; empty lists are meaningful. Keep start-array validation separate from grown actor/NPC values.
- [ ] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_hero_math.py tests/test_universal_card.py -q. Round-trip a value above 2**53 unchanged. Card works with no class, race catalog, spell selection or SRD import. Display descriptive capabilities separately from learned executable abilities.
- [ ] **Step 5: Commit.** feat: expose complete universal hero cards. Stage only this task's files.

### Task 3: Guided description-based creation

**Files:** Create app/core/universal/creation.py, app/agents/hero_creation.py, app/api/hero_creation.py; Modify app/main.py, app/core/library.py; Test tests/test_universal_creation.py.
**Interfaces:** start_dialogue(session,owner_id,description:HeroDescription,campaign_id:str|None,target_id:str|None)->CreationDialogue; answer_dialogue(session,dialogue_id,owner_id,expected_revision:int,answer:str)->CreationDialogue; confirm_hero(session,dialogue_id,owner_id,expected_revision:int)->str. StartingAllocationProposal includes six scores and explanations.

- [ ] **Step 1: Write failing tests.** test_identity_only_starts_dialogue — assert dialogue.status == 'questions'; test_confirm_once — assert created_count == 1. Substantive ambiguity yields relevant follow-up; stale/unanswered proposal cannot confirm. Confirmed hero is L1/xp0 with exact start array for library, admin premade and direct in-campaign creation. A group already at L10 does not change constructor output; catch-up is a later game event.
- [ ] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_creation.py -q. Expected missing new contract or required behavior, not an environment failure.
- [ ] **Step 3: Implement.** POST /api/hero-creation/dialogues, GET /{id}, POST /{id}/answers and /confirm. Persist transcript, proposal and revision; model runs outside row locks. Infer priorities from explicit description, not a class template, verbosity or omitted detail. Server validates proposal before ready/confirm. Explain scores and let player correct concept in words.
- [ ] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_creation.py -q. Reload resumes existing answers; wrong owner denied; malformed LLM output or failed provider preserves previous draft. GET never invokes LLM or changes dialogue.
- [ ] **Step 5: Commit.** feat: create heroes through guided master dialogue. Stage only this task's files.

### Task 4: One edit boundary for manual changes and master chat

**Files:** Create app/core/universal/editing.py; Modify app/api/{library,hero_creation}.py, app/agents/hero_creation.py, app/db/models.py; Test tests/test_universal_editing.py.
**Interfaces:** HeroEdit(description_patch,base_scores,expected_revision); propose_hero_edit(session,owner_id,library_id:str,message:str,expected_revision:int)->HeroEdit; apply_hero_edit(session,owner_id,library_id:str,edit:HeroEdit,request_key:str)->dict. Manual PATCH and confirmed chat proposal both call apply_hero_edit.

- [ ] **Step 1: Write failing tests.** test_manual_and_chat_share_budget — both reject all15 and a same-sum invalid array. test_edit_does_not_award_points — assert after.budget == before.budget. test_chat_preview_does_not_mutate — assert before == after_preview. Reject client-supplied level/XP/resource refill and stale revisions; replay is applied once. test_campaign_card_edit_forbidden — manual and chat requests with an in-game hero ID both reject with no mutation, including L1 campaign heroes.
- [ ] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_editing.py -q. Expected missing new contract or required behavior, not an environment failure.
- [ ] **Step 3: Implement.** Allow descriptions and score permutations only for the owner's base LibraryCharacter, with visible preview/confirmation. It stays L1/xp0 with exact array and no growth budget. Recompute library preview values server-side; never write an existing game copy. Reject Character/campaign targets in both endpoint and chat tool, not just UI. New capabilities remain proposals subject to world/realization rules, not free executable power.
- [ ] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_editing.py -q. Parallel chat/manual updates conflict without lost changes. Editing a library template never heals a live copy or grants it points; copied and directly created game heroes both reject edit requests. Creation drafts may still be refined before L1 confirmation.
- [ ] **Step 5: Commit.** feat: edit hero cards with a shared bounded validator. Stage only this task's files.

### Task 5: Full hero workshop UI and first acceptance

**Files:** Create web/src/builder/{HeroDescriptionForm,HeroCreationDialogue,HeroCardEditor}.tsx and tests; Modify web/src/pages/LibraryHeroPage.tsx, web/src/builder/Builder.tsx, web/src/game/HeroWindow.tsx, web/src/lib/{builder,types}.ts; Create web/src/lib/counts.ts, web/src/lib/counts.test.ts, web/src/pages/HeroWorkshop.test.tsx, tests/test_universal_hero_workshop.py.
**Interfaces:** Consumes Tasks1–4 endpoints and hero_card. HeroCardEditor(card,onSaved)->JSX; formatCount(value:string)->string and compareCounts(a:string,b:string)->number use BigInt for exact decimal-string counts. Creation starts from text; optional numeric reassignment is available only on the base library card. Game cards show state without manual/chat edit actions.

- [ ] **Step 1: Write failing tests.** test_workshop_roundtrip — creation, visible scores/explanations, manual edit, chat preview/confirmation, reload preserve same hero. UI offers score reassignment, not six unlimited numeric inputs; server rejection is shown. Assert unconfirmed chat edit does not change displayed saved card.
- [ ] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_hero_workshop.py -q; npm --prefix web test -- src/pages/HeroWorkshop.test.tsx. Expected missing new contract or required behavior, not an environment failure.
- [ ] **Step 3: Implement.** Show complete card with derived values and clear empty equipment/learned sections; never require class/race/spell pickers. Share manual/chat preview and confirmation for library cards, preserve unsaved text on stale-revision response. Do not render these editors for a created campaign hero; direct requests are still rejected server-side. Regenerate API contracts and use existing query patterns.
- [ ] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_hero_workshop.py -q; npm --prefix web test -- src/pages/HeroWorkshop.test.tsx. Run src/lib/counts.test.ts: compareCounts('9007199254740993','9007199254740992') == 1, without Number conversion. Run backend contracts, frontend typecheck/build and the node scenario in browser. Record what works and observed defects before Node2; scripted fixtures do not prove live LLM quality. No campaign or complete combat engine required.
- [ ] **Step 5: Commit.** feat: deliver the editable hero workshop. Stage only this task's files.
