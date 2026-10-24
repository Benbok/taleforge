# Node 2: first universal adventure — verification

Date: 2026-10-24. Branch: `feature/universal-creative-studio`.
Node 1 checkpoint, including all user styling and starting equipment: `103ffd3`.

## Delivered

- World studio with saved structured fields, revision-bound master questions/review, explicit acceptance and immutable versions. Catalogs and full generation are optional.
- Independent campaign launches, remapped entry scene and isolated private world settings. Library heroes enter through a saved compatibility/adaptation proposal and explicit confirmation; source scores, gear and portrait remain intact. All new copies start L1/xp0.
- Bounded pure action math, campaign-scoped immutable profiles, free ordinary checks and priced magical effects.
- Atomic resource/effect/discovery receipts with replay protection. Actor state refresh after serialization prevents lost updates from preloaded concurrent sessions. Learned abilities retain their saved immutable revision.
- Freeform Universal master dispatch, public-only saved-outcome narration, configured provider/model selection, private questions and existing text voice delivery. Universal paths bypass the legacy catalog parser. Legacy engine selection is rejected.
- Persistent exploration screen: complete entry description, saved hero card, learned abilities with calculated cost and limits, shared chat/voice/session controls and reconnect.
- Additive migration `universal_0004` preserves existing universal data.

## Evidence

- **119 Python tests passed** in the final combined run: all `test_universal*.py` plus existing adventure launch/publication regressions. Includes Node 1 coverage and explicit WebSocket retry dispatch of a retained turn instead of waiting for a source that is no longer pending.
- **345 frontend tests passed**, 74 files; frontend typecheck and production build passed. Ability cost/limits display additionally checked after the final UI projection change.
- Ruff on every changed/new Python file, contract freshness and `git diff --check` passed.
- Full integration test uses actual REST studio/review/accept/launch/admission/session endpoints and WebSocket messages. It performs a free investigation and a paid invented ability, fails narration after the action commits, opens a fresh engine/service, resumes narration, reconnects, and verifies one debit/discovery, independent campaigns and unchanged library source.
- Additional tests cover natural-1 attack self-harm and replay, hidden targets, composite rollback/resistance, concurrent debit/damage, pinned learned revisions, automatic retry bounds and explicit retry, selected provider/model, private question audience and saved intro without catalogs.
- Running stack remains Compose project `taleforge`, app `taleforge-app-1`, database `taleforge_universal`, port 8000. PostgreSQL reports `universal_0004 (head)`; authenticated login/library HTTP smoke passed after restart.
- Real headless Chrome authenticated against the running container and rendered `/author` with “Творческая студия”. Screenshot inspected; no generation was invoked.
- `graphify update .` refreshes the AST knowledge graph without model calls.

## Scope and limits

No live paid LLM/image generation was used for verification. The complete adventure flow uses deterministic providers; live browser checking covers authenticated studio rendering. User playthrough with the chosen provider remains the next acceptance step before Node 3.

Balance remains provisional: see [numerical report](2026-10-24-universal-balance.md). Strong high-level attacks and automatic checks are flagged, not declared balanced. Scheduled effects, tactical combat, full equipment management and progression belong to later nodes. Existing large-bundle and mixed static/dynamic-import build warnings remain.

Implementation decisions: ordinary checks use an explicit profile kind; partial composite realization does not teach; learned profiles pin immutable definitions. Critical attack failure uses a predeclared bounded self-damage consequence of 1 HP. Old engine files remain physically present for later cleanup, but cannot be selected through `get_engine`.

Additional execution decisions: migration numbering follows existing portraits (`0004`); actor persistence/resolution/discovery share one transaction owner; compatible library copies also require confirmation; the node uses one integrated commit because contracts and runtime depend on each other. Native PowerShell replaced the unavailable Git Bash for the plan ledger. Agent thread limits prevented a further fresh final reviewer; math, studio and cross-boundary reviews plus root regression checks were completed. These choices cost extra confirmation/review effort or rework if revised; no merge, push or workspace removal was performed.

## Equipment regeneration follow-up

The saved hero card originally exposed creation-time equipment only, with no regeneration action. Added a visible library equipment control: “Создать снаряжение” for older heroes with no saved items, otherwise “Пересоздать снаряжение”. The master proposes one bounded weapon and armor; explicit confirmation replaces library equipment with revision/replay checks. Description, scores and existing campaign copies remain unchanged; errors retain old items. No equipment editor is exposed on game cards.

Verification:18 targeted backend tests and347 frontend tests passed; production build, contracts, Ruff and AST update passed. Authenticated Chrome inspected the running Docker app and found the creation button on the existing older hero card. No paid generation was invoked.
