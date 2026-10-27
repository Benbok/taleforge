# Known entrances and exits on the orientation map

Implemented in `feature/combined` without rebuilding saved maps or changing their
visual style. Current-location passages have labelled boundary markers. Inspection
shows known destination, open/closed/locked/blocked/unknown state and source details.
The selected card follows server state updates. Click/Enter/Space only inspect;
movement remains a chat action.

Existing projected sketch passages retain exact positions. Known logical directions
and unplaced exits receive approximate boundary positions on a cloned display sketch.
Multiple markers use separate floor-boundary positions where available. Hidden routes
are excluded at both endpoints, including reverse-only historical links. Unknown
saved states no longer normalize to "open".

For public directions only described in the location's text, conservative observed
passage phrases become quoted display annotations. They have no destination or
confirmed passability; an explicit unavailable return path is marked blocked.
Hidden, hypothetical and negated phrases are omitted. These limited annotations
supplement structured data, deduplicate matching labels and do not act as a general
natural-language world parser. They create no entities, links or travel permissions.
Approximate positions and unknown information are disclosed in the UI.

Verification:

- 381 backend tests passed (Universal/exploration plus map-memory/topology). The
  obsolete migration test for removed revision0025 remains excluded; current
  Universal migration tests passed.
- 397 frontend tests passed; TypeScript, production build, owned Python Ruff,
  `git diff --check` and generated-contract check passed. Existing build size warnings
  remain.
- Independent review found a hidden reverse-link leak and inaccurate annotation of
  negated/conditional phrases. Both were reproduced RED and corrected GREEN. Additional
  regressions cover duplicate boundary positions, simultaneous structured/prose
  directions and live updates of the inspected passage state.
- Same combined container restarted (Docker Desktop/db/redis/app had been stopped).
  Chrome opened `c_d31978690fbfe4bd`, rendered and inspected the tunnel and blocked
  return markers. Runtime probes confirmed unchanged hero sheets/resources/locations,
  library, clock and event count. No gameplay or paid model call was submitted.
- AST-only graph update was run after final code changes.
