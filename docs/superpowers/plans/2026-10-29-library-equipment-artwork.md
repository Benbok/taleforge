# Library equipment artwork correction

The user supplied the actual library hero screenshot and requested generation/display there. The earlier equipment feature covered only the campaign inventory. Extend the agreed image flow to StartingEquipmentList in HeroWorkshop, with protected standalone library endpoints and shared media UI.

- [x] Add private library cache scope and resolve only the owner's validated starting equipment; preserve hero revision/sheet.
- [x] Reuse exact visual profiles between a library hero and its campaign copies; do not fetch another user's private cache.
- [x] Independently preserve adopted library bytes when the source campaign is deleted.
- [x] Atomically coordinate simultaneous library/game claims by pending_scope; preserve receipt binding and expired-lease recovery.
- [x] Preserve populated SQLite receipts with foreign_keys enabled during migration0012; explicit temporary self-reference avoids CASCADE deletion during table rebuild.
- [x] Wire generation and thumbnails inside each library equipment details panel, with the existing fullscreen viewer/retry controls.
- [x] Verify: focused backend tests and415 frontend tests, TypeScript/build and API contract pass. Independent review findings addressed with populated migration, campaign deletion, simultaneous requests and expired claims from older/other-owner scopes.
- [x] Apply migrations through universal_0013 and restart local app. Real screenshot hero: weapon ready (555591-byte original/2624-byte thumbnail), armor idle with can_generate=true. Browser verified actual library page on desktop/mobile, full-screen viewer, zero generation requests on read. Temporary browser auth file removed by helper.
- [x] Run final graphify update; preserve unrelated working tree changes and leave source uncommitted. Graph updated without force; HTML omitted by graph size limit.
