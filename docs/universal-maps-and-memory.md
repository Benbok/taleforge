# Universal Node5: maps and public memory

Implemented on `feature/universal-creative-studio`, after Node4 (`669696d`).

The game header opens the existing map window in orientation mode. Known landmarks,
places and passages remain inspectable; zoom and optional saved geometry remain useful.
Ground and passage clicks never move a hero, edit the chat draft or spend game time.
Missing geometry has a useful text fallback. Author/legacy map presentation is retained.
Stale tactical WebSocket commands are rejected before entering legacy execution.

Movement in chat can bind `move.destination_id` to a known accessible exit. The server
validates campaign membership, visibility, adjacency and authoritative passage state
before execution, including hidden/locked passages omitted by the visual projection.
Movement saves the hero's place and knowledge with the ordinary replay-safe exchange;
it does not move other heroes or require a grid cell. Map reads do not create a Scene.

Narrator and prose reviewer consume the same saved public context: resolved outcomes,
audience-visible local scene, recent narration/dialogue and up to six relevant shared
KnownFacts. Retrieval reuses the existing BM25 index after campaign, subject and
recipient filtering. Global legacy summaries are deliberately excluded because they
can contain another split party's history. Secret discovery, private backstories,
adaptations and rescue counters do not become narrator memory. Damage and resisted
secondary effects stay separate factual outcomes. Longer scenes and dialogue are
allowed while player agency and established facts remain constraints.

The public context is checkpointed before text generation. Restarting narration reuses
that snapshot and the original recipients rather than importing later discoveries or
repeating mechanics. Published text is also the voice input. Ordinary successful
observation does not itself reveal a concealed object; public roll cards redact an
observation not visible to all recipients. Arriving in a new place does not disclose
its contents to heroes who remained behind.

## Verification, 2026-10-26

- 310 backend tests passed: complete Universal/exploration suites plus map-memory and
  topology coverage. One obsolete legacy map-memory migration test was excluded: it
  refers to removed revision `0025`. Current Universal migration coverage passed.
- 385 frontend tests passed across 84 files; TypeScript and production build passed.
  Existing bundle-size/dynamic-import warnings remain.
- Owned Python changes pass Ruff and `git diff --check`.
- Independent whole-node review found two Important issues (hidden-door bypass and
  split-party arrival disclosure). Both were reproduced with failing regression tests
  and fixed; the final suite above includes those tests.
- The whole-adventure scenario uses real Alembic upgrades from `universal_0001` to head
  and the app lifespan. It preserves a preexisting hero, accepts an authored world,
  creates two independent launches, admits a library copy, invents a learned ability,
  resumes failed narration with captured voice input, handles an expiring effect and
  potion, awards equal XP to two heroes, allocates growth, reads the map and reconnects.
  Replayed combat changes neither receipts, time nor rewards; library and other launch
  remain unchanged. No paid model or image generation was called.
- AST-only `graphify update .`: 13,803 nodes, 46,634 edges, 447 communities; no LLM calls.

No public HTTP/WebSocket schema was changed in Node5; the optional destination belongs
to the internal semantic action model. Existing unrelated provider/config/campaign
edits were preserved and excluded from commits. Actual literary quality still requires
a user playtest with the configured model. Node6 cleanup remains separate.

## Local runtime

The user subsequently requested integration into `feature/combined`, where they are
playtesting. Node5 was merged with its existing free-creation/model changes retained.
The same `taleforge-app-1` container continues to mount `.worktrees/combined`, using
the existing `taleforge_universal` database and media volumes.

Combined verification: 354 backend tests and 385 frontend tests passed; TypeScript
and production build passed. The obsolete legacy revision0025 migration test remains
excluded. Ruff passes for the merged Node5 Python files; the existing parallel
`test_exploration_master.py` has an unused import and two long lines outside Node5.
AST-only graph update completed (13,942 nodes /46,950 edges).

After rebuilding the combined frontend and restarting the same app container,
authenticated API/library smoke passed. Headless Chrome opened campaign
`c_d31978690fbfe4bd`, found the header map button, opened the orientation map and
confirmed that it exposes no tactical gameplay commands. No gameplay actions or
paid model calls were sent. Live prose quality remains a user playtest check.
