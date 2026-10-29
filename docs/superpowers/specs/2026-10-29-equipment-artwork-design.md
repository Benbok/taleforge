# Equipment artwork

The user approved item-specific prompts, a sword/armor/ring comparison, saved reusable images and small inventory thumbnails. Extend the existing local ComfyUI and technical English translation services. Keep portraits and locations unchanged.

Use explicit generation in the universal inventory; viewing a page never generates images. A hero's player and the campaign master may request art for that hero's available items. Reading art requires the same inventory access. Do not expose hidden items, another player's inventory or another campaign's files. Starting equipment may exist only as a projected view: resolve its validated profile without materializing gameplay inventory on a read.

Cache within a campaign by a versioned digest of public name, description and kind. Distinct descriptions never collide; ownership, quantity and mechanical bonuses do not alter visual identity. Immutable attempts, durable request receipts, leases and a unique pending claim avoid duplicate GPU work and recover abandoned requests. Ready images are reused; failed requests can be retried with a new key. No regenerate control in this first version. Never change item state, quantity, equipment, clock or combat.

Translate only public item details to concise English. Frame one complete isolated object, generous margins, plain background, no hands or wearer. Compare 768 and 1024 at 20 steps on three item types before selecting the default; record actual results. Rings are a visual benchmark, not a new mechanical item kind. Existing rules support weapons, armor and consumables only.

Save the validated original and a Pillow-generated WebP thumbnail bounded by 256×256, preserving aspect ratio. Use the thumbnail in the list and lazy-load the original into an in-app fullscreen dialog on click. Authentication applies to both. File paths are server-generated, immutable and private. Generation errors leave gameplay usable; polling resolves pending work after reload.

Alternatives: automatic generation would consume GPU on routine reads; per-instance generation would duplicate identical art. Reuse within a table is the chosen implementation boundary to avoid sharing private data between games. Profile selection and exact layout are implementation decisions.
