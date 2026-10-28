# Worlds catalog and single launch path — design

## Intent

Taleforge used to ship two hard-coded world packs ("Эхо Левиафанов", "D&D 5e SRD 5.1") whose rules were fixed in the
application. Worlds are now authored in the studio with their own configurable rules. The "Миры" tab and the way a game
is created still reflect the old model. This work makes the authored, published world the only unit a game starts from,
and makes starting a game one uniform path.

## What the user decided

- The "Миры" tab lists published worlds created by authors — **all authors, not only the viewer's own**. The two
  built-in packs and everything about them disappear.
- A world appears in the list **only after its author publishes it**. Drafts never appear.
- "Запустить" on a world card creates a **new, independent session of that world** and takes the administrator to that
  session's cabinet. The administrator configures everything there; the game itself starts only afterwards.
- **Any administrator** may launch another author's published world. The cabinet and the launch response must **not
  reveal the author's secrets** (hidden plot, secret NPC/location data) to the administrator, exactly as players never see
  them.
- The "+ Новая кампания" button is removed. A game can be created **only** through "Миры"; the old step-by-step wizard
  (`/new`) is retired.
- Existing tables created on the old packs are not migrated, shown or supported (same stance as the rest of the
  retirement work).

## Goals

1. "Миры" shows the published worlds of every author; each card shows only the public summary.
2. One launch action per card; it lands the administrator in the new session's cabinet.
3. No code path remains that creates a campaign from a built-in pack or from the old wizard.
4. Built-in pack catalog, pack detail page and their API are removed from the product.

## Non-goals

- Changing how worlds are authored or published (studio, publishing, validation).
- Moderation, ratings, search or categories for the catalog.
- A new cabinet: the existing session cabinet is reused.
- Migrating, archiving or listing old tables/campaigns that used the built-in packs.

## Anti-goals (failure even if it "works")

- A viewer or non-author administrator can read hidden world content through the catalog list, the card, the launch
  response or the new session's cabinet.
- A draft or unpublished/withdrawn world is launchable or visible.
- Two ways to start a game remain (old wizard or built-in pack launch still reachable by URL or API).

## Constraints

- Software facts from the current code (retirement branch `feature/universal-retirement`):
  - Published worlds are `AdventureVersion` rows (per `AuthorProject`), carrying `public_summary`; the bundle with
    private content lives in the same row and must never be part of a list.
  - `GET /api/adventures` lists only the caller's own versions and is admin-only; `POST /api/adventures/{version}/games`
    launches only for the project owner. Launch is idempotent through `request_key` and creates the game through
    `instantiate_adventure`.
  - The tab currently renders `GET /api/worlds` (built-in packs) in `web/src/pages/Home.tsx`; its cards open
    `WorldDetailPage` and start the old wizard.
  - Launch currently takes full `InstanceOptions` up front; the new flow creates the session with defaults and lets the
    administrator set them in the cabinet before the game starts.
- Authorization, secrecy, search/memory, LLM accounting and audio stay as they are.
- Only published worlds are visible; if a project has several published versions, **the latest version is shown**
  (builder-level call recorded by the design owner).
- Only administrators can launch; viewing the catalog follows the existing access to the Home page.

## Decisions made by the builder's judgment (not by the user)

- Show the latest published version of a project; older versions are not separately launchable from the catalog.
- Defaults for the options the old launch asked for (name, player count, master type, leveling, flags) come from the
  server's existing new-campaign defaults; the cabinet is where the administrator changes them.
- The catalog list uses a dedicated public summary shape; the private bundle is excluded by construction.

## Left to the builder

- Exact endpoint names and response shape for the catalog, and how the cabinet masks author-only content.
- How `WorldDetailPage` is replaced (a "details" view of the public summary, or removal if the card is enough).
- Removing the retired API, pages, tests and generated types, and keeping `openapi.json`/`api.gen.ts` consistent.

## Calls added after the builder check (the design owner's, not the user's)

- **Session before start:** the cabinet already edits an unstarted campaign (`PATCH /campaigns/{id}`, brief, flags,
  seats) and starting is a separate action (`POST .../session/start`). Launch creates the campaign through
  `instantiate_adventure` with the server's default options and does not start it. The builder confirms the cabinet
  covers name, players, master, leveling and flags; any missing setting is added to the cabinet, not to launch.
- **Secrets mask:** the catalog list and card expose only `public_summary`. The cabinet and launch response never
  include the private bundle or hidden plot/secret entities for a non-author administrator; the project owner launching
  their own world keeps full access. Masking covers every endpoint that returns campaign or world state to that
  administrator, and is tested for each.
- **Who sees what:** the catalog is visible to every signed-in user; only administrators see "Запустить". The existing
  owner-only launch rule is relaxed for administrators on the published-version launch endpoint.
- **Published means** an existing `AdventureVersion` row; there is no withdraw state today and none is added. "Latest"
  is the highest version number of a project.
- **Double launch:** the client generates a new `request_key` per click of "Запустить" and keeps it while the request is
  in flight, so a double click makes one session and a later launch makes a new one; the key is scoped per administrator
  (as today).
- **Order and card:** newest published first, no pagination at this stage; the card shows the author's display name,
  as the app already shows authors by name.
- **Built-in pack removal:** the builder checks for seeds, demo data, scripts and docs that still need the built-in
  packs. Tests that exist only for them are retired and listed in the existing test map; the rest of the suite must be
  green apart from failures already present on `feature/combined`.

## Verification (what "done" means)

- As administrator A: publish a world; as administrator B: it appears in "Миры", B launches it, lands in the new
  session's cabinet, sees no author secrets, configures and starts the game.
- A draft world never appears; a second version of a project replaces the first in the list.
- `/new` and the "+ Новая кампания" button are gone; built-in packs appear nowhere in the UI or API.
- Backend and frontend suites, contract regeneration, typecheck and build pass.
