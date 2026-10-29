# Admin equipment regeneration plan and delivery ledger

Spec: `docs/superpowers/specs/2026-10-29-equipment-artwork-regeneration-design.md`.
Worktree: `feature/universal-retirement`, existing universal-retirement checkout.

- [x] Add failing API tests for admin-only replacement, mode-bound replay, old image retention on failure, shared library/game selection and late old receipts.
- [x] Add migration0014 and success-selection timestamps; bypass cache only for explicit authorized regeneration. Cache copies inherit original selection time.
- [x] Add role metadata and server enforcement on both endpoint families, capturing the role before rollback-capable operations.
- [x] Add failing UI replacement test; implement admin action, retained old thumbnail while pending and periodic ready-state refresh.
- [x] Prepend armor silhouette to the equipment-only diffusion prompt and exclude texture swatches. Preserve type through translation.
- [x] Independent review: fix cache-receipt conflict recovery to bind operation mode as well as source. Observe race regression RED, then GREEN.
- [x] Verify23 focused backend tests,417 frontend tests, API contract, ruff, TypeScript/build. Existing permissions, migration, inventory and cache regressions included.
- [x] Restart local app and apply universal_0014. Use real browser to click regeneration on the screenshot hero's armor; verify old thumbnail remains during generation and new image is selected. Result:25.32s, complete cuirass, no browser errors. Temporary auth file removed by helper. Old immutable image remains stored.
- [x] Update graphify after final changes:13118 nodes,35886 edges, no force. Preserve unrelated dirty files and leave source uncommitted.
