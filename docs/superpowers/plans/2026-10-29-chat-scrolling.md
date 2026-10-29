# Chat scrolling while the master thinks

User reported inability to scroll chat while the master responds. Root cause in ChatFeed: both layout and ResizeObserver forced bottom when masterStage was set, regardless of the reader's position. MasterThinkingCard independently called scrollIntoView on every stage change. The delayed frame/80ms callbacks also ignored intervening manual scrolling.

- [x] Reproduce with behavioral tests:3 failures returning scrollTop2000 instead of400, while bottom-follow baseline passed.
- [x] Track latest follow intent in a ref updated immediately by onScroll; guard deferred callbacks and resize handling with it.
- [x] Remove thinking-card self-scrolling. Keep stage updates under the feed's normal follow policy and retain the New messages action to resume following.
- [x] Verify4 focused regressions,428 frontend tests and TypeScript/Vite build.
- [x] Native browser wheel tests with real ChatFeed: desktop reading position14543→14543 across stage/message/size changes, mobile14193→14193, resumed bottom gap0, no JS errors.
- [x] Update graphify without force (13198 nodes/36470 edges); stop temporary Vite preview. Static bundle built into the mounted application directory; no backend restart needed. Keep source uncommitted in feature/universal-retirement and preserve other ongoing changes.
