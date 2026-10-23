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

The Chrome run used **ScriptedLLM**, not a live provider. Live model quality and the complete PostgreSQL test suite have not been verified. PostgreSQL Docker startup was subsequently checked as recorded below. No public publishing was performed.

## Docker launch in the existing stack — 2026-10-23

At the user's request, the existing `taleforge` Compose project was switched to this branch on **http://localhost:8000**. Services retain the names `taleforge-app-1` and `taleforge-sfx-1`; their source mounts point to this feature worktree. Existing PostgreSQL, Redis, STT and tunnel containers were retained. The old `taleforge` database remains intact; the new schema is in `taleforge_universal` inside the same PostgreSQL container. Existing administrator/model settings are loaded from the main checkout's `.env` without copying or printing secrets.

The actual PostgreSQL migration exposed two SQLite-generated numeric boolean defaults in the initial baseline. Both now use portable `sa.true()`. The drift check also found the cyclic campaign/adventure-version foreign key omitted by PostgreSQL `CREATE TABLE` with `use_alter=True`; additive revision `universal_0002` creates it after both tables exist. Both regressions failed before their fixes and passed afterwards; the SQLite schema/state suite passed **6/6**. Actual PostgreSQL `alembic upgrade head`, `alembic check`, HTTP health, the new OpenAPI paths, administrator authentication and the universal library GET all passed. The existing administrator row survived the additive upgrade. No live LLM calls were made by these checks.

The local override is `.superpowers/docker-compose.current.yml` (ignored, contains local paths but no secrets). From this feature worktree the repeatable command is:

```powershell
docker compose --env-file ../../.env -f ../../docker-compose.yml -f .superpowers/docker-compose.current.yml -p taleforge up -d --no-build --no-deps app sfx
```

The app image was built from this branch. The SFX service uses its existing dependency image with this branch mounted at `/srv/app`; its prepared model cache is reused offline. A separate-port project was not started. Docker build context now excludes `.superpowers`, `.worktrees` and `graphify-out`.

## Independent review

One fresh-context reviewer audited Node 1 against the plan and spec. Three Important findings were reproduced with failing regressions and fixed:

1. The editor now binds its values to the form's original revision across background refetch. Adopting a new revision while keeping the draft requires an explicit reconciliation action.
2. The campaign chooser accepts the universal library shape and finishes after creating the already-approved independent copy, without legacy submission or an editor.
3. Chat edits receive the saved score allocation and editing instructions to preserve fields and allocation unless the user requests a change.

No minor findings were deferred by this review. The review intentionally did not establish Node 2+ combat, catch-up, progression, world admission, PostgreSQL behavior, live model quality or complete cross-subsystem authorization/audio/knowledge coverage. These remain outside this checkpoint, rather than being treated as tested.

## Remaining acceptance

The user still needs to view the working workshop. The local demo is `http://127.0.0.1:8723/heroes/new` while the demo process is running; its model is scripted. To run the regular app in this workspace, configure a new `DATABASE_URL` (default `sqlite+aiosqlite:///./taleforge-universal.db`), persistent `JWT_SECRET`, and model settings, then run `python -m uvicorn app.main:app`. Do not point it at the old database. The new frontend build is present locally.

## Complete backend suite and baseline comparison

`python -m pytest -n 4 -q --tb=line`: **2477 passed, 47 failed, 24 skipped** (16m32s).
This broad run started before the final review fixes. The final focused 43-test run and final frontend checks above cover those fixes. The full backend suite is **not green**.

The failures were separated using a clean archive of base commit `cf57f12`, extracted inside this feature workspace without copying the main checkout's uncommitted files or environment:

`python -m pytest -n 4 tests/test_layout_quality.py tests/test_layout_furnish.py::test_generated_furnishing_is_bound_to_area_cells tests/test_adventure_snapshot.py::test_export_has_maps_ports_anchors_geography_and_no_workspace_ids -q --tb=line`

The baseline comparison produced **27 failed, 87 passed**. Its 27 failing test IDs exactly match the feature run's map/detail/export failures. They are pre-existing; their code was not changed in this node. They include missing deterministic map details, missing generated furnishing, and an exported binding ID.

The remaining **20** failures exercise superseded contracts: **16** demand historical revision IDs and preservation/downgrade of legacy game data, and **4** expect the D&D library builder/world selector/preview paths. The approved fresh-baseline and descriptive-workshop decisions intentionally replace those behaviors. Their test retirement belongs with Tasks 25–26; they are retained and explicitly reported here rather than skipped or silently removed. New-schema preservation and new workshop behavior have separate passing tests.

### Pre-existing failures reproduced on cf57f12


- `tests/test_adventure_snapshot.py::test_export_has_maps_ports_anchors_geography_and_no_workspace_ids`
- `tests/test_layout_furnish.py::test_generated_furnishing_is_bound_to_area_cells`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.drowned_abyss_tail]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.drowned_flooded_womb]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.drowned_lighthouse]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.drowned_throat]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.hook_bell_monastery]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.hook_bell_tower_no_ringer]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.hook_echolite_heart]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.hook_hospital_mercy]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.hook_jelly_fields]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.hook_league_archive]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.hook_nameless]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.hook_tower_17]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.hook_unceasing]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.landmark_treasury]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.landmark_veche_bell]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.old_mother_heart]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.old_mother_skull]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.old_mother_womb]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.rib_forest_skull_chapel]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.whisperer]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.whisperer_ascension]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.whisperer_choirs]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.whisperer_neck_cells]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.whisperer_reliquary]`
- `tests/test_layout_quality.py::test_base_templates_have_populated_reachable_maps[location.whisperer_vault]`

### Retired migration-contract failures

- `tests/test_authoring_migrations.py::test_foundation_preserves_existing_game_and_children`
- `tests/test_authoring_migrations.py::test_geography_tables_upgrade_and_downgrade_keep_existing_rows`
- `tests/test_authoring_migrations.py::test_upgrade_repairs_ambiguous_0031[False-False]`
- `tests/test_authoring_migrations.py::test_upgrade_repairs_ambiguous_0031[False-True]`
- `tests/test_authoring_migrations.py::test_upgrade_repairs_ambiguous_0031[True-False]`
- `tests/test_authoring_migrations.py::test_upgrade_repairs_ambiguous_0031[True-True]`
- `tests/test_layout_store.py::test_sqlite_alembic_layout_phases_upgrade_and_downgrade`
- `tests/test_llm_accounting.py::test_llm_call_migration_upgrade_and_downgrade`
- `tests/test_llm_accounting.py::test_usage_coverage_migration_preserves_historical_unknown`
- `tests/test_map_memory.py::test_map_memory_sqlite_upgrade_downgrade`
- `tests/test_map_migrations.py::test_location_map_migrations_match_metadata`
- `tests/test_menu_music.py::test_menu_music_migration_is_reversible_for_existing_user`
- `tests/test_narrative_migrations.py::test_sqlite_alembic_narrative_foundation_upgrade_and_downgrade`
- `tests/test_sfx.py::test_sfx_migration_allows_multiple_playbacks_per_turn`
- `tests/test_sfx.py::test_sfx_migration_upgrade_and_downgrade`
- `tests/test_world_objects.py::test_sqlite_alembic_world_objects_upgrade_and_downgrade`

### Retired library-contract failures

- `tests/test_builder.py::test_library_preview`
- `tests/test_profile.py::test_library_hero_copied_into_campaign`
- `tests/test_worlds.py::test_copy_into_other_world_names_what_to_replace`
- `tests/test_worlds.py::test_library_hero_built_for_world`

Docker follow-up verification: the complete focused workshop/API/contract set passed **45/45** after the PostgreSQL fixes. Existing app authentication remained valid after container recreation. The new schema is at universal_0002; the old taleforge database still exists.

## Live Gemini creation failure — 2026-10-23

Two real creation requests were recorded as `invalid_proposal` despite successful provider responses. One bounded diagnostic reproduction found a valid score permutation but `explanations: {}`. The tool schema exposed explanations as an arbitrary dictionary, so the provider received no explicit six-field requirement. Server validation correctly refused the incomplete proposal.

The tool now names `str`, `dex`, `con`, `int`, `wis`, `cha` as required explanation properties. Server validation still enforces the exact starting array and nonempty explanations. Invalid responses now record safe validation paths/types/messages in the application log and LLM audit diagnostics, excluding response input, hero text and secrets.

Two regressions failed before this fix and passed afterwards. The complete creation/editing/workshop group passed **13/13**, ruff passed, and the generated API contract remained current. A single live verification with `gemini-3.5-flash-lite` returned six explanations and passed validation; the saved draft and hero were not mutated by either diagnostic call. The existing `taleforge-app-1` container was restarted to activate the fix, and HTTP health passed. This verifies the observed live failure case, not general model quality.

## Delete saved drafts — 2026-10-23

At the user's request, pending creation records now have a confirmed Delete action both in the workshop list and in the opened dialogue. Deleting an opened draft returns to the creation form. The API deletes only the owner's unconfirmed creation draft at the requested revision. Foreign drafts are hidden, stale revisions conflict, and confirmed dialogue records cannot remove a created hero. An in-flight model response cannot restore a deleted draft.

The new deletion and UI regressions were observed failing before implementation. Final verification: **52/52** focused backend/API/contract checks, **333/333** frontend tests, build and ruff passed. The full focused run also exposed Alembic's embedded logging configuration disabling application loggers; a failing regression was added and embedded migrations now preserve the application's logging configuration.

`taleforge-app-1` was restarted on the existing port 8000. A temporary smoke draft in PostgreSQL returned DELETE 204 and subsequent GET 404. Only that temporary verification record was deleted; user records were left for the user to manage. No LLM calls were needed for deletion checks.

## Workshop presentation and guidance — 2026-10-23

The workshop now presents the three creation stages, field examples and expandable keyboard-accessible hints, optional-field labels, and a description completion ring with a checklist. Completion counts the five trimmed nonempty description fields (20% each). Only identity is required to start; completion does not change hero mechanics. The dialogue uses separate message bubbles and a responsive six-ability proposal grid. Saved drafts have clear continuation statuses and retain confirmed deletion.

Verification: **335/335 frontend tests**, including completion/whitespace/optional-field and hint text-preservation checks; TypeScript and production build passed. Existing build warnings about the large bundle and mixed static/dynamic API import remain. Chrome checks covered the form and dialogue at 1440px and 390px with no horizontal overflow, the actual light/dark theme toggle, and starting a ScriptedLLM conversation at 20% completeness. No live model calls were made. The production assets are served through the existing container's branch bind mount at port 8000. Graphify was updated.

Visual references: [desktop](2026-10-23-hero-workshop-design-desktop.png), [mobile](2026-10-23-hero-workshop-design-mobile.png).
