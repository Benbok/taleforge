# Exploration Magic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task in the existing isolated branch. Steps use checkbox syntax.

**Goal:** Complete approved stage2A: arbitrary noncombat magic with real persisted effects/objects, explicit resource costs, learning and grounded narration.

**Architecture:** IntentV2 → requirement review → server compilation/validation → atomic effect/object application and learning → saved public facts and cards. Reuse pure Universal dice/math and Event receipts; retain read compatibility for already saved V1 decisions. RuntimeProfile also stores immutable V2 ability definitions. One game clock and saved step completion are shared with future combat.

**Tech Stack:** Existing Python/FastAPI/Pydantic2/SQLAlchemy/Alembic, SQLite/PostgreSQL, pytest; React/TypeScript/Zustand/Vitest.

**Spec:** [Approved stage2A design](../specs/2026-10-25-exploration-magic-design.md), approved by user «согласен» on2026-10-25.

## Global Constraints

- Existing branch/worktree, app container, database, heroes and original library records are retained; additive migrations only. Head before work is universal_0004.
- Every supernatural use has positive cost. Ordinary actions stay free. Light baseline at L1 costs1; normal3; strong12, targets/components/time are paid explicitly.
- Cosmetic, illumination, camouflage, limited plant form and ordinary handheld objects are the initial families. Combat behavior remains the next stage; current tested pure numeric rules remain reusable.
- Completed receipts are immutable. Retries cannot duplicate cost, objects, effects, time or learning; failed attempted checks spend, pre-attempt rejection does not.
- Count arithmetic uses exact integers and decimal-string wire values. Natural20/1 rules and selected-die advantage/disadvantage are preserved.
- Default short action6 game seconds, default timed effect18 seconds. Price duration ceil(seconds/6); new effect lifetime starts after its casting step. No ticks from UI/OOC/disconnect.
- Authoritative facts and actual state gate narration. No generic free-text mutation, unseen material, foreign inventory or hidden/private facts in public views.
- No live paid test generation. Preserve concurrent frontend edits; stage only owned changes. Do not restart the live app until integration is green.

## Review Focus

1. Magic relabeled mundane or an unimplemented request silently weakened — Tasks1/4/7.
2. Conjured cup duplicated on restart, material/liquid lost or foreign inventory consumed — Tasks3/5/8.
3. A permanent physical result mistaken for a permanent buff, or a newly cast effect losing its first duration — Tasks2/5.
4. Plant camouflage interpreted as guaranteed invisibility or erasing a direct witness — Tasks4/6.
5. Unsupported claims escaping through old fresh proposal formats or narrative wording — Tasks4/7/8.

## File and interface ownership

- `app/rules/universal/exploration.py`: closed V2 DTOs, allowed primitive registry, definition identity and pure cost.
- `app/db/models.py`, `alembic/versions/0005_universal_exploration.py`: clock/step/effect storage; existing RuntimeProfile and Entity storage retained.
- `app/core/universal/definitions.py`, `clock.py`, `effects.py`: immutable ability persistence, one-time game time, effect start/end/read models.
- `app/core/universal/objects.py`: bounded ordinary props, ownership/material/liquid and restorative-item operations.
- `app/core/universal/interpretation.py`: scope/effect/requirement compilation and validation; no model I/O in write transactions.
- `app/core/universal/exploration_resolution.py`: one serialized action transaction, actual receipts and learning.
- `app/core/universal/perception.py`: eligibility, witness knowledge, checks and light/camouflage observations.
- `app/agents/master/exploration.py`: durable V2 admission/review/recovery; existing universal service owns publication.
- `app/core/universal/exploration_views.py`: authenticated projections; existing API/socket and new isolated UI panel consume these.

### Task 1: V2 intent, definitions and effect budgets

**Files:** Create rules/universal/exploration.py and tests/test_exploration_contracts.py.
**Interfaces:** IntentV2(schema_version=2,requirements,source,resolution,effects,parameters,...); AbilityDefinitionV2; ExplorationAction; EffectChange; ExplorationOutcome(ActionOutcome); definition_key(definition)->str; exploration_cost(definition,level)->int.
- [x] RED: assert supernatural cosmetic L1/light=1, ordinary check=0; unsupported effect/extra key rejected; form and light with equal numbers have different keys, cosmetic renaming has same key; permanent ordinary creation uses duration1, timed18s uses3 units; no float/negative/unbounded arbitrary bonus.
- [x] Run `python -m pytest tests/test_exploration_contracts.py -q -n 0`; expected missing module/contracts.
- [x] Implement closed primitives and bounded parameters, source vs resolution separation, requirements→effects coverage and exact budgets. Numeric damage/heal primitives consume existing pure rules, not arbitrary ready amounts. Every effect declares lifecycle, scope, cost units and acquisition participation.
- [x] Run contract tests plus existing universal pure-math tests; expected green.
- [x] Commit task1.

### Task 2: Storage and one saved clock/effect lifecycle

**Files:** Create migration0005, core/universal/{definitions,clock,effects}.py, tests/test_exploration_clock.py and test_exploration_migration.py; modify models.
**Interfaces:** admit_definition(session,cid,definition)->AbilityDefinitionV2; load_definition(session,cid,ref,revision); complete_step(session,cid,source_key,elapsed_seconds)->GameStep; start_effect(...)->RuntimeEffect; active_effects(session,cid,target)->list; dismiss_effect(...).
- [ ] RED: migrate universal_0004 with existing hero/Event to head without data loss; cast at t6 with18s remaining, next6s→12; replay unchanged; very large game seconds stay exact; reads cannot tick; expiration/dismissal removes only own effects.
- [ ] Run new storage tests; expected missing storage/migration.
- [ ] Add UniversalClock, UniversalStep and UniversalEffect tables. Time/sequence/deadlines use decimal-string storage to avoid SQLite integer overflow. Serialize through existing Campaign update lock, use unique(campaign_id,source_key). New effects apply at casting-step end; close an already completed step without reapplying. Definition rows immutable and campaign scoped.
- [ ] Run migration/clock tests and existing resolution/replay tests; expected green.
- [ ] Commit task2.

### Task 3: Real ordinary objects, materials, containers and energy consumables

**Files:** Create objects.py, tests/test_exploration_objects.py; use Entity kind=object with closed V2 state and existing actor storage.
**Interfaces:** introduce_object(session,cid,spec,evidence)->Entity; apply_object_operation(ctx,operation,source_event)->EffectChange; visible_objects(session,cid,actor_id)->list; ordinary_object_view(entity)->dict.
- [ ] RED: cup capacity300ml, fill200 from accessible water source reduces source by200, persists; pour/empty/take/place/give respect quantities/location/ownership; foreign/hidden material rejected; physical cup remains after creating magic; temporary cup expiry releases contents once; energy tonic restores only its pool and consumes once; generated ordinary cup cannot inherit restorative properties.
- [ ] Run object tests; expected missing operations.
- [ ] Implement bounded handheld vessel/material/water-source/energy-tonic states and public-evidence introduction. No free actor/loot creation from arbitrary player strings. Use stable source event IDs and ordinary-object constraints, positive quantities/capacity and exact counts. No trading value, armor or weapon modifiers are introduced here.
- [ ] Run object and legacy object-policy/privacy regressions; expected green.
- [ ] Commit task3.

### Task 4: Semantic coverage and shared compilation

**Files:** Create interpretation.py, tests/test_exploration_interpretation.py; extend capability registry through versioned V2 entrypoint.
**Interfaces:** compile_exploration(ctx,intent,requirements_review,public_context)->ExplorationAction; validate_exploration(ctx,action)->ValidatedExploration; needs_intent_review(source,intent,known)->bool.
- [ ] RED: exact bush source cannot compile to mundane hiding; «делаю вид, что колдую» is not forced into real magic; missing requested light/duration/form rejected; current actor and target/object scope rechecked; saved known ref cannot change effects/parameters; all four consequence branches remain bounded editorial hints, not free world operations.
- [ ] Run interpretation tests; expected missing compiler.
- [ ] Compile definitions from supported primitives. Reject uncovered requirements and free supernatural effects. Source-text triggers only request review, never replace semantic interpretation. Validate price, form restrictions, materials, target visibility, energy, timing and effect capability before write and again during execution.
- [ ] Run interpretation/contracts/shared-validation regressions; expected green.
- [ ] Commit task4.

### Task 5: Atomic application, facts and successful learning

**Files:** Create exploration_resolution.py, tests/test_exploration_resolution.py; extend discovery/state projection for V2 definitions without parsing them as ProfileSpec.
**Interfaces:** resolve_exploration(ctx,action,request_key)->ExplorationOutcome; record_exploration_ability(session,actor,action,outcome,event)->HeroAbility|None; public_exploration_facts(outcome)->dict.
- [ ] RED: automatic cheap cosmetic/cup spells spend and learn once; ordinary listening never learns; failed roll spends without effect/learning; rejected action creates no Event/definition; missing second component rolls back first; existing receipt replays without dice or changed actor resources; different semantic abilities with identical math are distinct; ordinary cup is not a duration buff.
- [ ] Run resolution tests; expected missing executor.
- [ ] Reuse pure dice/critical/derived math. In one transaction authorize, replay-check, validate, debit, apply effects/objects, finish one step, discover only complete realized supernatural definitions, save actual typed changes and Event. Scope every new reference; do not hold write transaction during model calls. Failed technical application rolls back debit/time/objects.
- [ ] Run all exploration and universal resolution/discovery regressions; expected green.
- [ ] Commit task5.

### Task 6: Noncombat visibility and useful persistent effects

**Files:** Create perception.py, tests/test_exploration_perception.py; integrate effects into execution validation and scene projection.
**Interfaces:** actor_constraints(session,cid,actor_id)->dict; stealth_edge(effects,context)->edge; assess_detection(ctx,observer_id,actor_id,source_key)->EffectChange; illumination_view(...)->dict.
- [ ] RED: camouflage grants a single advantage only in eligible context; direct witness retains identity; no observer means no invented guaranteed-hidden result; chosen natural20/1 honored; private perception DC not public; form prevents moving/speaking/manual actions until cancellation; light alters observation conditions but does not reveal secret objects automatically.
- [ ] Run perception tests; expected missing behavior.
- [ ] Plant form preserves base stats/HP/energy/senses and adds no immunity or air independence. Use passive observer perception10+M(WIS), fixed from saved data; track actual notice state. Existing scene details become observers/props only through validated introductions. Noncombat reactions do not attack. Future combat consumes the same effects/clock.
- [ ] Run perception, actor scope and scene/privacy tests; expected green.
- [ ] Commit task6.

### Task 7: Durable V2 master pipeline and grounded narrative

**Files:** Create agents/master/exploration.py, tests/test_exploration_master.py; modify master/universal.py, action admission/calls/narration and roll projection at explicit version boundaries.
**Interfaces:** obtain_exploration_action(...)->PreparedExploration; review_intent(...)->IntentReview; review_narration(...)->NarrationReview; ensure_roll_message branches on saved payload schema_version; existing V1 read adapter only for saved rows.
- [ ] RED: fresh old-format magic cannot bypass V2; saved V1 receipt still recovers; failed/ambiguous semantic review never rolls/debits; review/repair budget survives restart; narration cannot add form/item/hidden fact absent actual changes; no live-model tests; automatic spell card contains no invented d20.
- [ ] Run pipeline tests; expected missing integration.
- [ ] Force closed V2 tool schema for fresh decisions. Persist source/plan binding, review and bounded one-repair budget before external I/O. Review new/changed or conflicting intents; known exact definitions reuse existing semantics. Narrate saved facts plus audience-safe context; review contradictory prose with at most one repair, then factual fallback without replaying actions. Update deterministic provider fixtures to current wire format; seed explicit old traces for compatibility tests.
- [ ] Run all universal/exploration master, lifecycle, replay and transport regressions; expected green.
- [ ] Commit task7.

### Task 8: Player projections, UI, acceptance and deployment

**Files:** Create exploration_views.py, web/src/game/ExplorationPanel.tsx and tests; modify clean GamePage/types/API projection/roll-card files. Avoid committing concurrent user changes to UniversalAdventure, MessageView, styling, builder or author pages.
**Interfaces:** exploration_game_card(session,hero)->dict; scene/knowledge projection of actual effects/objects; existing endpoints/events and authenticated socket retained.
- [ ] RED: cards expose correct cost/limits/remaining time/object contents; owner inventory and hidden observer details stay scoped; new spell visible after successful application; automatic use no d20; reconnect preserves light/form/cup without repeated spend; reading UI unchanged clock. End-to-end material→cup→fill→place, bush→detection→expiration and firefly light→observation are executable.
- [ ] Run frontend and acceptance tests; expected missing projections/panel.
- [ ] Add isolated read-only effects/objects panel and friendly source/cost/result labels. Obtain game views from authoritative DB rather than stale actor JSON; keep manual game-card editing prohibited. Introduce no cell-combat UI or automatic enemy attack.
- [ ] Run complete exploration/universal backend suites, contract generation, frontend tests/typecheck/build, migration preservation, scoped real read-only browser smoke. Request one final independent review, fix important findings with RED/GREEN. Run graphify update once after final code. Restart same app only after green; no paid test casting. Record verification and retained next-stage limitations.
- [ ] Commit owned files, keep worktree/branch and unrelated edits; no merge/push/reset.

## Self-review and execution rulings

Spec acceptance scenarios1–12 map to Tasks1/4/5/7 (interpretation/cost/learning),2 (clock/lifecycle),3 (objects/resources),6 (perception),7/8 (facts/privacy/recovery/UI). Interfaces share V2 DTOs from Task1; only the transactional executor closes steps and issues action receipts. No second effect or inventory truth is introduced.

The user's approval covers this design and its inline implementation; no second permission request is needed for these implementation details. Preserve the existing native/inline workflow with one final independent review. Any necessary deviation is recorded in this plan's execution ledger. The plan's tests, exact defaults and public scenarios are the execution contract.
