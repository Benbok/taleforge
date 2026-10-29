# Admin equipment image replacement

The user supplied a generated armor texture and explicitly requested administrator regeneration and replacement. Add a ready-image action to the existing library/inventory component. Successful generation automatically selects the new immutable original and thumbnail. Retain the old image while pending and after failure. Preserve game state and item descriptions.

Use the existing local generator, explicit request keys and durable pending claims. Only platform admin/super_admin may request regeneration, and existing inventory/library access checks still apply. Server-side role enforcement is required. Distinguish create and regenerate in durable receipt binding, including conflict recovery.

Choose ready images by successful selection time, not cache receipt creation time. Cache aliases and independently adopted library copies inherit the original selection time; late old cache hits must not revert a replacement. Linked library/campaign views follow the new selection and mounted cards poll for updates.

Keep the existing UI and add one button below saved equipment art. A gallery/manual confirmation or image upload would add a separate interaction the user did not request. The user authorized automatic replacement by the regenerated image.

Correct the specific armor failure by placing complete cuirass/neck/arm silhouette before material descriptions in CLIP's limited context; exclude flat texture swatches in the equipment-only negative prompt. Leave portrait/location composition unchanged. Validate the actual admin action on the supplied armor and inspect the result.
