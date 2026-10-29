# Home Journal Implementation Plan

> Execute inline with superpowers:executing-plans. Design approved in chat; preserve unrelated workspace edits.

**Goal:** Make the home page a useful journal of adventures without obsolete 5e claims.
**Architecture:** Extend the home API with pinned world metadata, retain routes and actions, use the existing themed React components.
**Tech Stack:** FastAPI, SQLAlchemy, React, Tailwind, Vitest.
**Spec:** docs/superpowers/specs/2026-10-29-home-journal-design.md

## Constraints and review focus

- Never use the latest project title/version for a pinned campaign.
- Keep role filtering and hero-dependent actions, including ended campaigns.
- Handle loading/errors/empty results explicitly; no invented catalog data.
- Keep player permissions, keyboard access, mobile layout and both themes.
- Preserve unrelated dirty files and generated API changes.

## Tasks

- [x] Add regression coverage for pinned metadata, featured selection, filters and catalog failures.
- [x] Extend app/api/home.py and web/src/lib/types.ts with world_version; prefer AdventureVersion.public_summary.title and pinned version. Regenerate OpenAPI and client contract, preserving existing changes.
- [x] Rework Home.tsx and CampaignCardView.tsx with a featured card, compact grid, hero sidebar and neutral footer; remove static world news and fallback catalog.
- [x] Run focused backend/frontend tests, frontend build and review the diff; update graphify.

## Execution record

Backend home and contract: 8 passed. Home frontend: 4 passed. Browser checks at 1440px and 390px in both themes: no horizontal overflow or page errors; role filtering works. Vite production bundle succeeds.

The initial full frontend run found two failures in applicationAudio.test.ts. Concurrent audio edits resolved these; the final full frontend run passes all 336 tests across 69 files. The final standard build's TypeScript phase remains blocked by the existing untracked UniversalWorldStudio.tsx (missing authoring API types/methods). These unrelated files were not changed by this task. The Vite production bundler succeeds separately.

Fresh review found the empty catalog incorrectly implied studio publication would populate the pack catalog. Fixed its explanation and routed authors to /new, where published adventures can be selected.

## Transfer to the requested branch

User directed all work to `feature/universal-retirement` in `D:/Workspace/Projects/taleforge/.worktrees/universal-retirement`. Transferred and adapted the implementation there, preserving the branch's URL tab navigation, protected hero portraits, universal character types and published-world catalog with direct launch. New adventure links open `/?tab=worlds`. Kept the branch's hero library, added an explicit catalog fetch error, and adapted the pinned-version regression to the universal studio fixtures.

Final verification in this worktree: 394 frontend tests across 83 files pass; 8 backend home/contract tests pass; the full TypeScript + Vite build passes; Ruff and git diff --check pass. Graphify update completed. Removed only this task's changes from main, preserving unrelated edits, including audio and DeepSeek. No commits or publication performed.
