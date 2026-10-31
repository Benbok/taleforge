# Campaign Covers Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Generate world covers in campaign settings and show large/thumbnail covers on Home.

**Architecture:** Reuse ArtworkRecipe/service for claims, accounting, protected storage and the latest successful image. Add a world-scene adapter using the existing portrait provider, and expose cover URLs in room and Home projections.

**Tech Stack:** Python, FastAPI, SQLAlchemy, React, TypeScript, pytest, Vitest.

**Spec:** `docs/superpowers/specs/2026-10-31-campaign-covers-design.md`

## Global Constraints

- Only the owner generates; campaign members view protected media.
- No automatic paid generation; request keys survive uncertain network errors.
- Existing cover remains visible during regeneration and after failure.
- Use public world metadata only; no private briefs or secrets.
- Preserve unrelated uncommitted work.

## Review Focus

- Outsiders and players cannot generate; outsiders cannot download images.
- Replay and concurrent requests cannot start duplicate image calls.
- Failed or stale attempts preserve the last ready cover.
- Worlds without a public introduction use public catalog metadata/name.
- Unsaved settings and unavailable images have clear UI states.

## Task 1: Server lifecycle and providers

Files: `app/core/campaign_covers.py`, `app/agents/campaign_images.py`, `app/api/campaign_covers.py`, `app/main.py`, `app/agents/portraits.py`, `app/api/home.py`, `app/api/schemas.py`, `app/api/campaigns.py`, `tests/test_campaign_covers.py`.

- [ ] Write API tests for generation, replay, stale/failing attempts, authorization, thumbnail delivery and Home URLs; run them and confirm missing-route failures.
- [ ] Add the campaign recipe, protected image/thumbnail endpoints and configured scene adapters. Extend Gemini's adapter with optional art direction/aspect ratio while preserving portrait defaults.
- [ ] Add nullable cover URLs to room/Home projections. Run targeted server and existing artwork/provider tests.

## Task 2: Settings and Home UI

Files: `web/src/cabinet/CampaignCoverStudio.tsx`, `web/src/cabinet/SettingsTab.tsx`, `web/src/components/CampaignCoverImage.tsx`, `web/src/components/CampaignCardView.tsx`, `web/src/lib/types.ts`, `web/src/lib/campaign.ts`, related UI tests.

- [ ] Write tests for manual generation, disabled unsaved settings, replay after uncertain errors, and full/thumbnail presentation; confirm failures before implementation.
- [ ] Implement studio with busy/error/retry states and React Query invalidation, protected image rendering, a responsive large featured cover and thumbnails on other cards.
- [ ] Run relevant Vitest tests and production build.

## Task 3: Final verification

- [ ] Run server and frontend suites, lint changed Python files, inspect diff, update graph with `graphify update .`.
- [ ] Review changes, record checks and any limitations. Leave changes in the shared working directory for review without committing unrelated work.

## Execution ledger

- Ruling: implement in the current shared checkout to preserve the user's ongoing changes; no branch operations or commits are needed for this request.
- Ruling: the user's “да” approves the proposed button-based scenario; execute inline without further workflow confirmations.
