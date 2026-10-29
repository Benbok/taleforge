# Location artwork implementation

Spec: docs/superpowers/specs/2026-10-29-location-artwork-design.md. Execute inline in feature/universal-retirement; preserve unrelated dirty files.

- [x] Add regressions for access/current-room scope, public-only prompts, cache/idempotency, failure preservation and landscape parameters.
- [x] Add LocationArtwork attempts model and migration0009 with unique pending-room index and request receipt uniqueness.
- [x] Reuse configurable ComfyUI style and technical translator prompt/purpose with a separate location workflow.
- [x] Implement protected current-location status/generate/image API, bounded durable claims, stale-description detection and separate costs.
- [x] Add a keyed authenticated illustration component to UniversalAdventure, manual generation and pending polling without gameplay blocking.
- [x] Verify focused/backend migration/frontend checks, real local landscape, build, fresh review, contract and graphify update; restart only app.

User confirmed manual generation in the asynchronous preference reply.

Follow-up: the user requested opening images fullscreen within the app. Replaced the external blob link with a native modal dialog in a body portal, full-viewport sizing, contained image, Escape/button/background closing, focus restoration and scroll locking. Seven focused frontend tests pass; TypeScript/Vite build passes. Browser checks at390x844 and1440x900 confirm exact full-viewport dialog bounds, no new window, no page errors, and working close controls. Frontend bundle rebuilt for the running app.

Graphify update was run for the fullscreen follow-up but refused to replace12972 existing nodes with12958 rebuilt nodes. Existing graph preserved; no forced overwrite of curated data. This does not affect the frontend build or running viewer.

Validation:41 focused backend tests pass (including SQLite migration/check, concurrent requests and description-change rejection);402 frontend tests across84files pass; TypeScript+Vite and Docker builds pass; scoped Ruff and git diff --check pass. The full frontend run emits existing React hook warnings in UniversalWorldStudio tests, outside this change.

Fresh review found idle/ready participants did not refresh shared images and failed pending polls could stall permanently. Both corrected with RED-to-GREEN tests:15s ready/idle polling,2.5s pending,5s retry plus manual status retry. Real PostgreSQL trial caught an audit purpose longer than VARCHAR32; renamed to location_artwork_translation and added a schema-length regression. No important backend/access issues found by review.

Live landscape:1152x768, translation5.8s, total31.0s; saved as media/location-artwork-preview.png. Browser preview at800/390px has no page errors or horizontal overflow. Existing local compose override enables LOCATION_ARTWORK_ENABLED; only app recreated, PostgreSQL revision universal_0009/table verified, HTTP200 confirmed. There was no persisted live current-room scene for a read-only endpoint smoke check, so user worlds were not changed. Graphify updated. No commits/pushes.
