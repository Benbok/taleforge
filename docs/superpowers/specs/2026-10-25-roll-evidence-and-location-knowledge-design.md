# Roll evidence and location knowledge

User request: show actual dice and totals separately from narration, and make mentioned places open accumulating hero-visible knowledge.

Use existing chat roll cards and entity inspector. Universal resolution records each die and each check in its immutable receipt; a deterministic, replay-safe chat projection exposes the actual draws, modifier, total, threshold and outcome. Numeric counts remain decimal strings. No model-generated dice or visual rerolls. Hidden opponent defenses stay private.

The existing entity registry, markup linker, inspector and visible-message history already support location knowledge. Connect them to Universal turns and intros, restrict markup to publicly available scene references, and ask narration to use the current location reference even when referring to it by a descriptive name. Preserve all distinct visible observations for Universal locations, refresh an open location card when narration changes, and mount the inspector on the Universal screen. Existing locations are reused; descriptive aliases do not create duplicate places or disclose private author data.

Approaches considered: inventing a separate dice/knowledge system would duplicate receipts and visibility rules; extracting facts with an extra model call would add cost and failure modes. Reusing authoritative receipts and existing visible narration avoids both. This is the implementation choice, under the user's instruction to continue and include these changes.

Verification: deterministic rolls including multiple targets, restart without duplicated cards, real totals and modifier display, scoped knowledge accumulation and private-message isolation, clickable locations and cache refresh. No paid model requests or world reset.
