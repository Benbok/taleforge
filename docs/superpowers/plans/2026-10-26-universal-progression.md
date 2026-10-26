# Universal Progression Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans inline, TDD, one final independent review.

**Goal:** Deliver Node4 XP, safe allocation, copy catch-up and reproducible balance acceptance.
**Architecture:** Exact pure growth arithmetic; campaign-locked Event receipts for awards/allocation/admission; existing HeroBudget owns points, existing resources carry private revision. No parallel ledger table or general game-card editor.
**Tech Stack:** Existing Python/FastAPI/SQLAlchemy/Pydantic and React/TypeScript.
**Spec:** ../specs/2026-10-23-universal-creative-studio-design.md. Original requirements: 2026-10-23-universal-creative-studio-04-progression-and-balance.md Tasks18–21.

## Constraints and rulings

Keep current branch/worktree/database. Preserve original heroes and copies. Every constructor creates L1; catch-up is a separate recorded admission operation. User explicitly requested proceeding after Node3, so no repeat design approval. Current numeric proposals are version1 prototype configuration; document balance flags rather than silently changing formulas. No live paid model calls.
Awards are trusted master decisions bound to a saved achievement, not user-supplied XP. AI may propose bounded difficulty for successful exploration/victory/quest; server checks persisted evidence and awards each achievement once to eligible local participants. Replaying narration does not grant again. Allocation is player-confirmed and does not consume combat time.

### Task 1: Exact growth and durable equal XP awards
- [x] RED pure thresholds21/100/huge XP, equal full awards, replay/binding/scope.
- [x] Implement progression arithmetic, growth budget validation, once-only award receipts and resource delta refill.
- [x] GREEN focused tests and commit.

### Task 2: Authenticated allocation and in-game controls
- [x] RED budget/stale/concurrent/replay/dead/scope and frontend confirmation.
- [x] Implement owner endpoint and authoritative revision, partial refill, allocation panel integrated with current game card.
- [x] GREEN relevant backend/frontend checks and commit.

### Task 3: Separate one-time copy admission catch-up
- [x] RED L1 snapshot before catch-up, L10/18 points, unchanged original, replay and foreign/dead group exclusion.
- [x] Implement server-computed party level after both creation paths; persist L1 admission and catch-up receipts, no client target level.
- [x] GREEN creation/admission/allocation regressions and commit.

### Task 4: Achievement integration, balance and acceptance
- [x] RED saved achievement evidence/dedup and complete XP→allocation→catch-up→reconnect scenario; deterministic actual build budgets.
- [x] Integrate bounded master reward proposal with saved exchange, actual public reward cards, no XP for routine repeated actions. Extend balance report for L1/10/20/100/1000 and specialist/even builds using real growth/item/attack formulas.
- [x] GREEN full Universal/exploration tests, contracts, frontend tests/types/build, one fresh independent review and important fixes, graphify update.
- [x] Generate version1 balance report, restart same Docker app, read-only smoke, commit and retain branch. Report unperformed checks honestly.

Implementation and automated acceptance completed 2026-10-26. 287 backend /383 frontend tests pass. See ../../universal-progression.md for version1 reward policy, balance flags, review fixes and Docker smoke. User playtest remains before next node.
