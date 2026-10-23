# Hero portraits

Generate a square illustrated portrait from the saved universal hero description using Gemini 3.1 Flash Lite Image. Generation and regeneration are explicit actions. Keep the previous portrait until a new image succeeds. Portraits are cosmetic and do not alter sheets, levels or game resources.

1. Add immutable portrait records and nullable portrait/current-job references to library and campaign characters; migrate existing universal storage.
2. Add an injectable Gemini REST adapter with a bounded timeout, safe errors, image MIME/size checks and model usage accounting. Persist claims before calling the provider; prevent overlapping calls and repeated request-key charges. Expire interrupted claims after a bounded lease.
3. Authenticate generation and media reads. Library generation belongs to its owner; campaign generation belongs to the seated player or campaign owner. Campaign participants may read their characters' portraits. Keep immutable image references when copying a library hero.
4. Add explicit generation controls and portrait display to the workshop and campaign hero screen; display portraits in the game party, chat and hero card, with initials as fallback.
5. Verify with injected image responses only: access control, failures, replay/concurrency, independent copies, media retrieval, client controls and game display. Regenerate the API contract, build, migrate and restart the existing Docker app on the feature branch. Update graphify.

No live image generation is required for automated verification. Use the existing GEMINI_API_KEY only on the server; PORTRAIT_MODEL configures the model separately from chat. Save files in the existing persistent media volume.
