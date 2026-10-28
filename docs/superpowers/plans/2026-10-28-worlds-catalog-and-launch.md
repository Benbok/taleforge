# Worlds Catalog and Single Launch Path Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** "Миры" lists published worlds of all authors; "Запустить" creates an unstarted session and opens its cabinet; the old built-in packs and the old "Новая кампания" path disappear from the product.

**Architecture:** A new read-only catalog endpoint exposes the latest published `AdventureVersion` per project with its `public_summary`. The existing launch endpoint is relaxed to any admin and made option-less (defaults), landing in the existing cabinet (`/c/{id}/manage`). A single guard decides whether a viewer may read the author's secrets, applied at every master-only read of `CampaignSecret`/plan. The built-in pack catalog (`/api/worlds`, `WorldDetailPage`) and the wizard (`/new`) are removed.

**Tech Stack:** Python 3.11+, FastAPI, SQLAlchemy async, Pydantic 2, pytest; React 19, TypeScript, React Query, Vitest.

**Spec:** [Design](../specs/2026-10-28-worlds-catalog-and-launch-design.md)

## Global Constraints

- Only published worlds appear; drafts never. Latest version = highest `AdventureVersion.version` of a project.
- Catalog and card expose `public_summary` only; the bundle, plot and secrets never appear in a list, card or launch response.
- Any administrator (`is_admin`) may launch any published world; the project owner keeps full access to their own world's secrets, every other administrator never reads them.
- Catalog visible to every signed-in user; "Запустить" only for administrators.
- Launch is idempotent per `(owner, request_key)`; the client makes a new key per click and keeps it while the request is in flight.
- Newest published first, no pagination, card shows the author's `User.name`.
- No migration of old tables; no schema change (no new migration).
- Ordinary tests use ScriptedLLM, no live models. After code changes run `graphify update .`.

## Review Focus

- Non-author administrator launches a world, then calls every master-only read (`GET /campaigns/{id}/secrets`, `PUT` of the same, `GET /campaigns/{id}/plan`, `GET /campaigns/{id}/master-panel`) — none returns author plot/setting (Task 1).
- A project with two published versions shows once, as the higher version (Task 2).
- A project with no published version never appears, even to its owner (Task 2).
- Double submit with one `request_key` creates one campaign; a different key creates a second (Task 3).
- A signed-out caller gets 401 from the catalog and launch (Task 2/3).

**Decision for the reader (flagged):** `POST /api/campaigns` is the creation primitive used by ~70 test files. This plan removes only its UI (button, wizard, links). The endpoint itself stays as an internal primitive (spec anti-goal "two ways to start a game" is met for the product, not for the raw API). Closing it fully means rewriting those tests; say so at review if you want that as a separate plan.

---

### Task 1: Author-secret guard

**Files:**
- Create: `app/core/authoring/access.py`
- Modify: `app/api/campaigns.py` (`get_secrets`, `put_secrets`, `get_master_panel`), `app/api/plan.py` (`plan_out`)
- Test: `tests/test_author_secret_access.py`

**Interfaces:**
- Produces: `async def author_secrets_visible(session: AsyncSession, campaign: Campaign, user: User) -> bool` — `True` when `campaign.adventure_version_id is None` (not launched from a world) or the version's `AuthorProject.owner_id == user.id`; `False` otherwise.

- [ ] **Step 1: Write failing tests** in `tests/test_author_secret_access.py`: build a published world by author A (reuse the publish helper used in `tests/test_universal_launch.py`), launch it as admin B, make B master (human master seat), then assert for B: `GET /api/campaigns/{id}/secrets` → 404, `PUT .../secrets` → 404, `GET .../plan` body has no `"plan"` key, `GET .../master-panel` has `has_plot == False` and no plot tool group. Same calls as A on A's own launch return the plot (`secrets["plot"]` non-empty).
- [ ] **Step 2: Run** `python -m pytest -n 0 tests/test_author_secret_access.py -q`. Expected: FAIL (B currently reads the plot).
- [ ] **Step 3: Implement** `author_secrets_visible` in `app/core/authoring/access.py`; call it in the three endpoints (404 `NotFound("нет доступа")` for secrets, omit `plan`/plot data for plan and master-panel). Builder greps `is_master` readers of `CampaignSecret`/`CampaignPlan`/`world.plot` (`app/agents`, `app/gateway`, `app/core/master_panel.py`) and applies the same guard to any other player-facing read it finds, with a test line per find.
- [ ] **Step 4: Run** the same test file. Expected: PASS; then `python -m pytest -n 0 tests/test_universal_launch.py tests/test_authoring_acceptance.py -q` still green (those that were green on `feature/combined`).
- [ ] **Step 5: Commit** `feat: only the author reads a launched world's secrets`.

### Task 2: Catalog endpoint

**Files:**
- Modify: `app/api/adventures.py`, `app/core/authoring/contracts.py`
- Test: `tests/test_worlds_catalog.py`

**Interfaces:**
- Produces: `class CatalogEntryOut(Contract)`: `version_id: str`, `project_id: str`, `title: str`, `author_name: str`, `version: int`, `public_summary: dict`, `published_at: str`. Route `GET /api/adventures/catalog` → `list[CatalogEntryOut]`, any signed-in user (`UserDep`), newest `published_at` first.

- [ ] **Step 1: Write failing tests** `test_catalog_lists_latest_published_version_of_every_author` (two authors, one project has v1 and v2 → one entry with `version == 2`; entries from both authors), `test_catalog_excludes_unpublished_projects`, `test_catalog_has_no_bundle_or_private_keys` (response JSON has only the `CatalogEntryOut` keys), `test_catalog_requires_login` (401), `test_catalog_visible_to_a_player` (non-admin gets 200).
- [ ] **Step 2: Run** `python -m pytest -n 0 tests/test_worlds_catalog.py -q`. Expected: FAIL (404 route).
- [ ] **Step 3: Implement** the route in `app/api/adventures.py` placed before `/{version_id}/games`; query: latest version per `project_id` joined to `AuthorProject.title` and `User.name`. Add `CatalogEntryOut` to contracts.
- [ ] **Step 4: Run** the file. Expected: PASS.
- [ ] **Step 5: Commit** `feat: catalog of published worlds of all authors`.

### Task 3: Launch by any administrator with defaults

**Files:**
- Modify: `app/api/adventures.py` (`launch`), `app/core/authoring/contracts.py` (`LaunchRequest`), `app/core/authoring/instances.py` (`instantiate_adventure` caller only)
- Test: `tests/test_worlds_launch.py`

**Interfaces:**
- Consumes: `author_secrets_visible` is not used here; launch response stays `LaunchReceipt(campaign_id, adventure_version_id, url)`.
- Produces: `LaunchRequest.options: InstanceOptions | None = None`. When omitted the endpoint builds `InstanceOptions(name=<AuthorProject.title>)`; every other field keeps its existing default. The owner check is replaced by `is_admin(user)` only; non-admin → 404 (as today, no hint).

- [ ] **Step 1: Write failing tests** `test_other_admin_launches_published_world` (admin B, no options → 201, campaign `owner_id == B`, `name == project title`, session not started), `test_launch_is_idempotent_per_request_key` (same key → same `campaign_id`; new key → different), `test_player_cannot_launch` (404), `test_launch_of_unknown_version_is_404`.
- [ ] **Step 2: Run** `python -m pytest -n 0 tests/test_worlds_launch.py -q`. Expected: FAIL.
- [ ] **Step 3: Implement** the relaxed check and optional options in `launch`; the receipt URL stays `/c/{id}`; the web client navigates to `/c/{id}/manage`.
- [ ] **Step 3b: Cabinet covers the launch options.** Test `test_cabinet_edits_what_launch_no_longer_asks`: on an unstarted launched campaign, `PATCH /api/campaigns/{id}` accepts and persists `name`, master type, leveling (`xp|milestone`), `excluded_themes`, `tts_enabled`, `creation_rules`; the number of players is changed through seats. A setting the cabinet cannot change today is added to `PATCH` (with the cabinet field in `ManagePage.tsx`), not to launch.
- [ ] **Step 4: Run** the file plus `tests/test_adventure_instances.py tests/test_universal_launch.py -q`. Expected: PASS (instances tests that failed on `feature/combined` stay as they were).
- [ ] **Step 5: Commit** `feat: any administrator launches a published world with default options`.

### Task 4: Retire the built-in pack catalog

**Files:**
- Delete: `app/api/worlds.py`, `app/core/worlds.py`, `tests/test_worlds.py`
- Modify: `app/main.py` (remove `worlds` import and `include_router`), regenerate `web/openapi.json`, `web/src/lib/api.gen.ts`
- Test: `tests/test_worlds_removed.py`

**Interfaces:**
- Produces: `/api/worlds` and `/api/worlds/{id}` return 404.

- [ ] **Step 1: Write failing test** `test_builtin_world_api_is_gone`: `client.get("/api/worlds")` and `client.get("/api/worlds/echo-leviathans")` → 404.
- [ ] **Step 2: Run** it. Expected: FAIL (200).
- [ ] **Step 3: Implement** the removals. Builder searches `rg "tests.test_worlds|core.worlds|api/worlds"` in `app tests tools web/src docs` and fixes every consumer: `tests/test_atlas.py` and `tests/test_standing.py` import fixtures from `tests/test_worlds.py` — move the fixture they need to `tests/game.py` if they pass on `feature/combined`, otherwise retire the test and list it in `docs/superpowers/reviews/2026-10-27-universal-retirement-test-map.md`. Then `python -m app.contract` and `npm --prefix web run gen:api`.
- [ ] **Step 4: Run** `python -m pytest -n 4 -q --timeout=60` and compare failures with `feature/combined` (49 known). Expected: no new failure.
- [ ] **Step 5: Commit** `refactor: remove the built-in world pack catalog`.

### Task 5: Worlds tab shows the catalog; launch opens the cabinet

**Files:**
- Create: `web/src/pages/WorldsCatalog.tsx`, `web/src/pages/WorldsCatalog.test.tsx`
- Modify: `web/src/pages/Home.tsx` (worlds tab renders `WorldsCatalog`), `web/src/lib/authoring.ts` (`catalog()`, `launch` with optional options)
- Interfaces: `catalog: () => api<CatalogEntry[]>("/api/adventures/catalog")` where `CatalogEntry` comes from generated types; `WorldsCatalog` props: `{ isAdmin: boolean }`.

- [ ] **Step 1: Write failing tests** in `WorldsCatalog.test.tsx` (mock `api`): renders a card per entry with title, author name and summary text; an admin sees "Запустить", a non-admin does not; clicking "Запустить" posts `{ request_key }` (no options) to `/api/adventures/{version_id}/games` and navigates to `/c/{campaign_id}/manage`; a double click sends one request (button disabled while pending); empty catalog shows an empty-state text.
- [ ] **Step 2: Run** `npm --prefix web test -- WorldsCatalog`. Expected: FAIL (component missing).
- [ ] **Step 3: Implement** `WorldsCatalog` with React Query, one `newRequestKey()` per click kept in a ref while pending (reuse the helper `NewCampaignPage` uses); remove the `FALLBACK_WORLDS`/pack code from `Home.tsx`.
- [ ] **Step 4: Run** `npm --prefix web test -- WorldsCatalog Home`. Expected: PASS.
- [ ] **Step 5: Commit** `feat(ui): worlds tab lists published worlds and launches them`.

### Task 6: Remove the wizard and old pack UI

**Files:**
- Delete: `web/src/pages/NewCampaignPage.tsx`, `web/src/pages/NewCampaignPage.test.tsx`, `web/src/pages/WorldDetailPage.tsx`, `web/src/pages/WorldDetailPage.test.tsx`, `web/src/lib/worlds.ts`
- Modify: `web/src/App.tsx` (routes `/new`, `/games/new`, `/worlds/:worldId`), `web/src/pages/Home.tsx` ("+ Новая кампания" button and the `/new` links near lines 181, 191, 552 now point to `/?tab=worlds`), `web/src/pages/AuthorProjectsPage.tsx` (text mentioning «Новая кампания»), `web/src/audio/applicationAudioCoordinator.ts` and its test (`/new` path)
- Test: `web/src/pages/Home.test.tsx` additions

- [ ] **Step 1: Write failing tests** `test_home_has_no_new_campaign_button` (admin Home does not render "Новая кампания"), `test_empty_tables_state_links_to_worlds_tab` (the empty-state call to action targets `/?tab=worlds`), `test_removed_routes_redirect_home` (`/new` and `/worlds/x` render the home redirect).
- [ ] **Step 2: Run** `npm --prefix web test -- Home`. Expected: FAIL.
- [ ] **Step 3: Implement** the removals; `/new`, `/games/new`, `/worlds/:id` become `<Navigate to="/?tab=worlds" replace />`. `rg "NewCampaignPage|WorldDetailPage|lib/worlds|\"/new\""` in `web/src` returns nothing but the redirects.
- [ ] **Step 4: Run** `npm --prefix web run typecheck && npm --prefix web test && npm --prefix web run build`. Expected: all green.
- [ ] **Step 5: Commit** `refactor(ui): remove the new-campaign wizard and built-in world pages`.

### Task 7: Final verification

**Files:** `README.md` (section on starting a game), `docs/superpowers/reviews/2026-10-27-universal-retirement-test-map.md` (retired tests).

- [ ] **Step 1: Run** `python -m pytest -n 4 -q --timeout=60`; compare failures to `feature/combined`. Expected: no new failure.
- [ ] **Step 2: Run** `python -m ruff check app tests tools`, `python -m ruff format --check app tests tools`, `python -m app.contract`, `npm --prefix web run gen:api`, `npm --prefix web run typecheck`, `npm --prefix web test`, `npm --prefix web run build`. Expected: all clean, no diff from `gen:api` after commit.
- [ ] **Step 3: Rehearse in the running container** (compose override `.superpowers/docker-compose.retirement.yml`): as admin A publish a world, as admin B open "Миры", launch, land in `/c/{id}/manage`, confirm no plot appears in the cabinet, start the session. Report what was not run.
- [ ] **Step 4: Update README** (one paragraph: games start only from "Миры") and run `graphify update .`.
- [ ] **Step 5: Commit** `docs: describe the single launch path`.
