# Campaign world covers

Approved in chat: generate a cover by button in the settings of a saved campaign, with explicit regeneration. The main campaign on Home displays a wide illustration around half the viewport height; other cards display small previews. Existing covers remain visible while a replacement runs or fails.

## Approach

Reuse the existing Artwork lifecycle and configured hero image provider. A campaign-cover recipe uses only the campaign name, public introduction and public world metadata, never private campaign briefs, secrets or plot material. The latest ready artwork is the cover; old campaigns without one keep their existing presentation. Reusing hero portrait prompts would produce faces rather than world scenes; a separate generation pipeline would duplicate request claims, accounting and protected media storage.

## Constraints

Only the owner generates covers in Settings. Campaign members may view images. Gemini uses a wide scene prompt; ComfyUI uses the existing configured workflow/checkpoint with landscape dimensions and scene art direction. No automatic paid generation. Retries reuse the request key. No database migration is needed: covers use the existing artworks table.

## Builder decisions

Home's existing featured-campaign selection remains the definition of the main active campaign. Large covers use responsive height near 50vh; thumbnail requests return resized WebP. Unsaved settings must be saved before generation. The image and translation costs use existing campaign accounting.
