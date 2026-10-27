# Universal World Expansion Implementation Plan

> For agentic workers: use superpowers:executing-plans inline, TDD and one independent final review.

Goal: make an authored Universal world grow persistently and let players enter newly developed locations.
Architecture: closed world proposals + independent review -> durable phase -> atomic publication -> saved action transition -> recipient-safe narration. Reuse phase leases/recovery/accounting; no legacy runtime invocation.
Tech: existing Python/Pydantic/SQLAlchemy, React/Vitest, PostgreSQL/SQLite.
Spec: ../specs/2026-10-27-universal-world-expansion.md

## Global Constraints
Use feature/combined and same Docker/database/media; preserve all existing world/hero/library data and completed receipt ev_f42e9b75d87a3d1e. No paid live calls, reset/push, duplicated mechanics executor or whole-world regeneration. Keep current map style; code search graphify first, update after changes. No LLM I/O inside DB transactions. Each phase has persisted call budget/lease and durable reviewed draft. User does not author locations manually.

## Review Focus
Concurrent phase publication/recovery -> stable entities and one movement. Current facts and private world/hero data -> no retcon or disclosure. Missing/blocked/unprepared exits -> no false-success travel. Re-entry -> no regeneration or free resources. Split parties -> destination details only for present original recipients.

### Task 1: Persistent Universal scene preparation
Files: new app/rules/universal/world.py, app/core/universal/world_generation.py, app/agents/master/world.py; modify app/core/world_generation/{storage,service}.py and master/universal.py structured calls. Tests tests/test_universal_world_generation.py.
Interfaces: WorldScenePlan/WorldSceneReview closed schemas; reserve_scene(session,campaign,location_id,turn_id); prepare_scene(service,campaign,turn_id,location_id); run_phase(maker,claim,llm). Existing location_initial rows tagged generator_version; separate session apply callback with normal lease/world CAS.
- [x] RED scene plan bounds/unique refs, stable visible/hidden props/passages, no clock/hero changes, immutable existing facts, invalid/foreign refs rejected, retry/concurrent draft publication.
- [x] Implement schemas, reservation, leases/call budgets, model/review prompts and atomic publication; reuse existing recovery dispatcher and accounting.
- [x] GREEN focused tests and commit owned files.

### Task 2: Lazy preparation and real movement
Files: app/agents/master/{universal,universal_lifecycle,exploration}.py, app/core/universal/{interpretation,travel,exploration_resolution}.py, app/rules/universal/{exploration,failures}.py. Tests tests/test_universal_world_exploration.py and existing first-adventure scenario fixture.
- [x] RED first scene preparation, travel binds known target, failed preparation never advances/spends, ambiguous/unresolved crossing not successful note, return and recovery reuse same rooms/receipts.
- [x] Prepare current and destination before action execution; explicit move scope and semantic review; reject pending/blocked targets at execution. New-session entry prep and old-session next-action prep.
- [x] GREEN runtime/integration tests and commit.

### Task 3: Public scene, map and preparation status
Files: app/agents/master/public_context.py or universal.py audience handling, app/core/universal/orientation_generation.py marker refresh as needed, web/src/game/masterStatus.ts and tests.
- [x] RED split-party destination privacy, no new offscreen knowledge, published prepared scene/objects on map, status copy and honest movement results.
- [x] Implement audience narrowing and persisted public checkpoint, preparation label, harmless geometry marker refresh preserving floor.
- [x] GREEN tests, generated contracts/types/build and commit.

### Task 4: Acceptance and delivery
Files: tests/test_universal_world_playthrough.py; docs/universal-world-expansion.md.
- [x] Whole existing-world -> props/NPCs -> tunnel -> entry -> persistence -> back -> retries/no duplicate time, library/other launch unchanged; recovery and provider failure, current migrations/lifespan where applicable.
- [x] Full Universal/exploration + affected phase tests, frontend/types/build/contracts, lint; one fresh independent review and one Important fix pass; graphify update.
- [x] Same combined container restart and read-only API/browser smoke, no live generation. Record remaining user playtest; commit and retain combined.


## Delivery evidence ? 2026-10-27

Implemented on feature/combined in commits acdbb43, 4326c74, 374a21c and 012a84b.
Final independent review found four Important issues; all fixed in the final pass, with regression coverage for result-card privacy, per-location multi-source narration/recovery, explicit blocked-phase retry, and current public conditions/evidence.

Verification: 401 Universal/exploration/map backend tests + 3 phase compatibility tests passed; 398 frontend tests passed. API contract regeneration/check, TypeScript/production build, owned Python Ruff and diff checks passed. Graphify AST update completed (14075 nodes, 47550 edges).

Same taleforge-app-1 container restarted from combined mounts; PostgreSQL taleforge_universal remains at universal_0008 head. Health/login/library and authenticated Chrome adventure/map/passages smoke passed. Before/after hashes of hero resources/sheet/location, library, original receipt, event count and game clock matched exactly. No live world-model calls or world phases were created during smoke.

Next real playtest: send a new in-game action (for example, ???? ? ????????). Existing running campaign develops before that action; completed old receipt is preserved. Model prose and real-provider behavior are deliberately left to this user playtest. Created structures retain their existing crossing policy; the far place develops before the next action there. Already-ready imported legacy rooms are reused.
