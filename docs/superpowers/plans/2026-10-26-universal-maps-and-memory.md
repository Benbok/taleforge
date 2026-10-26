# Universal Maps and Memory Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, TDD and one independent final review.

**Goal:** Deliver Node5 orientation maps, grounded public memory/narration and whole-adventure acceptance.
**Architecture:** Reuse existing map visualizations and saved knowledge, disable tactical commands for Universal. One audience-safe public context feeds narrator/review/voice; action receipts remain the sole mechanics executor. Compose existing creation/launch/combat/growth services in acceptance.
**Tech Stack:** Existing FastAPI/SQLAlchemy/Pydantic, React/TypeScript/Vitest.
**Spec:** ../specs/2026-10-23-universal-creative-studio-design.md. Original requirements: 2026-10-23-universal-creative-studio-05-maps-and-narration.md Tasks22–24.

## Constraints

Keep feature/universal-creative-studio and the existing worktree/database. Preserve all heroes and launches. No paid model tests, merge, push or reset. Initial unrelated dirty files: app/agents/llm.py, app/agents/providers.py, app/api/schemas.py, app/config.py, app/core/campaigns.py; do not stage or overwrite them. Actual active master is universal.py/exploration.py, not legacy narrator helpers. Existing geometry is optional presentation; no invisible cell/feet walls in Universal actions. Map inspection never sends game commands or creates steps/rewards. Preserve author preview/generation tools and existing saved maps.

### Task 1: Read-only orientation map in the Universal game
- [x] RED map surface/passage clicks never step/traverse/insert drafts; inspection and zoom work. Server rejects old tactical socket commands before mutation. Hidden/private/foreign objects and inventory stay out; GET/read leaves receipts/clock unchanged; no-cell action works.
- [x] Implement Universal orientation mode in existing map window/components and add game entry. Reuse known-location/sketch projection with canonical visibility and optional geometry. Keep legacy author/preview visuals usable; only active Universal tactical paths disabled.
- [x] GREEN map/privacy/socket tests and targeted frontend tests; commit owned files.

### Task 2: Grounded public narration and relevant memory
- [x] RED shared facts/history/dialogue and relevant saved knowledge included; secrets/rescue counters/adaptations absent from narration/review/voice. Damage remains when binding resisted. Retry and changed audience do not reroll or leak.
- [x] Implement audience-scoped public context and persisted narration checkpoint using current Universal pipeline. Reuse memory/retrieval with campaign/recipient/known-subject filtering. Allow scene-appropriate detail and dialogue without forcing a short paragraph or inventing facts/actions. Preserve existing prose/link improvements.
- [x] GREEN narration/recovery/privacy tests; commit.

### Task 3: Whole persistent adventure acceptance and delivery
- [ ] RED accepted author world → two launches → independent library copy → invented ability → combat/effect/potion → equal XP/growth → read-only map → reconnect. Assert original/other launch unchanged and no private player/voice leakage.
- [ ] Compose existing services with actual migrations/lifespan in at least one path. Fix demonstrated integration gaps in owning modules; no new feature set or general editor.
- [ ] GREEN complete Universal/exploration suites plus affected map/memory/socket tests, frontend/tests/types/build, own-contract verification where applicable. Independent final review and one Important fix pass; graphify update after final code.
- [ ] Restart same Docker app and read-only browser/API smoke, write verification report and commit. Retain branch. User playtest remains before cleanup stage.
