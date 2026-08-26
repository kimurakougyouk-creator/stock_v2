# Project State

Last updated: 2026-08-26

> **Runtime handoff note (2026-08-26):** `HANDOFF_MASTER.md` is the canonical cross-chat handoff entry point. Phase 7 signal-runner -> verified IBKR Paper wiring is merged (#234), but normal `start.sh` / `signal_runner.main()` still defaults to no order dispatch. The verified-derivative cleanup was executed locally, backed up the ledger, and quarantined four exact rows without sending an order. PR #238 then made the read-only reconciliation audit recognize the exact closed SPY stock pair from distinct broker execution IDs plus the SELL row's explicit FX, without mutating the ledger. Chromebook verification now reports AAPL/SPY broker/local `0/0`, blocker count `0`, and `RECONCILIATION_EVIDENCE_IS_CLEAN`. The next runtime gate is the bounded read-only soak; do not repeat old Paper proof.

This is the concise evidence ledger for AI agents. Do not replace verified facts with guesses and do not request duplicate Paper orders merely to re-prove existing broker evidence.

## Current phase

The consolidated IBKR Paper completion audit is complete for the exact verified scope. Stock/ETF/global-stock controlled evidence is flat and reconciled; the exact ESU6 futures and pinned SPY long-option round trips pass multiplier-aware accounting/recovery using persisted broker execution evidence plus current broker-flat checks. Crypto BTC/USD ContractDetails are visible on PAXOS and ZEROHASH, but this account did not prove Paper crypto order validation; ZEROHASH explicitly returned invalid-account and PAXOS produced no What-If acceptance preview. FX remains blocked by an IBKR account/currency-leverage restriction. Live Trading remains disabled/fail-closed.

## Latest consolidated evidence

Local runs on 2026-08-26:

- Verified-derivative cleanup targeted tests: `4 passed`; `4` exact derivative rows quarantined after backup; no broker order sent.
- Post-PR #238 reconciliation targeted tests: `8 passed`.
- Latest reconciliation: account/execution snapshot ready on port `4002`; AAPL broker/local `0/0`; SPY broker/local `0/0`; blocker count `0`; `RECONCILIATION_EVIDENCE_IS_CLEAN`; ledger unchanged; no Paper or Live order sent.
- Remote-equivalent isolated full suite after PR #238: `1348 passed`.

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

The Paper platform is complete only for the exact verified capability scope listed above. Unsupported, broader, or externally blocked products are intentionally not promoted. Live Trading remains disabled.

## Next engineering priority

Do not create more duplicate broker proof. Run the bounded read-only soak now that reconciliation is clean, then continue production hardening of the verified Paper scope: deterministic recovery after restart/network loss, reporting/monitoring, and a deliberate unattended Paper runtime/entry point. Only then judge the Paper milestone complete. Any future FX/Crypto capability expansion requires new broker/account evidence first; Live remains out of scope and fail-closed.
