# Encountered NPC portraits

User requested image generation for encountered NPCs. Add the portrait flow to their existing inspect card. Use the configured local ComfyUI and technical English translator. Honor the user's preceding concern about worse replacements: generate candidates first, explicitly Apply the chosen variant. No automatic replacement and no gameplay mutations.

The existing inspect policy gates known NPCs, and only public name/observed description enter the prompt. Offscreen NPCs use an observed snapshot, never their current mutable appearance. Share candidates/selection only within campaign+NPC+public-source digest. Owner/master (or a platform admin with normal NPC access) creates and selects; participants view their authorized projection. All media routes enforce the same projection.

- [x] Write API regressions for encountered/hidden/foreign NPCs, source privacy, variants and explicit selection, permissions, replay/failure and changed description.
- [x] Add immutable NPC portrait attempts, pending leases, selected-image pointer, migration0015, settings and local portrait-specific adapters. Keep selection independent of generation.
- [x] Add NPC portrait component to EntityPopover, with protected thumbnails, fullscreen viewer, candidate previews and Apply. Avoid closing the parent popover when using its portal viewer.
- [x] Verify44 backend checks,422 frontend tests, build, real ComfyUI generation and native browser component/API interaction. No fake NPC spawned in the game; existing encountered cave rats used. New candidates were not applied automatically.
- [x] Independent review: extend normal observe to NPC snapshots; explicit generation remembers current nearby encounter, never offscreen mutable appearance. Add RED/GREEN regression for unplaced NPC/hero null locations; no fictitious encounter is recorded.
- [x] Incorporate user art direction steering: all new local images lead with painterly fantasy style; repo workflows reject photography. Second real candidate inspected and confirmed illustrated. Existing saved images retained.
- [x] Final graphify update succeeded without force:13185 nodes,36422 edges. Runtime universal_0015, correct feature branch; temporary auth removed. Source uncommitted, unrelated changes preserved.
