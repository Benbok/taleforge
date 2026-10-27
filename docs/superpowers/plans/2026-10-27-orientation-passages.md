# Known passages on orientation maps

Approved: retain map appearance; show known entry/exit markers and readable states; inspection only. Work in combined and deploy same app.

Use only viewer-projected sketch exits and known destinations. Supplement missing geometry with a cloned display sketch; never persist schematic points as actual passages. Public descriptions may provide quoted direction annotations (unknown destination/state, explicit blocked return path); do not convert prose into travel permission. Hidden/rumoured/negated exits never become active markers. Server projection filters hidden adjacency so a historical link cannot reveal a secret passage.

TDD: projection/cloning and marker inspection; missing geometry, hidden/deduplicated/stable exits; existing sketch positions remain; statuses and keyboard interaction; no draft/socket actions, events, clock changes. Verify affected backend and frontend/full/types/build, one independent review, AST graph update, live map rendering and data invariance. Commit owned files only.

Complete: 381 backend /397 frontend tests, types/build/contracts/lint passed. Independent review findings fixed with RED/GREEN regressions. Same-container live map markers and inspection verified; gameplay state unchanged. See ../../universal-orientation-passages.md.
