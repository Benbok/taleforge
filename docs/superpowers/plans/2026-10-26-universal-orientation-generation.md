# Universal orientation-map generation

Approved scope: generate once on first entry/start; explicit generation for existing campaigns; keep combined runtime and saved progress.

Design: reuse DeterministicLayoutProvider and geometry.build_area for a single cosmetic area. Infer a coarse visual shape from the public location description, otherwise use an open schematic. Show that scale/positions are approximate. Only existing public unowned scene objects become markers; do not invent world entities, exits, lore, loot or mechanical cover. Existing sketches/complexes remain unchanged. Store sketch+version on the current location with campaign serialization; reads do not generate. No model calls or migration required.

1. RED: generation is idempotent, preserves sketches and gameplay clock/resources/events, excludes private/owned objects, rejects stale/foreign locations. Cover first session and both normal/created-route travel.
2. GREEN: one shared service; authenticated POST for the controlled hero's current location; automatic hooks at session start and travel. Lock/recheck before saving. Refresh map viewers after explicit generation.
3. UI: missing-map button, pending/error/retry, refresh on success; no regeneration button for saved map; honest orientation copy. Tests for success/failure and play-as.
4. Verify full Universal/exploration and focused frontend tests/types/build, generated contracts, independent final review and fixes, graph update. Deploy same combined container and browser generation for the existing campaign without gameplay/time changes. Commit only owned changes; preserve initial parallel edits.

Completed: all four steps verified. 375 backend /388 frontend tests passed, types/build/contracts/lint passed. Independent review issues were reproduced and fixed. Same-container browser generation created the live campaign map; before/after probes confirm no gameplay changes. See ../../universal-orientation-generation.md.
