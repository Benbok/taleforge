# Universal Combat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans in the existing worktree. Complete tasks inline with RED/GREEN and one independent final review.

**Goal:** Finish Node3: persistent combat equipment, one enemy response per hero action, timed combat effects and private zero-HP rescue, exposed through the running game.

**Architecture:** Extend the closed V2 action pipeline. Entity object instances hold bounded equipment profiles; UniversalEffect and UniversalClock remain the only runtime effect/time stores. A saved CombatExchange checkpoints hero action → enemy reply → one clock completion. Existing numeric dice formulas and Event receipts remain authoritative.

**Tech Stack:** Existing Python/FastAPI/Pydantic2/SQLAlchemy/Alembic, SQLite/PostgreSQL; React/TypeScript/Vitest.

**Spec:** [Approved universal design](../specs/2026-10-23-universal-creative-studio-design.md), [Node3 requirements Tasks13–17](2026-10-23-universal-creative-studio-03-combat-and-equipment.md), [2A integration](../specs/2026-10-25-exploration-magic-design.md). User explicitly requested execution after completing2A; implementation details below adapt that approved scope to current HEAD df45e03.

## Global Constraints

- Keep branch feature/universal-creative-studio, linked worktree, same Docker app/database and all saved heroes/worlds. No reset, merge or push. Migration follows universal_0005; the old plan's occupied filenames are superseded.
- Six attributes/five energies; HP=10+CON+6*(L-1), AC=12+M(DEX)+compatible equipped defenses. Library originals remain untouched.
- One eligible enemy reply per accepted hero game action, including heal/guard/wait. No enemy counter-counter. OOC, inspection, disconnect and UI reads do not create actions or ticks.
- Exact integer/decimal-string counts, natural20/1 and selected-die advantage/disadvantage remain. Binding resistance does not erase already applied damage.
- One shared game clock closes after hero/reply, never twice. New timed effects retain full duration after the casting exchange. Regeneration executes only once through existing clock completion.
- Common/rare/unique/epic statuses; no simultaneous rarity multiplier and the same flat weapon bonus. One weapon/armor slot initially; no class restrictions or grid combat.
- Rescues/death-save counters are private in API, WebSocket, narrative and voice. Rolls used for ordinary attacks remain visible.
- No live paid model tests. Preserve any concurrent edits and stage only task-owned files. Restart current app only after integration checks.

## Review Focus

1. Replay/crash after hero action must not repeat damage, item consumption, enemy response or tick — Tasks3/5.
2. Stale/dead/bound/offline/foreign actors cannot make an impossible attack — Tasks2/3/4.
3. Remote effect expiry, hidden foes and private death counters must not leak through cards/narration — Tasks2/4/5.
4. Starting armor must be materialized once and never counted alongside its persisted replacement — Task1.
5. Newly applied effects and newly unconscious heroes must not lose duration or receive an immediate rescue roll — Tasks3/4.

### Task 1: Persistent bounded equipment and consumables

**Files:** rules/universal/items.py; core/universal/inventory.py; tests/test_universal_inventory.py; modify exploration_views/state, API and existing derive consumers.
**Interfaces:** ItemProfile closed DTO(kind/status/slot/base_dice/attribute/attack_bonus/damage_bonus/defense_bonus/restore_pool/restore_amount); ensure_inventory(session,cid,actor_id); equipped_items(...); actor_derived(...); equip(...,request_key); consume(...,target_id,request_key).
- [x] RED: DEX14 AC14 + armor3 =17, unequip14; persisted starter counted once; four statuses only, flat bonus disables rarity multiplier; potion changes only selected pool and quantity once; foreign/hidden inventory rejected.
- [x] Run `python -m pytest tests/test_universal_inventory.py -q -n0`; expected missing module.
- [x] Implement Entity-backed instances and source-event receipts, exact quantities and slot replacement under campaign lock. Common starting equipment uses stable actor/slot IDs; equipped replacements suppress fallback starter bonus. Ordinary vessels retain2A behavior. HP/energy consumables clamp maxima and never change ability scores.
- [x] Run inventory and exploration contract/resolution regressions, Ruff; commit owned files.

### Task 2: V2 combat primitives, actor eligibility and actual effects

**Files:** rules/universal/combat.py; core/universal/combat_actions.py; extend exploration contracts/compiler/resolver/effects/perception; tests/test_universal_combat_actions.py.
**Interfaces:** combat_action(ctx,action,event)->ExplorationOutcome changes; scoped_targets(...); effective_actor(...); initialize_combatant(...); hostile candidates are persisted actors grounded in existing scene evidence.
- [x] RED: actual attack/damage/heal, damage+resisted binding independent; weapon bonuses affect their own terms; control blocks movement/acting/targeting; exact numbers and natural20/1. Hidden/foreign/stale targets reject before dice. Existing ordinary observation remains free.
- [x] Run combat-action tests; expected missing capabilities.
- [x] Extend V2 operations for weapon/equip/guard and periodic damage; attribute, power and resistance are compiled, never arbitrary final damage. Reuse existing pure numeric math. Directly witnessed forms cannot erase identity; expose cancellable effect IDs to decision context; vanished objects cannot reappear as observations. Scope global expiration changes before public projection.
- [x] Run V2 master/resolution/perception/privacy suites; commit.

### Task 3: Durable single enemy response and shared clock

**Files:** core/universal/combat.py; migration0006_universal_combat.py; models; agents/master/universal.py; tests/test_universal_exchange.py.
**Interfaces:** CombatExchange unique(cid,source_key), checkpoints hero_applied/reply_pending/reply_applied/ticks_pending/ticks_done; run_exchange(ctx,action,choose_reply=None,request_key)->saved outcomes.
- [x] RED: attack/heal/guard/wait each allow at most one eligible reply; AoE still one; no enemy still closes once; completed replay and restart at every checkpoint do not duplicate anything; stale reply becomes saved pass.
- [x] Run exchange/migration tests; expected missing coordinator/storage.
- [x] Commit hero receipt before outside-lock selection. Default deterministic nearest eligible hostile NPC policy uses admitted saved weapon profile and target. A supplied selector runs outside transactions, then eligibility is rechecked. Enemy action cannot recursively open another exchange. Defer existing complete_step until reply/pass; new effects are available to that reply without losing their full post-exchange lifetime.
- [x] Run exchange/concurrent completion/migration preservation regressions; commit.

### Task 4: Periodic effects and private vitality

**Files:** core/universal/vitality.py; combat effect completion; tests/test_universal_vitality.py and test_universal_effects.py.
**Interfaces:** enter_zero_hp(...,source_key,exchange_sequence); advance_vitality(ctx,exchange_id); advance_exchange(...); public vitality is only conscious/unconscious/stable/dead, without counters.
- [x] RED: new0HP has no immediate save; subsequent completed step rolls once; ordinary foe dies, significant NPC may save; healing rescues living but not dead; all-incapacitated explicit world action progresses, offline does not. DOT ticks once, rolls back on failure, stops after expiration.
- [x] Run vitality/effects tests; expected missing lifecycle.
- [x] Persist private rescue state in actor resource extras with eligible sequence. Reuse existing death-save arithmetic. Tick DOT and rescues inside the same saved completion transaction, honor ongoing controls and remove only their own modifiers.
- [x] Run privacy/replay/concurrent tick regressions; commit.

### Task 5: Game integration, equipment/combat UI and acceptance

**Files:** exploration_views; master V2 capability/context/narration; REST operations; isolated UniversalCombatPanel and tests; contracts; tests/test_universal_combat_playthrough.py.
**Interfaces:** Authoritative gear/effects/HP/outcome/exchange projection, existing authenticated endpoints/events. Client never resolves combat.
- [x] RED: integrated equip→vine hit+resisted bind→one reply→effect expiry→matching potion→0HP/rescue→reconnect, with private counters absent from player/narrator/voice; visible dice remain exact.
- [x] Run acceptance/frontend tests; expected missing integration.
- [x] Render actual equipment slots, compatible equip controls, HP/energy, active effects, enemy response and public life state. Retain current UI refinements and optional art; no grid, class system, XP/progression or map rewrite.
- [x] Run complete Universal/exploration backend suites, contract generation, frontend tests/typecheck/build and additive migrations. One independent final review; fix important findings with RED/GREEN. Update graphify once after final code. Restart same app and run read-only authenticated smoke, no paid casts.
- [x] Commit owned work and verification report, keep branch/worktree. Next stage remains progression/XP.

## Execution rulings

User's request authorizes implementation of the existing Node3 design. This plan reconciles reused2A parts and occupied migration numbers, rather than repeating design approval. Any further behavior choices are recorded in the plan-specific ledger. Review findings from the earlier2A session are regressions to verify when touching shared combat effects/perception; completed2A work is not reverted or reimplemented.

Implementation and automated acceptance: complete 2026-10-26. See docs/universal-combat.md for validation and playtest scope. Independent review findings fixed; final reviewer verdict was interrupted by usage limit. User playtest remains before Node4.
