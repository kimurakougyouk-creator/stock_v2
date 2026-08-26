# Project State

Last updated: 2026-08-26

> **Runtime handoff note (2026-08-26):** `HANDOFF_MASTER.md` is the canonical cross-chat handoff entry point. The exact verified-scope Paper milestone is complete. PR #240 durably repaired the exact closed-SPY BUY FX from its unique closed SELL evidence with backup first; reconciliation is clean. A three-cycle read-only soak passed, restart/network-loss recovery tests passed, and PR #241's explicit bounded Paper runtime completed one real scan for AAPL 1 / SPY 1 / 9432.T 100 with three final HOLD decisions, zero data/runtime/execution errors, zero new fills, and no Live order. Normal `start.sh` remains non-ordering. Do not repeat old Paper proof or force an order.

This is the concise evidence ledger for AI agents. Do not replace verified facts with guesses and do not request duplicate Paper orders merely to re-prove existing broker evidence.

## Current phase

The IBKR Paper milestone is complete for the exact verified scope. The bounded deliberate runtime, explicit Paper opt-in, reconciliation/accounting/preflight gates, deterministic restart/network-loss recovery, and monitoring/reporting evidence all pass. Stock/ETF/global-stock controlled evidence is flat and reconciled; the exact ESU6 futures and pinned SPY long-option round trips pass multiplier-aware accounting/recovery using persisted broker execution evidence plus current broker-flat checks. Crypto BTC/USD ContractDetails are visible on PAXOS and ZEROHASH, but this account did not prove Paper crypto order validation. FX remains blocked by an IBKR account/currency-leverage restriction. Live Trading remains disabled/fail-closed.

## Latest consolidated evidence

Local runs on 2026-08-26:

- Verified-derivative cleanup targeted tests: `4 passed`; `4` exact derivative rows quarantined after backup; no broker order sent.
- Post-PR #238 reconciliation targeted tests: `8 passed`.
- Latest reconciliation: account/execution snapshot ready on port `4002`; AAPL broker/local `0/0`; SPY broker/local `0/0`; blocker count `0`; `RECONCILIATION_EVIDENCE_IS_CLEAN`; ledger unchanged; no Paper or Live order sent.
- Remote-equivalent isolated full suite after PR #238: `1348 passed`.
- Closed-SPY durable FX repair after PR #240: `16 passed`; exact BUY intent repaired at `158.875` from unique reference SELL exec_id `0000e511.6a8b602c.01.01`; backup created; reconciliation clean; no broker/Live order sent.
- Bounded read-only soak: `1348 passed in 25.23s`, followed by `PASS (3 consecutive read-only cycles)` with account/reconciliation/accounting/preflight/E2E gates clean and no Paper/Live order in every cycle.
- Targeted restart/network-loss/recovery and durable-intent tests: `31 passed`.
- PR #241 verified Paper runtime targeted tests: `37 passed`; remote-equivalent full suite: `1359 passed`.
- Final Chromebook deliberate runtime: `37 passed in 2.80s`; AAPL final `HOLD`, SPY final `HOLD`, 9432.T final `HOLD`; analysis records `3`; data failures `0`; confirmed new fills `0`; runtime errors `0`; execution errors `0`; Live order sent `False`.
- Zero new fills in the final scan is expected because all three final decisions were HOLD; it is not an execution failure.

- Aggregate read-only audit: `1330 passed`.
- Stock/ETF/global-stock final completion gate: `PASS`.
- Controlled broker positions: SPY `0`, AAPL `0`, 9432 `0`; trusted local quantities also `0`.
- Trusted stock accounting: realized PnL `141.39875`, unrealized PnL `0.0`, ending equity `1000141.39875`, max drawdown `0.0` for the bounded trusted history.
- ESU6 futures post-fill audit: `READY=True`, realized PnL `-25.00 USD`, unrealized `0`, ending contracts `0`, restart recovery verified, current broker flat verified.
- Pinned SPY option post-fill audit: `READY=True`, realized PnL `-1.00 USD`, unrealized `0`, ending contracts `0`, restart recovery verified, current broker flat verified.
- Crypto ContractDetails visibility: PAXOS resolved `True`, ZEROHASH resolved `True`, one BTC/USD candidate on each venue.
- Aggregate `FINAL READ-ONLY GATE: PASS`.
- `REAL ORDER SENT BY WRAPPER: False`; `LIVE ORDER SENT BY WRAPPER: False`.
- Follow-up crypto What-If audit: `1335 passed`; PAXOS and ZEROHASH both resolved with `minTick=0.25`, `minSize=1e-08`, `sizeIncrement=1e-08`, and WHATIF listed in broker order types.
- Crypto What-If acceptance: `False` on both routes; ZEROHASH returned invalid-account, PAXOS returned no acceptance preview.
- No real Paper crypto order and no Live order were sent.

## Verified real IBKR Paper capabilities

The capability registry must remain limited to exact evidence:

- `US_STOCK`: verified Paper, Live disabled.
- `US_ETF`: verified Paper, Live disabled.
- `US_ESU6_FUTURE_LONG_ROUNDTRIP`: exactly ESU6, BUY 1 then SELL 1 to flat; no general futures claim.
- `US_SPY_OPTION_LONG_INTRADAY`: pinned SPY option BUY 1 then SELL 1 to flat; no short/multi-leg/exercise/assignment/expiry claim.

Additional controlled evidence:

- 9432/TSEJ/JPY: controlled BUY 100 and flatten SELL 100 completed; broker/local quantity returned to `0`. This does not generalize to all global stocks.
- AAPL reset SELL 3 completed and broker returned to `0`; the reset remains excluded from ordinary trusted PnL because historical opening basis was not proven.

## Derivative accounting boundary

- Futures use product-specific multiplier-aware accounting and a read-only post-fill audit requiring exact broker execution identity, broker-flat state, realized/unrealized PnL, equity/drawdown and restart-style recovery.
- Options use a separate multiplier-aware accounting/recovery path.
- Historical `reqExecutions` windows are not assumed to retain old fills forever. Exact previously captured broker execution IDs and contract identity are persisted as immutable evidence; current broker-flat state is still required before the derivative audit can pass.
- Option exercise, assignment, expiration settlement, opening short options and multi-leg options remain explicitly unverified and fail closed.
- A successful single futures or option round trip must not be generalized to arbitrary contracts or lifecycle behavior.

## FX boundary

- `USD/JPY@IDEALPRO` ContractDetails resolution and IBKR Paper API connectivity are verified.
- Explicit FX What-If submission was rejected by IBKR with error 201: `FX trade would expose account to currency leverage.`
- Leveraged Spot FX Paper capability is therefore not promoted. Currency Conversion must not be treated as equivalent to leveraged Spot FX capability.
- The safe FX no-transmit/What-If implementation gate is complete; the account restriction remains an external capability blocker.

## Crypto boundary

- BTC/USD ContractDetails resolve on both PAXOS and ZEROHASH through the local Paper Gateway.
- Broker sizing metadata is captured for the observed routes.
- Direct Paper What-If did not prove order validation: ZEROHASH returned invalid-account; PAXOS returned no acceptance preview.
- Therefore CRYPTO remains unpromoted and fail-closed for this account.
- If IBKR account permissions/residence eligibility change later, crypto must be re-verified from the permission/order-validation gate before any controlled Paper E2E.

## Repository safety state

- Live Trading remains prohibited/fail-closed.
- Broker execution identity (`exec_id`) is persisted and used for reconciliation deduplication.
- Timeout/uncertain order state is never automatically resent.
- Legacy reset executions with unproven cost basis are quarantined from trusted accounting.
- The earlier IB API message-loop teardown `serverVersion() is None` TypeError is contained for guarded probes by `run_ibapi_message_loop_safely`.
- `ibkr_all_readonly_completion_once.sh` runs all no-order audits, reports every step, and returns the aggregate gate after all steps finish.
- Broad FUTURES/OPTIONS/FX/CRYPTO support claims remain prohibited beyond exact verified evidence.

## Audit issue status

- Parent multi-asset audit #56: completed and closed after exact capability boundaries were established.
- Crypto availability verification #184: completed and closed with a negative trading-eligibility result for the current account. Reopen only if broker/account permissions materially change.

## Completion rule

As of 2026-08-26, the Paper milestone completion rule is satisfied for the exact verified capability scope listed above. Unsupported, broader, or externally blocked products are intentionally not promoted. Live Trading remains disabled.

## Next engineering priority

Do not create more duplicate broker proof or force an actionable signal. The next single stage is monitored Paper operation over time: accumulate ordinary deliberate-run results and evaluate strategy quality, reporting, and operational alerts without broadening the capability registry. Any future FX/Crypto capability expansion requires new broker/account evidence first; Live remains out of scope and fail-closed.
