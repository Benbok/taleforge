# Universal Action Boundary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement task-by-task. Steps use checkbox syntax.

**Goal:** Remove inconsistent model/runtime contracts and fictional explanations of technical failures before Node3.
**Architecture:** Semantic proposal → canonical server compiler → shared preparation/execution validation → atomic receipt → public result rendering. Keep the existing pure math, actor storage and Event receipts.
**Tech Stack:** Python/FastAPI/Pydantic/SQLAlchemy/pytest; React/TypeScript/Vitest.
**Spec:** [Approved design](../specs/2026-10-24-universal-action-boundary-design.md).

## Global Constraints

- Existing branch, worktree, database, characters, profiles and receipts remain intact.
- No Node3 mechanics, arbitrary model numeric effects or live paid test requests.
- Costs and all count arithmetic remain exact integers with decimal-string wire serialization.
- Preserve ownership, scene visibility, private deliberation and atomic replay protections.
- Preserve unrelated working-tree edits; stage only owned changes.

## Review Focus

- The real ordinary torch profile must resolve free even when the legacy outer label says ability.
- The real duration3/environment firefly proposal must become a technical unsupported result, never a world-magic prohibition.
- Malformed proposals get only one persisted repair; restart cannot reset the budget or replay effects.
- A stale/foreign/hidden target or exhausted resource is rejected consistently before preparation and during execution.
- Unsupported/denied outcomes must not be displayed with a success checkmark.

### Task 1: Shared failures, capabilities and validation

Files: new rules/universal/failures.py; core/universal/contracts.py and validation.py; modify core/universal/resolution.py; tests/test_universal_action_validation.py.
Interfaces: ActionFailure, ActionValidationError; ActionRef/ProposedAction/ResolutionContext remain import-compatible; capabilities()->dict; validate_action(ctx,proposal,require_saved_profile=True)->ActionState.
- [x] Write and run failing consistency, typed-failure, ordinary-check and unsupported-duration tests.
- [x] Extract shared checks and target/ownership/resource validation, invoke them from atomic resolution.
- [x] Run targeted math/resolution/discovery regressions; commit this task (70359db).

### Task 2: Semantic intent and canonical compiler

Files: new core/universal/action_intents.py and preparation.py; tests/test_universal_action_preparation.py.
Interfaces: ActionIntent/EffectIntent, legacy admission adapter; prepare_action(ctx,intent,source_id,known)->PreparedAction; no model I/O in validation transactions.
- [x] Write and run failing canonical type, bounded effect, target scope, known-reference and legacy-read tests.
- [x] Compile semantic choices into bounded server profiles; validate before immutable profile persistence; expose one capability registry.
- [x] Run preparation/shared-validation regressions; commit this task (117e689).

### Task 3: Durable admission, repair and factual narration

Files: new agents/master/action_admission.py and action_results.py; modify agents/master/universal.py; tests/test_universal_action_pipeline.py.
Interfaces: obtain_prepared_action with at most one persisted repair; public_turn_view/render technical failures from saved outcomes.
- [x] Write and run failing malformed proposal, repair budget/restart, firefly unsupported, provider failure and no-double-debit tests.
- [x] Wire the canonical compiler, record only validated executable admissions, preserve existing receipts and saved decisions.
- [x] Keep technical failures out of fictional narration; typed public failure metadata survives reconnect.
- [x] Run full universal backend regression and legacy transport tests; commit this task (085acd2).

### Task 4: UI, integration and review

Files: game/MessageView.tsx, lib/types.ts; corresponding tests; contracts and verification report.
- [x] Verify handled refusals show their actual reason rather than a success checkmark; preserve existing valid-message rendering.
- [x] Regenerate contracts; run frontend tests/typecheck/build and real read-only browser/Docker smoke.
- [x] Run final review, refresh graphify, record outcomes and limitations; commit and leave the branch in place.

### Task 5: Actual roll evidence (user extension, October 25)

Spec: ../specs/2026-10-25-roll-evidence-and-location-knowledge-design.md.
- [x] Record per-check and per-die proof in Universal receipts; project one stable chat card per receipt in the same transaction.
- [x] Display die faces, modifiers, totals, DCs and outcomes using exact counts; keep hidden defenses private.
- [x] Verify ordinary/multiple-target rolls, recovery, no duplicate cards and frontend rendering.

### Task 6: Location references and cumulative public knowledge

- [x] Link public places in Universal narration/intro using existing markup and current scene references.
- [x] Mount the knowledge inspector; refresh location cards and retain all hero-visible observations.
- [x] Verify location links, accumulating knowledge, private observation isolation and read-only browser smoke.

Verification: ../reports/2026-10-25-action-boundary-and-game-evidence-verification.md.
