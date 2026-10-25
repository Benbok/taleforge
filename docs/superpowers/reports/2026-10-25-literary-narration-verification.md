# Literary scene narration without repeated campaign headings

User request: remove the redundant campaign/location title above each chat response and make narration an artistic interpretation of the saved check result, with at least one or two substantive paragraphs.

Removed the automatic location heading from public/party narration and whisper rendering. Inline entity/location references still open the existing knowledge inspector. Existing message content is retained; old generated prose is not silently rewritten or regenerated.

The authored entry placeholder previously used the campaign title as its location name. New publications now use a neutral entry label. Existing instances receive the same public label in scene projections and knowledge cards, without changing stored world entities. Distinct actual location names remain intact. The narrator is instructed to describe the physical setting naturally instead of treating the service label or campaign title as a proper place name.

Universal narration now requests 1–2 connected literary paragraphs, normally 70–140 words. The saved consequence remains the factual anchor, but its wording should be interpreted and expanded through already established sensory details rather than copied from the roll card. The prompt excludes headings, repeated campaign exposition, dice summaries, invented mechanical changes, new enemies/items/clues and decisions on the player's behalf.

Admission and narration now share the latest visible story context for the current group. Public and appropriately tagged group narration are included; whispers, untagged private messages, other groups and other known locations are excluded. Old placeholder campaign names are neutralized only in model context, preserving original messages. This also fixes the previous omission of party-scoped narration from admission history.

Regression tests were observed RED then GREEN for duplicate headings, entry-name separation, visible group history, untagged private-message exclusion and future publication entry names. The two-paragraph provider fixture survives storage intact. Final verification: **172 backend tests passed** (all universal tests, WebSocket suites and selected existing roll/link regressions); **362 frontend tests passed**, with typecheck/build, Ruff and whitespace checks passing. Existing Vite bundle warnings remain. No live paid model call was made; deterministic tests verify context and rendering, while the prose style is supplied through the model instruction rather than a hardcoded word-count filler.

The same branch/container and existing game data are retained. Other user frontend edits are excluded from the commit. AST graph refreshed after code changes.
