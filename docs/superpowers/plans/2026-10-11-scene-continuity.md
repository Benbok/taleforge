# Scene continuity bug fix plan

**Goal:** Keep opening narration, registered NPCs, player dialogue and tool execution consistent, including streamed and malformed model output.

**Evidence:** Campaign c_31e87408c10d0101: the opening NPC remained a sketch; parse failed on an undersized Gemini cache; narration retries emitted JSON pseudo calls; the master invented another player's reply.

**Execution:** Implement and review in an isolated worktree, then transfer the changes into the user's checkout. Preserve unrelated edits. The user subsequently authorized a commit and rebuild/restart of the app container. Do not alter campaign data manually.

## Constraints

- Textual tool calls never authorize execution.
- Do not introduce unplanned NPCs, expose secret NPC details, or move existing parties on repeated preparation.
- Main narration may describe registered NPC speech; player speech belongs to the player.
- Provider errors unrelated to cache size retain existing failure handling.

## Tasks

1. [x] Add regression coverage for fenced, inline, malformed and truncated JSON pseudo calls in detection, cleanup, streaming and master retries. Watch it fail, extend the existing filter, rerun textcalls tests.
2. [x] Reproduce short Gemini system prompts and cache rejection using a provider boundary double. Disable explicit Gemini caching (retain Anthropic cache behavior), check parse integration and LLM tests.
3. [x] Reproduce missing opening NPCs and repeated preparation. Prepare only the first node's NPCs in its registered location using develop; send the factual scene and prior intro to hero introduction. Keep greeting at the table. Run opening tests.
4. [x] Reproduce a narrator answering for another player and a second unknown entity reference. Retry with explicit player ownership constraints; block repeated invalid narration; keep technical text out of streamed/voiced output. Run master and continuity tests.
5. [x] Run the Python suite and lint; review the diff and edge cases; transfer verified changes to the original checkout and record validation.

## Review focus

- JSON split across arbitrary chunk boundaries and an unfinished final object.
- Narrative prose with ordinary JSON must remain intact.
- Repeated opening preparation cannot duplicate or relocate established NPCs.
- NPC registration failure must stop introductions rather than publish unsupported dialogue.
- AI player turns and already submitted human dialogue must remain valid.

## Ledger

- Baseline: user edits exist in tests/test_worlds.py, web/src/pages/CampaignHeroPage.tsx and web/src/pages/HeroFlows.test.tsx; excluded from changes.
- Ruling: use the already installed Python environment; no dependency changes are necessary.
- Parallel workspace changes to JSON filtering, bare markup and location preparation were merged and tested. Existing frontend edits and tests/test_worlds.py remain outside this fix's commit.
- Review regressions cover partial JSON keys, no-argument function wrappers, ordinary nested JSON, module NPC room placement, multiline player dialogue, speaker attribution, untagged retry hallucinations and successful transitions.
- Opening preparation now waits for committed generation operations. Background intro preparation shares the startup lock and reuses the same plan version, fixing a duplicate-call race found by the combined suite.
- Final verification in the user's checkout: 706 passed, 3 skipped (221.18 s). Ruff and git diff checks passed. Independent review found no remaining material issues.
- The app image built successfully. Per the user's instruction, commit the reviewed files and recreate the app container from this image, then verify its health and deployed source.
