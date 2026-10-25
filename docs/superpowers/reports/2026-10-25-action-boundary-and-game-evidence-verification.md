# Action boundary, roll evidence and location knowledge — verification

Date: 2026-10-25. Branch: `feature/universal-creative-studio`. Base: `43b5003`.

## Delivered

The model supplies semantic intent, which the server compiles and validates using a shared preparation/execution boundary. The runtime capability registry is also given to the model. Ordinary checks are free regardless of a legacy outer ability label; unsupported duration/scene/item mechanics produce typed Russian technical notices. Technical errors do not become fictional laws of the world. Proposal repair is limited to one persisted attempt; provider outages, saved admissions and receipts survive restarts. Failed provider requests are audited. Recovering narration never repeats an applied action.

Universal receipts now include every real die and every target's check. A deterministic chat card shows die faces, modifiers, exact totals, visible thresholds, results, energy and damage. Cards and action receipts commit together, use stable IDs and survive narration recovery without duplication. The model is asked to leave numeric roll reporting to these cards. Counts use decimal strings; the UI uses exact integers rather than floating-point rounding. Opponent creature defenses remain hidden.

Universal narration and session framing use the existing public entity references and inspector. Known names are linked in inflected Russian forms, unknown reference IDs are removed, and a location reference remains available even when a paragraph does not repeat the place name. Party-scoped narration renders as shared narration rather than a private whisper. Location cards collect all distinct visible observations; another player's private messages remain excluded. An open card refreshes after new narration. Leaving a place retains access to its known observations and last visible description without exposing later changes. Existing narration is enriched at read time using its saved public scene; no history rewrite is required.

## Verification

- Backend: **154 passed**, including every `test_universal*.py`, `test_ws.py`, `test_ws_waiting.py` and focused existing roll/link regressions in `test_game_screen.py`.
- Frontend: **358 passed** in 78 files (`npm test`). Typecheck and production build passed. Existing Vite bundle-size/dynamic-import warnings remain.
- Ruff passed for changed backend modules and regression tests. `git diff --check` passed.
- API contracts regenerated with `python -m app.contract` and `npm run gen:api`; no schema drift remained.
- Same Compose app `taleforge-app-1` restarted on port 8000 using the existing branch mounts and database. HTTP 200 and clean application startup verified.
- Authenticated headless Chrome opened a location reference from the real saved session and loaded the knowledge card. Screenshot: ignored local artifact `.superpowers/node2-studio.png`. No generation button was pressed and no paid test request was made.
- `graphify update .` refreshed the AST graph without a model call.

Tests cover the actual torch/firefly failure shapes, malformed proposals, bounded repair across provider failures, known-profile semantic changes, scoped targets, resource rejection, exact roll proof, multiple targets, hidden defenses, narrator crashes, no duplicated effects/cards, cumulative and private observations, legacy message projection, party links and location memory after leaving.

## Review and decisions

Independent review found two action-boundary issues: known references could discard changed semantics, and provider failures could lose their category across restarts. Both have reproducing regressions and fixes. Extension review found missing party-narration location links and lost access after leaving a place. Both were reproduced RED and verified GREEN. The technical-notice observation finding was upgraded from minor to important: persisting engine messages as location knowledge violates the public-fiction boundary. Its mixed-turn regression was reproduced RED and passed after filtering saved notices. No review findings remain deferred.

Ruling: execute the sequential compiler/validator refactor with one implementation owner and independent final review; this avoids competing changes to shared contracts, at the cost of relying on tests and that final review for independent validation.

Ruling: Node3 duration, arbitrary item and scene-effect mechanics remain unavailable, as requested; the cost is that firefly illumination with a persistent scene effect still receives an honest unsupported notice until its planned mechanics are implemented.

Ruling: keep a strict legacy admission reader for existing saved profiles and receipts; this preserves ongoing sessions, at the cost of retaining a transitional compatibility surface with dedicated tests.

Ruling: keep the existing game policy that hero AC is public and creature AC is hidden. This preserves existing roll behavior; if hero defenses later become private, the roll projection must be narrowed as well.

Ruling: old receipts lacking per-die/per-target details are shown only with the evidence they actually saved. No retrospective dice are invented, at the cost of less detail for recovered older actions. Completed old actions are never replayed merely to add a card.

The branch/worktree and unrelated user frontend edits remain in place. Only this task's files are committed; no merge, push, database reset or automatic paid verification is performed. The full legacy D&D test suite is outside this verification; the reported backend count is the scoped suite above.
