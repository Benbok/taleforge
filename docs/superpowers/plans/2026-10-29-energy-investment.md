# Energy Investment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After a failed ordinary check the table pauses, and the acting player may invest the check's attribute energy to turn a near miss into a success; the exact price is shown and the button exists only when the hero can pay it.

**Architecture:** The d20 for a `check` action is rolled in the turn loop *before* `resolve_exploration` commits anything and stored in `MasterTurn.trace`. If the roll failed by a small shortfall the hero can afford, the turn publishes an `investment` message and awaits the player's decision (or a timeout). `resolve_exploration` then replays the stored roll through `FixedDice` with an `invest` bonus, so every success-only consequence (objects, moves, timed effects) runs exactly once, on the final result. The server derives the price from the stored roll; the client only says accept or decline.

**Tech Stack:** Python 3.12, SQLAlchemy async, FastAPI, pytest; React + TypeScript + Vitest in `web/`.

**Spec:** decisions made in conversation 2026-10-29, recorded in "Design decisions" below (no separate spec file).

## Design decisions

- Price = `shortfall × level × INVEST_COST_FACTOR`, where `shortfall = difficulty − total` (total = natural + modifier). `INVEST_COST_FACTOR = 3` (same base as ability cost `3 × level`), `INVEST_MAX_SHORTFALL = 5`, `INVEST_TIMEOUT_SECONDS = 45`. All three are module constants to tune after play.
- Offered only when: `resolution == "check"`, no combat operations, attribute has an energy pool (not `con`), natural roll is not 1, `1 ≤ shortfall ≤ INVEST_MAX_SHORTFALL`, and `energies[attr] − action.cost ≥ price`. Otherwise no pause and no button.
- One point of shortfall is bought by one `level × factor` price; investing yields an ordinary success (never critical).
- Works for all five pooled attributes (`str dex int wis cha`) through `action.attribute`; nothing is specific to charisma.
- The pause blocks the whole table (master turns are already sequential); only the controlling seat (seat user or stand-in) may answer; timeout equals decline. A restart re-offers with a fresh deadline.
- Out of scope: attack/resistance rolls, abilities in combat, partial investment, choosing an amount.

## Global Constraints

- Public text is Russian; ids/keys stay English.
- Energy is only ever deducted inside `_execute` (`exploration_resolution.py`), under the campaign lock, with the receipt `Event`; never in the API handler.
- Client input is never trusted for price or points.
- After code changes run `graphify update .` (AGENTS.md).

## Review Focus

- Natural 1 with a 1-point shortfall: no offer (critical failure stands).
- Hero has the price but `action.cost` already consumed part of the pool: offer must use the remainder.
- Player double-clicks or two tabs send accept: energy spent once, same outcome.
- Server restarts while the offer is open: turn resumes, re-offers, never loses or double-spends.
- Non-controlling seat posts accept: rejected, offer stays open.
- Decision arrives after the timeout: ignored, result stands as rolled.

---

### Task 1: Pure investment rules

**Files:**
- Create: `app/rules/universal/investment.py`
- Modify: `app/rules/universal/profiles.py` (`resolve_check`, `CheckProof`)
- Test: `tests/test_universal_investment_rules.py`

**Interfaces:**
- Produces: `INVEST_COST_FACTOR = 3`, `INVEST_MAX_SHORTFALL = 5`, `INVEST_TIMEOUT_SECONDS = 45`; `shortfall(natural: int, total: int, difficulty: int) -> int` (0 when no investment can help: success, natural 1, or natural 20); `invest_price(shortfall_points: int, level: int) -> int`; `resolve_check(..., edge="normal", bonus: int = 0)` adds `bonus` to `total` before comparing; `CheckProof.invested: int = 0`.

- [ ] **Step 1: Write failing tests** in `tests/test_universal_investment_rules.py`:
  - `shortfall(10, 9, 12) == 3`; `shortfall(1, 11, 12) == 0` (natural 1); `shortfall(20, 15, 40) == 0`; `shortfall(15, 15, 12) == 0` (already success).
  - `invest_price(3, 1) == 9`, `invest_price(3, 10) == 90`.
  - `resolve_check(FixedDice([10]), 8, False, 12, bonus=3)` → `success` True, `total == 12` (score 8 gives modifier −1, so 10 − 1 + 3), `critical is False`. Also `FixedDice([1])` with a huge bonus stays a critical failure.
- [ ] **Step 2: Run** `pytest tests/test_universal_investment_rules.py -v` → FAIL (module missing).
- [ ] **Step 3: Implement** the module and the `bonus` keyword (default 0, validated as non-negative int via `_integer`); add `invested: int = Field(default=0, ge=0)` to `CheckProof`. Success rule becomes `natural == 20 or (natural != 1 and total + bonus >= difficulty)`; returned `total` includes the bonus.
- [ ] **Step 4: Run** the new tests plus `pytest tests/test_universal_critical_checks.py -v` → PASS.
- [ ] **Step 5: Commit** `feat(rules): energy investment price and check bonus`.

### Task 2: Execute a check from a stored roll with investment

**Files:**
- Modify: `app/core/universal/contracts.py` (`ResolutionContext`)
- Modify: `app/core/universal/exploration_resolution.py:187-210`
- Modify: `app/core/universal/rolls.py` (proof `invested`)
- Test: `tests/test_universal_investment_execution.py` (reuse fixtures from `tests/test_universal_critical_checks.py` / `tests/test_universal_resolution.py`)

**Interfaces:**
- Consumes: Task 1 functions.
- Produces: `ResolutionContext.preroll: tuple[int, ...] | None = None` and `ResolutionContext.invest: bool = False`. In `_execute`: when `resolution == "check"` and `ctx.preroll` is set, the check uses `FixedDice(list(ctx.preroll))` instead of `ctx.dice`; when `ctx.invest` is true the server recomputes `shortfall` from that roll, rejects with `ValueError` (→ `denied`) if `shortfall == 0` or energy `< action.cost + price`, deducts `price` from `energies[action.attribute]` together with `action.cost`, and passes `bonus=shortfall`. `CheckProof.invested = shortfall` and `result.cost = action.cost + price`.

- [ ] **Step 1: Write failing tests:** (a) preroll `[10]`, score 8, DC 12, no invest → failure, identical to rolling with `FixedDice([9])`; (b) same with `invest=True`, level 1 → success, `checks[0].invested == 3`, energy reduced by exactly 9, success-only operation (use an existing `observe`/`create_object` fixture) applied once; (c) `invest=True` with energy 8 → outcome `denied`, energy unchanged; (d) `invest=True` on natural 1 → `denied`; (e) replay of the same `request_key` returns the stored outcome and spends nothing further.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the context fields and the `_execute` branch as described; keep the existing path unchanged when `preroll is None`. `ensure_roll_message` copies `invested` into each check dict automatically via `model_dump`; confirm.
- [ ] **Step 4: Run** the new tests and `pytest tests/test_universal_action_pipeline.py tests/test_universal_critical_checks.py -v` → PASS.
- [ ] **Step 5: Commit** `feat(universal): execute checks from a stored roll with energy investment`.

### Task 3: Offer, decision registry, timeout

**Files:**
- Create: `app/core/universal/investment.py`
- Modify: `app/agents/master/service.py` (registry attribute)
- Test: `tests/test_universal_investment_offer.py`

**Interfaces:**
- Produces:
  - `async def make_offer(session, campaign, game_id, turn_id, action, sheet, resources, rolls: list[int], audience) -> Offer | None` — evaluates the conditions in "Design decisions" using `resolve_check(FixedDice(rolls), …)`; returns `None` when no offer; otherwise creates a `Message(kind="investment", visible_to=audience, content="Вложить усилие?", data=dict(mid, actor_id, attribute, natural, modifier, total, difficulty, shortfall, price, available, deadline_ts, status="offered"))` and returns `Offer(message_id, mid, shortfall, price, controller_seat_ids)`.
  - `async def settle_offer(session, message_id, status: Literal["invested","declined","expired"]) -> Message` — rewrites `data.status`, returns the message for republishing under the same id/seq.
  - On `service`: `service.investments: dict[tuple[str, str], asyncio.Future[bool]]`; `async def await_decision(service, cid, mid, timeout=INVEST_TIMEOUT_SECONDS) -> bool` (True = invest; timeout/cancel → False and the registry entry is removed); `def submit_decision(service, cid, mid, accept: bool) -> bool` (False when no open offer or already decided, first decision wins).
- [ ] **Step 1: Write failing tests:** offer `None` for each non-offer condition (success, natural 1, shortfall 6, `con`, remainder energy short by 1 after `action.cost`, `resolution != "check"`, combat operation); offer present with `price == 9` for the Pupkin case (cha 8, level 1, DC 12, rolls `[10]`); `await_decision` returns True after `submit_decision(True)`, False after timeout (use `timeout=0.05`); second `submit_decision` returns False.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** as specified. `controller_seat_ids` = the hero's seat id plus its `stand_in` seat if present (mirror the check at `universal.py:281-283`).
- [ ] **Step 4: Run** tests → PASS.
- [ ] **Step 5: Commit** `feat(universal): investment offer and decision registry`.

### Task 4: Turn-loop integration

**Files:**
- Modify: `app/agents/master/universal.py` (between `outcome = prepared_outcome(compiled)` and `run_exchange`, ~line 408-418)
- Modify: `app/agents/master/action_results.py` (`public_outcome`)
- Test: `tests/test_universal_investment_turn.py`

**Interfaces:**
- Consumes: Task 2 context fields; Task 3 `make_offer`, `await_decision`, `settle_offer`.
- Behaviour: for a v2 `compiled.proposal` with `resolution == "check"` and no existing receipt (`already_applied` false): obtain `trace["rolls"][mid]` (roll once with `resolve_check(service.dice_factory(), …).rolls`, persist trace immediately; reuse on recovery). Call `make_offer`; if an offer exists, persist `trace["investment"][mid] = {"status": "offered"}`, `commit`, `publish_message`, `await await_decision`, then `settle_offer`, republish the same message, and store `trace["investment"][mid]["status"]`. Build the `ResolutionContext` with `preroll=tuple(trace["rolls"][mid])` and `invest=<decision>`. On recovery a stored `"invested"`/`"declined"` status is reused without re-offering; `"offered"` re-offers. `public_outcome` gains `invested: bool` (true when any check has `invested > 0`) so the narrator may mention the extra effort.
- [ ] **Step 1: Write failing tests** with a fake service using `FixedDice([10])` and an immediate `submit_decision`: accept → roll card has `invested == 3`, energy −9, success text told; decline → failure card, energy unchanged; timeout → failure; no offer when energy short (no `investment` message exists, turn never waits); restart simulation (trace contains `rolls` and `"offered"`) re-offers once and the final energy deduction occurs once.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** the loop change; keep the existing code path byte-for-byte when no pre-roll applies (e.g. `resolution != "check"`).
- [ ] **Step 4: Run** new tests plus `pytest tests/test_universal_action_pipeline.py tests/test_universal_catchup.py tests/test_universal_combat_playthrough.py -v` → PASS.
- [ ] **Step 5: Commit** `feat(master): pause the turn for an energy investment decision`.

### Task 5: Decision endpoint

**Files:**
- Modify: `app/api/characters.py` (or the campaign actions router that owns player commands)
- Modify: `app/api/schemas.py`, `web/openapi.json`, `web/src/lib/api.gen.ts` (regenerate with the repo's existing generator command in `web/package.json`)
- Test: `tests/test_universal_investment_api.py`

**Interfaces:**
- Produces: `POST /api/campaigns/{campaign_id}/investments/{mid}` body `InvestmentDecision {accept: bool}` → `{ "status": "accepted" | "declined" | "closed" }`. Uses `get_viewer(...)`; rejects with `AccessDenied` unless `viewer.seat.id` is in the offer's `controller_seat_ids` (read from the `investment` message `data`); calls `submit_decision(request.app.state.master, cid, mid, accept)`; `"closed"` when no open offer.
- [ ] **Step 1: Write failing tests:** controlling seat accept → `accepted`; other seat → 403 and the offer remains open; second call → `closed`; unknown `mid` → `closed`.
- [ ] **Step 2: Run** → FAIL.
- [ ] **Step 3: Implement** route and schema, regenerate OpenAPI types.
- [ ] **Step 4: Run** tests → PASS.
- [ ] **Step 5: Commit** `feat(api): investment decision endpoint`.

### Task 6: Chat UI

**Files:**
- Create: `web/src/game/InvestmentOffer.tsx`, `web/src/game/InvestmentOffer.test.tsx`
- Modify: `web/src/game/MessageView.tsx` (render `kind === "investment"`), `web/src/game/UniversalRollProof.tsx:50`, `web/src/lib/types.ts`

**Interfaces:**
- Consumes: message `data` from Task 3; endpoint from Task 5.
- Produces: `InvestmentOffer({ message, canAnswer }: …)` showing «Недобор N — вложить P Харизмы (есть A)»; two buttons «Вложить» / «Принять провал» only when `status === "offered"` and `canAnswer`; other viewers see «<Имя> решает, вложить ли P Харизмы» plus a countdown from `deadline_ts`; after settlement shows the final status text. `UniversalRollProof` line becomes «Энергия: −{cost}» as before and adds «Вложено: +{invested}» when `invested > 0`. Attribute names use the existing ability name map.
- [ ] **Step 1: Write failing Vitest tests:** buttons present for the controlling seat with `status:"offered"`, absent for other seats and after `invested/declined/expired`; clicking «Вложить» posts `{accept:true}`; price and shortfall text rendered; proof card shows «Вложено: +3».
- [ ] **Step 2: Run** `npm --prefix web test -- InvestmentOffer UniversalRollProof` → FAIL.
- [ ] **Step 3: Implement.** A republished message with the same id replaces the old one through `mergeMessages` in `web/src/stores/game.ts:216-229`; confirm with a store test rather than changing the store.
- [ ] **Step 4: Run** the web test suite and `npm --prefix web run typecheck` → PASS.
- [ ] **Step 5: Commit** `feat(ui): energy investment offer card`.

### Task 7: Verification and graph

- [ ] **Step 1:** Run `pytest tests -k universal -q` and `npm --prefix web test` → all PASS.
- [ ] **Step 2:** Play the Pupkin scenario manually (cha 8, DC 12 conversation, force a low roll) and confirm: card with price 9, buttons for the owner only, final card shows «Вложено: +3», energy 18 → 9.
- [ ] **Step 3:** Run `graphify update .` and commit `docs: update graph`.
- [ ] **Step 4:** Revisit `INVEST_COST_FACTOR` and `INVEST_MAX_SHORTFALL` after the manual run; adjust the constants only.
