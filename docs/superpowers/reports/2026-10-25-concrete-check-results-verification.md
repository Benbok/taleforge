# Concrete check results

The playtest receipt `ev_d5ac7df8f4a2617f` correctly saved natural 15, total 17 and a successful Wisdom check against 11. Its admission supplied only the intent (the hero listens), and the outcome contained no observable consequence. The narrator therefore repeated the attempt; transport, dice and completion status were working.

New semantic check admissions must supply distinct observable success/failure descriptions before dice. A missing result consumes the existing bounded proposal repair, never a throw or energy. Runtime selects the branch from the actual saved success value and records only the selected description in the action outcome. Both conditional descriptions remain in the immutable proposal for recovery; the narrator and public roll card receive only the selected result. Existing prepared decisions, legacy admissions and receipts remain readable without retrospective dice or invented descriptions.

The roll card now shows **Результат действия** even if narration merely repeats the attempted action or the narrator fails. Selected results also contribute to hero-visible location observations. Reference IDs are restricted to public scene entities. The existing narrator is instructed to state the concrete saved result, rather than replace it with an attempt. No extra model call was added.

Verification: **159 backend tests passed**, including all universal tests, WebSocket tests and existing focused roll/link regressions. **360 frontend tests passed**; production typecheck/build and Ruff passed. Regression tests were observed RED, then GREEN for successful and failed perception checks, a missing-result repair, narrator restart without another throw, the result block, public reference filtering and knowledge accumulation. Existing Vite bundle warnings remain. The AST graph was refreshed.

The live receipt was inspected read-only; no paid test generation, reroll or edit of the previous narration was performed. The change applies to newly admitted checks. Other user frontend edits remain outside the commit.
