# Universal orientation-map generation

Integrated into `feature/combined`, using the existing container and database.

Locations without a saved sketch receive a schematic outline when the session starts
with heroes present or a hero enters via a known destination or created structure.
Existing running games can create the current place's sketch from the map window.
The authenticated POST accepts the location currently displayed for the controlled
hero/master, including play-as, shared-scene heroes and the master's party fallback.
A stale or foreign location is rejected. Map reads remain read-only.

Generation reuses `DeterministicLayoutProvider` and `geometry.build_area`. A coarse
outline follows the public description; otherwise it is an open schematic. Automatic
provider scenery is removed. Only existing public, unowned scene object entities
become markers; narrative-only props remain in the description until represented by
saved entities. Positions and scale are explicitly approximate. This is a local
schematic operation with no model/image-generation calls. It creates no world objects,
enemies, loot, passages, cover bonuses, rewards or game steps.

Campaign serialization and a fresh location check ensure simultaneous/repeated
requests save one sketch. Saved sketches, complexes and module rooms are preserved.
Generated sketch and version live in the location state; no database migration is
needed. The UI shows pending/error/retry states and refreshes after publication.

## Verification

- 375 backend tests passed across Universal/exploration, map-memory and topology.
  The obsolete legacy map-memory migration test referencing removed revision0025
  remains excluded; current Universal migration tests passed.
- 388 frontend tests passed; TypeScript and production build passed. Existing
  bundle-size/dynamic-import warnings remain. Updated OpenAPI/TypeScript contracts
  pass `python -m app.contract --check`; owned Python changes pass Ruff/diff-check.
- Independent review identified inherited scenery/marker overlap and differing
  current-place semantics. Both were reproduced RED and fixed GREEN. Tests also
  cover concurrent requests, long marker IDs and preservation of authored maps.
- The combined app was restarted. Authenticated Chrome opened campaign
  `c_d31978690fbfe4bd`, created its current sketch and rendered the geometry. A
  before/after database probe confirmed unchanged hero sheets/resources/locations,
  library sheets, game clock and event count; saved orientation maps increased0→1.
- Parallel free-magic work was preserved. Its author committed initial backend hooks
  together with their changes in `0e389de`; subsequent fixes/UI/contracts are recorded
  in the orientation-generation commit. No merge/reset of that parallel work occurred.
