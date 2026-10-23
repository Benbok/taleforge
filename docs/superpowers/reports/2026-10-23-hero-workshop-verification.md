# Hero workshop — Node 1 verification

Date: 2026-10-23. Branch: `feature/universal-creative-studio`.
Workspace: `D:/Workspace/Projects/taleforge/.worktrees/universal-creative-studio`.

Node 1 implements Tasks 1–5 from [the hero workshop plan](../plans/2026-10-23-universal-creative-studio-01-hero-workshop.md).
Nodes 2–6 are not implemented at this checkpoint. The plan requires the user to view the working workshop before Node 2 starts.

## Delivered behavior

- A newly named SQLite database is initialized with the frozen `universal_0001` baseline. A populated legacy schema is rejected before application bootstrap writes; existing databases are never deleted or adopted. Later nodes must use additive migrations.
- Existing authorization, authoring, knowledge, LLM accounting and audio tables remain in the baseline. The original checkout's uncommitted database/LLM changes and test files were not copied or altered.
- `/heroes/new` starts with descriptive fields. Creation questions, answers, explanations and revisions persist. GET does not call the model. A failed first model request leaves a resumable draft.
- Confirmation creates one L1/xp0 hero with precisely 15/14/13/12/10/8. Direct campaign creation and admin premades use the same constructor; no catch-up points are awarded in the constructor.
- The complete card displays descriptions, six scores/modifiers, HP, five reserves, AC, equipment and learned-ability sections. Descriptive capabilities grant no executable abilities. Private history and hidden death counters are excluded.
- Base heroes can be edited manually or through persisted master proposals. Both use one server validator, owner checks, SQL revision checks and replay receipts. Manual controls swap values rather than accepting unlimited scores. Preview does not mutate the saved card.
- Campaign copies are independent, are returned as read-only universal cards, and reject both library edit endpoints and the legacy campaign card editor. Copy selection does not call the legacy submission endpoint.
- Unbounded values use exact Python integers and decimal strings on the wire. The client formats and compares them using BigInt.

## Evidence

- Initial API/profile baseline before changes: **18 passed**.
- Final workshop, API and contract check: **43 passed**. Command:

  `python -m pytest -n 0 tests/test_universal_schema.py tests/test_universal_state.py tests/test_universal_hero_math.py tests/test_universal_card.py tests/test_universal_creation.py tests/test_universal_editing.py tests/test_universal_hero_workshop.py tests/test_api.py tests/test_contract.py -q`

- Complete frontend suite: **331 passed, 69 files** (`npm --prefix web test`).
- `npm --prefix web run build`: passed. Existing bundler warnings concern bundle size and an ineffective dynamic import of `api.ts`.
- `python -m app.contract`, `npm --prefix web run gen:api`: completed; generated REST types include universal cards.
- Whole-repository `ruff check .`: passed after formatting the frozen migration.
- SQLite `alembic upgrade head` twice: passed; real application startup/restart and persisted hero restart: passed.
- Chrome: actual local HTTP server, real React UI and SQL database. Creation → manual preview/confirmation → chat preview/confirmation → navigation reload passed. Screenshot: [workshop](2026-10-23-hero-workshop.png).
- `graphify update .`: completed after implementation; large HTML visualization was skipped automatically, while graph JSON/report were updated.

The Chrome run used **ScriptedLLM**, not a live provider. Live model quality and PostgreSQL have not been verified. No deployment or publishing was performed.

## Independent review

One fresh-context reviewer audited Node 1 against the plan and spec. Three Important findings were reproduced with failing regressions and fixed:

1. The editor now binds its values to the form's original revision across background refetch. Adopting a new revision while keeping the draft requires an explicit reconciliation action.
2. The campaign chooser accepts the universal library shape and finishes after creating the already-approved independent copy, without legacy submission or an editor.
3. Chat edits receive the saved score allocation and editing instructions to preserve fields and allocation unless the user requests a change.

No minor findings were deferred by this review. The review intentionally did not establish Node 2+ combat, catch-up, progression, world admission, PostgreSQL behavior, live model quality or complete cross-subsystem authorization/audio/knowledge coverage. These remain outside this checkpoint, rather than being treated as tested.

## Remaining acceptance

The user still needs to view the working workshop. The local demo is `http://127.0.0.1:8723/heroes/new` while the demo process is running; its model is scripted. To run the regular app in this workspace, configure a new `DATABASE_URL` (default `sqlite+aiosqlite:///./taleforge-universal.db`), persistent `JWT_SECRET`, and model settings, then run `python -m uvicorn app.main:app`. Do not point it at the old database. The new frontend build is present locally.

The complete backend test run was also launched; its result and any legacy-contract failures are recorded below when it finishes. Focused Node 1 checks above are distinct from the full legacy suite.
