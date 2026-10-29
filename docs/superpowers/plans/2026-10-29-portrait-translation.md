# Technical translation for local portraits

User requested automatic Russian-to-English portrait prompts. The Google deep-translator trial returned429 from Windows and Docker; the user explicitly selected the configured technical model instead. Work only in feature/universal-retirement. Google-only trial modules/dependency removed; no new runtime dependencies.

Design: initialize TechnicalPortraitTranslator with the shared LLM and explicit provider technical model, only for ComfyUI. Translate saved appearance/identity/personality after the durable portrait claim and before image submission; never mutate the saved sheet. English bypasses the model. Cache128 successful English results, validate output, and stop before image submission on failed or incomplete translation. Persist a separate hero_portrait_translation LlmCall including real usage and cost; classify it under creation. Bound model and queue wait, keeping database commits outside provider cancellation deadlines.

- [x] Regression tests cover routing, successful cache, separate accounting, invalid/incomplete/blocked output, timeout, original-sheet preservation and creation-cost classification.
- [x] Wire translator into startup, API and lifecycle; preserve the existing ComfyUI adapter and immutable image storage.
- [x] Live technical translation from Docker succeeded: DeepSeek Flash5.3s; translated image1024x1024 completed32.4s total with the requested silver hair, green eyes and elven ears.
- [x] Final focused tests, build, runtime switch and graphify update.

Read-only review found no important issues; the minor spending phase omission was corrected with a RED-to-GREEN test. Google trial code, worker and tests were removed as superseded by the user's explicit choice. No commits or pushes.

Final checks:30 backend translation/ComfyUI/portrait/contract tests pass;2 frontend portrait tests pass; TypeScript+Vite build and Docker image build pass; scoped Ruff and git diff --check pass. Recreated only app with the completed implementation; HTTP200 confirmed. Graphify update completed. The configured translation model is deepseek/deepseek-flash; image inference stays on the local RealVisXL ComfyUI service.
