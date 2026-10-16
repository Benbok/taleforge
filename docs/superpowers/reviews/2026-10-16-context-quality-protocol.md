# Context quality protocol

The offline evaluator uses the same seeded world and mechanical policy for
`legacy`, `v1`, and `revised`. The context variant is a test label; it is never
read from campaign settings or exposed through the API.

The first pass is a context replay: it checks required and forbidden facts,
block sizes, tool schemas, retries, fallback reasons, and unknown provider usage.
The second pass is a product replay: it includes early completion and tool
profiles and reports the total calls and cost separately. A failed or retried
call remains in the denominator.

The manifest in `tests/fixtures/context_quality.json` covers twelve scenario
classes: speech, old promises, hidden search, combat effects, multipart actions,
two heroes, split party, transition, resume, uncertain parsing, world reactions,
and NPC motives. The manifest is structural; it does not claim that scripted
text is literary quality evidence.

Acceptance gates:

- no required fact or mechanical outcome is lost;
- no forbidden fact is visible to the narrator audience;
- revised context reduces measured input size on the fixed packet set;
- failed, fallback, and unknown-usage rows remain visible;
- live prose is reviewed separately by a human using the same model/settings.

No paid run is part of this implementation pass. A live comparison requires a
new isolated campaign, a fixed provider/model, and a budget agreed before it is
started.
