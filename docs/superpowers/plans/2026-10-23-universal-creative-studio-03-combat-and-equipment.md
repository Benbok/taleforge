# Combat and Equipment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Добавить к уже работающему приключению предметы, полноценный бой, эффекты и спасение при 0 HP.

**Architecture:** Характеристики предметов подключаются к существующим карточкам. Координатор обмена, часы эффектов и жизненное состояние реализуются раздельно; последняя задача проверяет их вместе в работающей сцене.

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

Четыре статуса/двойной бонус — Task13; лишний ответ врага/reconnect — Task14; повтор тика — Task15; скрытая смерть/offline — Task16; совместный сценарий — Task17.

## Проверка результата узла

В игре экипировать оружие/броню → применить лозу → получить один ответ врага → проверить связывание и снятие эффекта → потратить профильный расходник → спасти героя при 0 HP → переподключиться без повторного урона.
Следующий узел начинается после зелёных проверок этого узла и просмотра его работающего сценария пользователем. Это проверка результата, а не требование создавать новое согласование каждой технической детали. Общая уборка старого кода не блокирует демонстрацию готовых сценариев.

### Task 13: Persistent items, equipment and consumables

**Files:** Create app/core/universal/inventory.py, alembic/versions/0004_universal_inventory_profiles.py; Modify app/tools/master/{items,invented}.py, app/core/equipment.py, app/api/characters.py, web/src/game/Gear.tsx, app/db/models.py; Create tests/test_universal_inventory.py, web/src/game/Gear.test.tsx.
**Interfaces:** ItemStatus=common/rare/unique/epic; ItemProfile as index. equip(session,campaign_id,actor_id,inventory_id,equipped:bool,request_key)->ActorDerived; consume(session,campaign_id,actor_id,inventory_id,target_id,request_key)->ActionOutcome; item_view(profile,instance)->dict.

- [ ] **Step 1: Write failing tests.** DEX14 baseAC14 + armor3 =>17; remove=>14. Each item saves one required status, rejects superseded statuses. Mana potion changes wis only, consumes quantity once, clamps maximum. Weapon attack bonus affects hit, damage bonus affects damage.
- [ ] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_inventory.py -q; npm --prefix web test -- src/game/Gear.test.tsx. Expected missing new contract or required behavior, not an environment failure.
- [ ] **Step 3: Implement.** Master creates bounded persistent properties; type-specific stats, localized status and known effects appear in card. Server owns quantity, slot compatibility and duplicate defense bonus handling. Unique status is not automatically world-singleton. Difficulty changes never rewrite an existing item.
- [ ] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_inventory.py -q; npm --prefix web test -- src/game/Gear.test.tsx. Foreign item/target and failed mutation roll back. Rarity follows Task8 provisional configuration once, no double multiplier. Restorative potion never raises underlying ability score. Existing hero/world survive migration.
- [ ] **Step 5: Commit.** feat: equip persistent items and consume matching resources. Stage only this task's files.

### Task 14: One eligible enemy reply

**Files:** Create app/core/universal/combat.py, alembic/versions/0005_combat_exchanges.py; Modify app/db/models.py, app/core/combat.py, app/agents/master/{turn,checkpoint}.py; Test tests/test_universal_exchange.py.
**Interfaces:** CombatExchange(campaign_id,source_key,sequence,hero_action,enemy_actor_id,status), unique(campaign_id,source_key); run_exchange(ctx,hero_action:ProposedAction,choose_reply:Callable[[dict],Awaitable[ProposedAction|None]],request_key:str)->list[ActionOutcome]. Checkpoints hero_applied/reply_pending/reply_applied/ticks_pending/ticks_done.

- [ ] **Step 1: Write failing tests.** test_heal_allows_one_reply — assert reply_count == 1; same for attack/guard/wait. Multi-hit/AoE still one reply; reply may target another hero. Offline/OOC/map inspection produce no exchange. Reply cannot provoke counter-counter.
- [ ] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_exchange.py -q. Expected missing new contract or required behavior, not an environment failure.
- [ ] **Step 3: Implement.** Commit hero action once, select enemy outside locks using refreshed scene, recheck eligibility and apply one reply via Task9. Dead/incapacitated/unreachable enemy cannot make impossible attack. Failed reply records pass without undo/replay of hero action. Stop at ticks_pending until Task15 adds scheduled completion.
- [ ] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_exchange.py -q. Hero kills proposed enemy before selection, stale enemy proposal, no eligible enemy and reconnect at each checkpoint. Additive migration retains existing adventure.
- [ ] **Step 5: Commit.** feat: coordinate one saved enemy response per hero action. Stage only this task's files.

### Task 15: Saved effects and exchange clock

**Files:** Create app/core/universal/effects.py, alembic/versions/0006_runtime_effects.py; Modify app/db/models.py, app/core/universal/{resolution,combat}.py, app/tools/effects.py; Test tests/test_universal_effects.py.
**Interfaces:** RuntimeEffect(campaign_id,ref,definition,applied_exchange,remaining,private); advance_exchange(ctx,exchange_id:str)->None. Completes ticks_pending→ticks_done after hero/reply pair.

- [ ] **Step 1: Write failing tests.** test_effect_starts_next_exchange — assert remaining_after_application == 3; assert remaining_after_next_exchange == 2. Repeated completion does not decrement again. Damage-over-time ticks once for each eligible completed exchange.
- [ ] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_effects.py -q. Expected missing new contract or required behavior, not an environment failure.
- [ ] **Step 3: Implement.** Immediate effects apply now; scheduled duration starts on the next completed exchange. Persist effect/exchange receipt with state change in one transaction. Same clock for buffs/debuffs/periodic damage; no ticks from client activity or narration length.
- [ ] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_effects.py -q. Rollback during tick, concurrent completion, no enemy still completing exchange, cannot_move affecting melee eligibility and expiration removing exactly its own bonus. Savepoint prevents duplicate HP loss.
- [ ] **Step 5: Commit.** feat: persist and tick effects once per exchange. Stage only this task's files.

### Task 16: Unconsciousness and hidden rescue

**Files:** Create app/core/universal/vitality.py; Modify app/core/universal/{resolution,effects}.py, app/tools/master/checks.py, app/core/views.py; Test tests/test_universal_vitality.py.
**Interfaces:** enter_zero_hp(session,campaign_id,actor_id,source_key,exchange_sequence:int)->ActorResources; advance_vitality(ctx,exchange_id:str)->None inside Task15 completion transaction. Reuse shared tested death-save arithmetic without old-class/rest imports.

- [ ] **Step 1: Write failing tests.** New0HP has saves0 until next exchange, then one save. Ordinary foe0 dies; significant NPC may receive saves. Healing before tick rescues living; dead remains dead. Public view lacks private save counters.
- [ ] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_vitality.py -q. Expected missing new contract or required behavior, not an environment failure.
- [ ] **Step 3: Implement.** Persist stable/dead/unconscious state and eligible-from exchange; unconscious protagonist cannot act. Explicit world-event sources can progress all-incapacitated situations; disconnect is never a source. Healing and trusted later level refill clear appropriate unconscious state only when living HP becomes positive.
- [ ] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_vitality.py -q. All heroes incapacitated reaches stable/dead/rescued outcome, repeated tick is safe, party member can assist before save and voice payload hides counters. Ordinary visible rolls are not hidden automatically.
- [ ] **Step 5: Commit.** feat: persist zero-health rescue outcomes. Stage only this task's files.

### Task 17: Combat UI and third acceptance

**Files:** Modify web/src/game/{CombatStrip,ChatFeed,HeroHud,Gear}.tsx, app/gateway/protocol.py; Create tests/test_universal_combat_playthrough.py, web/src/pages/CombatAdventure.test.tsx.
**Interfaces:** Consumes saved exchange/outcome/effect views; no duplicate client resolution. Existing public_turn_view expands to actual combat outcomes without exposing private state.

- [ ] **Step 1: Write failing tests.** Scenario equip→vine damage+resisted bind→one enemy reply→buff expiration→targeted potion→0HP/rescue→reconnect. assert reply_count == hero_action_count; assert replay_debits == original_debits; no death_failures in player/voice payload.
- [ ] **Step 2: Run RED.** python -m pytest -n 0 tests/test_universal_combat_playthrough.py -q; npm --prefix web test -- src/pages/CombatAdventure.test.tsx. Expected missing new contract or required behavior, not an environment failure.
- [ ] **Step 3: Implement.** Render authoritative HP/resources/equipment/effects and actual narrative outcomes. Preserve websocket sequencing and completed-exchange checkpoint semantics. Resist binding does not erase damage; binding is not full stun.
- [ ] **Step 4: Run GREEN.** python -m pytest -n 0 tests/test_universal_combat_playthrough.py -q; npm --prefix web test -- src/pages/CombatAdventure.test.tsx. Frontend typecheck/build and manual combat demonstration. Review actual pacing with agreed HP/damage example; record coefficients needing calibration rather than silently changing world laws.
- [ ] **Step 5: Commit.** test: verify the playable combat and equipment node. Stage only this task's files.
