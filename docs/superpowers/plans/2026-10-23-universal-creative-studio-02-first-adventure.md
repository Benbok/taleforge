# First Playable Adventure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Во втором узле получить играемое исследовательское приключение с собственным миром, героем, проверками и сохранением.

**Architecture:** Студия и запуск подключаются сразу к пользовательскому интерфейсу. Числа, допуск мастера и сохранение действий разделены на небольшие задачи; игровая регистрация подключается здесь, не в конце разработки.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic 2, SQLAlchemy async, SQLite/PostgreSQL, pytest; React 19, TypeScript, React Query, Zustand, Vitest.

**Spec:** [Approved design](../specs/2026-10-23-universal-creative-studio-design.md)
**Index:** [Node order and shared contracts](2026-10-23-universal-creative-studio.md)

## Execution checkpoint — 2026-10-24

Tasks 6–12 implemented and verified together. See [verification evidence and explicit limits](../reports/2026-10-24-first-adventure-verification.md). A single integrated Node2 checkpoint replaces the task-level commit suggestions below. Full provider-driven user playthrough is the acceptance step before Node3.

## Дополнение исследования — проект 2026-10-25

Пользовательское тестирование выявило разрыв между ordinary_check, магическим намерением, состоянием мира и освоением. [Дизайн этапа2А](../specs/2026-10-25-exploration-magic-design.md) расширяет Tasks8–11 типизированными небоевыми эффектами, явной ценой любой магии и освоением нечисловых/automatic-способностей. Это новая приёмка перед боем; прежние готовые функции и данные сохраняются. Ни одно расширение не считается реализованным по факту составления документа.

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

Разные версии/прохождения — Tasks6,7; обход бюджета и повтор — Tasks8,9; невозможный замысел — Task10; ложное освоение — Task11; reconnect и доступный сценарий — Task12.

## Проверка результата узла

В браузере создать мир → принять версию → запустить → добавить копию героя → исследовать место и выполнить действие с проверкой → увидеть последствия и освоенное умение → перезапустить приложение и продолжить. Это уже исследовательская игра; полноценный бой проверяется в следующем узле.
Следующий узел начинается после зелёных проверок этого узла и просмотра его работающего сценария пользователем. Это проверка результата, а не требование создавать новое согласование каждой технической детали. Общая уборка старого кода не блокирует демонстрацию готовых сценариев.

### Task 6: World studio, review and immutable version

**Files:** Modify app/core/authoring/{contracts,projects,lore,validation,publication}.py, app/api/authoring.py, web/src/author/{AuthorWorkspace,LoreEditor,ValidationPanel}.tsx; Create app/agents/studio_review.py, tests/test_universal_studio.py.
**Interfaces:** StudioFields(title,premise,world,laws,inhabitants,powers,history,start,style,difficulty,excluded_themes,public_text,secret_text); review_project(session,project_id,owner_id,expected_revision)->CreationDialogue; accept_project(session,project_id,owner_id,expected_revision)->AdventureVersion.

- [x] **Step 1: Write failing tests.** test_review_revision — assert stale.status_code == 409; empty pack/class catalog does not block authoring. Scripted master asks a concrete contradiction question; answer permits accepted version. Public summary excludes secret laws/history.
- [x] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_studio.py -q. Expected missing new contract or required behavior, not an environment failure.
- [x] **Step 3: Implement.** Use existing studio controls with described world field groups and questions/accepted state. Rename visible workspace to «Творческая студия». Acceptance stores immutable universal version; model does not silently rewrite fundamental laws. Optional generators remain usable without mandatory full pregeneration.
- [x] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_studio.py -q. Frontend author workspace tests/typecheck; author can save/reopen a project and see exactly which version was accepted. Unreviewed or stale revision cannot publish.
- [x] **Step 5: Commit.** feat: author and review reusable universal worlds. Stage only this task's files.

### Task 7: Launch isolation and hero admission

**Files:** Modify app/core/authoring/{snapshot,instances,pipeline}.py, app/core/campaigns.py, app/core/{library,characters}.py, app/api/characters.py, app/db/models.py, app/rules/universal/contracts.py, web/src/pages/{NewCampaignPage,CampaignHeroPage,AuthorProjectsPage}.tsx; Create app/core/universal/profiles.py, alembic/versions/0002_runtime_profiles.py, tests/test_universal_launch.py, tests/test_universal_admission.py.
**Interfaces:** instantiate_adventure retains existing LaunchReceipt; admit_copy(session,library_id,campaign_id,seat_id)->Character; actor_view(sheet,resources,private:bool)->dict. RuntimeProfile(campaign_id,ref,revision,kind,definition) and closed ProfileSpec contract are introduced here, with numeric execution in Task8. load_actor(session,campaign_id,actor_id)->tuple[UniversalSheet,ActorResources]; save_actor(session,campaign_id,actor_id,sheet,resources)->None; get_profile(session,campaign_id,ref,revision)->ProfileSpec; put_profile(session,campaign_id,profile)->ProfileSpec. Node2 admits L1 copies; developed-group catch-up comes in Task20.

- [x] **Step 1: Write failing tests.** test_two_launches_isolated — assert first.campaign_id != second.campaign_id; profile/entity IDs disjoint. test_library_copy_untouched — assert source_after == source_before. An incompatible hero gets master admission/adaptation for its copy, not changes to original or a general game-card editor. Both library import and direct in-campaign creation first produce L1. Manual/chat edits to either completed game instance reject.
- [x] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_launch.py tests/test_universal_admission.py -q. Expected missing new contract or required behavior, not an environment failure.
- [x] **Step 3: Implement.** Copy immutable world/version profiles with remapped refs; launch UI reaches saved game. Reuse Node1 creation dialogue and read-only card for game copies; do not expose the library editor. Direct in-campaign confirmation also creates L1. Catch-up and earned-point allocation occur only later in the game, not in constructor fields. Library edits never alter live copies. Incompatible or unconfirmed adaptation cannot auto-join.
- [x] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_launch.py tests/test_universal_admission.py -q. Edit source and one launched game; verify other launch/original unchanged. Repeated launch request returns same receipt. Node1 heroes still load after any additive migration.
- [x] **Step 5: Commit.** feat: launch independent adventures and admit hero copies. Stage only this task's files.

### Task 8: Action profiles, dice and preliminary balance

**Files:** Create app/rules/universal/profiles.py, tools/eval_universal_balance.py; Modify app/rules/universal/{contracts,mechanics}.py; Test tests/test_universal_profiles.py, tests/test_universal_balance.py.
**Interfaces:** ProfileSpec, EffectSpec, ResistanceSpec, ActionOutcome; validate_profile(profile)->ProfileSpec; resource_cost(profile,level:int)->int; resolve_check(dice,attribute:int,trained:bool,difficulty:int,edge:str)->ActionOutcome; resolve_attack(dice,sheet,target_ac:int,profile,critical:bool=False)->ActionOutcome; resolve_resistance(dice,target_id,effect_id,target_attribute:int,resistance)->EffectOutcome; restore(current,maximum,amount)->int.

- [x] **Step 1: Write failing tests.** At L1/A14/die4 normal common damage6/cost3; L10 same damage24/cost30. WIS33 DC21 vs DEX14/24/33 binds 90/65/45 percent. Crit doubles base dice only; immunity remains0. Same seed report repeats exactly.
- [x] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_profiles.py tests/test_universal_balance.py -q. Expected missing new contract or required behavior, not an environment failure.
- [x] **Step 3: Implement.** Use damage roll(B)+M(A)+2*(L-1)+item bonus then intensity/rarity once; cost L*ceil(3*q*q), q=.5/1/2. Targets/duration/numeric components multiply cost. Proposed bases1d4/1d6/1d8 require bounded profiles. Specify provisional four-status item budgets before numerical use; mark them designer proposals, not approved balance. Separate attack/damage item bonuses. Fix parameters before Dice; no trained bonus implicitly on resistance.
- [x] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_profiles.py tests/test_universal_balance.py -q. Before admitting runtime actions, generate preliminary report at levels1/10/100 with +2 points/level specialist/even builds. Flag one-shots/automatic checks and record chosen provisional coefficients; no universal balance proof. Narrative cannot justify unpriced extra effects or arbitrary100d100.
- [x] **Step 5: Commit.** feat: resolve bounded universal action profiles. Stage only this task's files.

### Task 9: Atomic saved action execution

**Files:** Create app/core/universal/resolution.py; Modify app/tools/resolution/{operations,executor}.py, app/core/resolution/policy.py; Create tests/test_universal_resolution.py.
**Interfaces:** ProposedAction(ref:ActionRef,actor_id,targets,profile:ProfileSpec,operations:list[EffectSpec],reason); resolve_action(ctx,proposal:ProposedAction,request_key:str)->ActionOutcome. Consumes Task8 pure math and Node1/Task7 actor/profile scope.

- [x] **Step 1: Write failing tests.** test_replay_spends_once — assert replay.status == 'repeated'; assert debit_count == 1. Foreign actor/target, stale profile, damage999999 or free restoration deny without mutation. Failure of second operation rolls back actor and target.
- [x] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_resolution.py -q. Expected missing new contract or required behavior, not an environment failure.
- [x] **Step 3: Implement.** Validate scope, ownership, cost and compiled operations; persist chosen parameters, Dice, debit and outcomes in short transaction/savepoint with source Event receipt. Immediate effects are saved; scheduled duration integration belongs to Node3. No LLM calls inside transaction.
- [x] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_resolution.py -q. Vine hit with successful resistance keeps damage/cost and no cannot_move. Reconnect after commit returns receipt. A denied action and an attempted miss differ; model cannot rewrite DC after roll.
- [x] **Step 5: Commit.** feat: save universal actions atomically with replay protection. Stage only this task's files.

### Task 10: Master admission and early runtime wiring

**Files:** Create app/tools/universal_actions.py, app/rules/universal/engine.py; Modify app/rules/{__init__,base}.py, app/main.py, app/tools/{__init__,registry}.py, app/agents/intent.py, app/agents/master/{turn,tool_profiles,action_binding,prompt_context,creative,narration}.py, app/agents/prompts/master_system.j2; Test tests/test_universal_action_admission.py, tests/test_universal_runtime.py.
**Interfaces:** admit_action(ctx,source:ActionRef,summary:str)->ProposedAction|DomainError; get_engine(ruleset_id:str) selects universal only; public_turn_view(ctx,audience)->dict from saved results. Existing narrator/voice publishes this view.

- [x] **Step 1: Write failing tests.** test_unknown_ability_name_is_admitted — assert proposed.profile.attribute == 'wis'; world-impossible action denies before execution. assert type(get_engine('universal')).__name__ == 'UniversalEngine'. Old ruleset cannot be selected. Public narrator payload excludes death counters and another hero's secrets.
- [x] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_action_admission.py tests/test_universal_runtime.py -q. Expected missing new contract or required behavior, not an environment failure.
- [x] **Step 3: Implement.** Master considers world, hero, level, resources and scene; free-form intent routes to Task9 without requiring an SRD entry. Wire universal registered paths now and disable old class/rest/spell-slot registrations; physical cleanup later. Basic public narration describes saved result without mandatory2–4-sentence cap. Preserve player agency and search/context. Unknown name grants no extra privilege.
- [x] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_action_admission.py tests/test_universal_runtime.py -q. Low-dex mage may propose tumble; weak stat affects check without duplicate automatic DC penalty. Technical call limits are not fictional denials. Existing auth/provider/audio startup retained. Active-hostile combat entry is not advertised as complete until Node3.
- [x] **Step 5: Commit.** feat: connect free-form master actions to the universal runtime. Stage only this task's files.

### Task 11: Successful ability discovery

**Files:** Create app/core/universal/discovery.py, alembic/versions/0003_hero_abilities.py; Modify app/core/universal/resolution.py, app/core/views.py, app/db/models.py; Test tests/test_universal_discovery.py.
**Interfaces:** record_realized_ability(session,character_id:str,proposal:ProposedAction,outcome:ActionOutcome,event_id:str)->HeroAbility|None, inside action transaction. Saved ability view exposes profile ref/name/description/cost/limits.

- [x] **Step 1: Write failing tests.** test_success_learns_once — assert count == 1; first miss => count0; later miss preserves learned ID. Learning-write error rolls back entire action. New migration preserves Node1 hero and Node2 world.
- [x] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_discovery.py -q. Expected missing new contract or required behavior, not an environment failure.
- [x] **Step 3: Implement.** Learn only successfully realized admitted ability, never merely a text declaration. Enforce campaign/profile/event uniqueness and persisted resource key. Replay never creates a second learning event. For partial composite realization, settle the previously open learning policy with an explicit example before enabling full composite learning; do not silently treat every resisted part as learned.
- [x] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_discovery.py -q. Concurrent replay, renamed ability, changed profile revision and independent campaign copies. Known ability is usable again with saved rules; failed first attempt remains only history.
- [x] **Step 5: Commit.** feat: learn abilities from saved successful actions. Stage only this task's files.

### Task 12: Playable exploration UI and second acceptance

**Files:** Modify web/src/pages/GamePage.tsx, web/src/game/{ChatFeed,Composer,HeroWindow,Features,Spellbook}.tsx, web/src/stores/game.ts, web/src/lib/types.ts; Create tests/test_universal_first_adventure.py, web/src/pages/FirstAdventure.test.tsx.
**Interfaces:** Consumes Node2 author/launch/admission, hero_card and public_turn_view. No new execution function. Event reducers keep existing websocket sequence/checkpoint semantics.

- [x] **Step 1: Write failing tests.** test_first_adventure — accepted world → launch → copy hero → narrative investigation/check → successful invented ability → save → restart/reconnect. assert library_after == library_before; assert learned_count == 1; assert debit_after_reconnect == debit_before_reconnect.
- [x] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_first_adventure.py -q; npm --prefix web test -- src/pages/FirstAdventure.test.tsx. Expected missing new contract or required behavior, not an environment failure.
- [x] **Step 3: Implement.** Make studio launch and game chat reachable through normal pages; show saved card and learned abilities, not mocked local state. Coordinates are not mandatory for admitting exploration/action; location membership and reachability remain world facts. Supply complete description of current noncombat scene.
- [x] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_first_adventure.py -q; npm --prefix web test -- src/pages/FirstAdventure.test.tsx. Regenerate contracts; frontend typecheck/build; manually demonstrate the node scenario. Record actual outcomes and limitations before Node3. The user already has a persistent exploratory game here, not just backend libraries.
- [x] **Step 5: Commit.** feat: deliver the first playable universal adventure. Stage only this task's files.
