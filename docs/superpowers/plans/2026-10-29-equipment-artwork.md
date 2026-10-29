# Equipment Artwork Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax for tracking.

**Goal:** Explicit local equipment image generation with reusable saved art and inventory thumbnails.
**Architecture:** Campaign-scoped content cache with immutable leased attempts, protected item endpoints, existing ComfyUI/translation adapters and a focused React component.
**Tech Stack:** FastAPI, SQLAlchemy, Pillow, React, ComfyUI RealVisXL.
**Spec:** docs/superpowers/specs/2026-10-29-equipment-artwork-design.md

## Global Constraints
- Work only in feature/universal-retirement and its existing worktree; preserve unrelated changes.
- No gameplay mutations, automatic generation, cloud image fallback or cross-campaign cache access.
- Translate public visual details only; protect originals and 256-pixel WebP thumbnails.

## Review Focus
- Virtual starter items resolve without modifying inventory.
- Concurrent identical-item requests perform only one generation.
- Item access and public descriptions can change during generation.
- Cancellation, abandoned leases and invalid image bytes permit recovery without publishing broken files.
- Late UI responses never appear on another item's card.

### Task 1: Select a local image profile
- [x] Generate sword, armor and ring with identical seeds at 768/20 and 1024/20; inspect full-object composition and record timings.
- [x] Add equipment-specific workflow, translation and style factories, leaving existing profiles unchanged.

### Task 2: Persist and authorize artwork
- [x] Write failing API tests for cache reuse, distinct descriptions, permissions, virtual starters, failures and pending recovery.
- [x] Add migration/model and Pillow dependency; implement public-profile resolution, digest, durable claim, translation/generation, validated files, thumbnail, audit and protected reads.
- [x] Register settings and router; run focused backend and existing image/inventory regressions.

### Task 3: Integrate inventory UI
- [x] Write failing component tests for explicit generation, thumbnails, original viewer, pending/retry and component replacement.
- [x] Add focused EquipmentArtwork component; share fullscreen viewer with location artwork; insert into UniversalCombatPanel.
- [x] Run frontend tests, typecheck/build and browser smoke check.

### Task 4: Deliver locally
- [x] Document profile and usage; update OpenAPI; review changes and run graphify update.
- [x] Build/restart local app, apply migration and enable equipment generation in local runtime; verify health and real endpoint behavior.
- [x] Report verified behavior and any limits, with no claim of an unperformed live test.

## Delivery ledger

- Existing user-approved approach executed inline; no new approval gate or commit of unrelated changes.
- Profile selected after six local generations: 768/20, full items on plain backgrounds.
- Backend: 44 focused tests passed, including concurrent generation and concurrent cached receipts, fresh boot/migration checks and API contract. Frontend: 414 tests passed; typecheck/build and ruff passed.
- Independent review findings fixed: durable cache-hit receipts, retryable image downloads and rollback-safe concurrent cache recovery.
- Local PostgreSQL upgraded through universal_0011; app restarted with equipment artwork enabled. Live request generated the existing hero item in 18.3s; replay after restart returned cached art in 0.15s. No inventory/time changes.
- Browser checks at 390x844 and 1440x900: no overflow, exact viewport dialog, lazy original download, Esc/close, one window, no JS errors.
- Initial graphify update refused a smaller extraction; final incremental update succeeded without force: 13060 nodes, 35682 edges. HTML skipped by the graph's 5000-node visualization limit.
- Source changes remain uncommitted in feature/universal-retirement. ComfyUI and application remain available; temporary Vite preview stopped.
