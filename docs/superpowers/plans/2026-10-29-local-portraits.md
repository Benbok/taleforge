# Local ComfyUI portrait integration

Approved in chat: add ComfyUI beside Gemini using the installed RealVisXL text-to-image workflow, then try a real local generation. Work only in feature/universal-retirement. Do not edit the external ComfyUI installation or original workflows.

Design: PORTRAIT_PROVIDER selects gemini (unchanged default) or comfyui. A project-owned API-format workflow preserves the source checkpoint, resolution and sampling parameters, with game-art prompts. The adapter submits once, polls only that job, and downloads the resulting bounded PNG/JPEG/WebP into the existing immutable portrait store. No cloud fallback. A local request has a configurable total deadline, including queue wait; the portrait claim remains valid longer than that deadline. Timeout deletes only its queued job and never interrupts other running work.

- [x] Add adapter/config regressions, observe failures.
- [x] Implement API workflow, adapter, factory and deadline-aware portrait claims; document configuration.
- [x] Start the existing local ComfyUI hidden, with outputs directed into this worktree's media; generate one test portrait and measure it.
- [x] Verify existing portrait behavior, local error paths, project checks and graphify update; review the integration.

Local GPU: RTX 4050 Laptop, 6 GB VRAM. Installed workflow: Text_To_Image_RealVisXL.json, checkpoint RealVisXL_V5.0_fp16.safetensors, 1024 square, 30 steps, CFG 5, dpmpp_2m/karras. Actual quality and latency must be measured. Use an English character description for the first smoke test; Russian prompt quality is a separate check.

Results: real English portrait43s, Russian portrait via Docker24.3s; Russian lost key appearance traits. The user subsequently requested translation: completed in docs/superpowers/plans/2026-10-29-portrait-translation.md using the configured technical model, with separate cost accounting. Existing ignored retirement compose override enables ComfyUI through host.docker.internal; only app recreated, HTTP200 confirmed. Image inference has no cloud fallback. Original external workflows untouched.

Verification:22 backend portrait/contract tests pass,2 frontend portrait tests pass, full TypeScript+Vite build passes, scoped Ruff and git diff --check pass. Fresh review found missing queued-job cleanup on HTTP timeout/cancellation; fixed with finally and RED→GREEN regressions for both cases. Graphify updated.
