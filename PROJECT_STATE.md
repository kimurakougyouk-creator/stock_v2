# Project State

Last updated: 2026-08-26

This is the concise evidence ledger for AI agents. Do not replace verified facts with guesses and do not request duplicate Paper orders merely to re-prove existing broker evidence.

## Current phase

The consolidated IBKR Paper read-only completion audit passes for the exact verified scope. Stock/ETF/global-stock controlled evidence is flat and reconciled; the exact ESU6 futures and pinned SPY long-option round trips pass multiplier-aware accounting/recovery using persisted broker execution evidence plus current broker-flat checks. Crypto BTC/USD ContractDetails are visible on both PAXOS and ZEROHASH, but account trading permission and actual Paper order acceptance are still unproven. FX remains blocked by an IBKR account/currency-leverage restriction. Live Trading remains disabled/fail-closed.

## Latest consolidated audit

Local run on 2026-08-26:

- `1330 passed`.
- Stock/ETF/global-stock final completion gate: `PASS`.
- Controlled broker positions: SPY `0`, AAPL `0`, 9432 `0`; trusted local quantities also `0`.
- Trusted stock accounting: realized PnL `141.39875`, unrealized PnL `0.0`, ending equity `1000141.39875`, max drawdown `0.0` for the bounded trusted history.
- ESU6 futures post-fill audit: `READY=True`, realized PnL `-25.00 USD`, unrealized `0`, ending contracts `0`, restart recovery verified, current broker flat verified.
- Pinned SPY option post-fill audit: `READY=True`, realized PnL `-1.00 USD`, unrealized `0`, ending contracts `0`, restart recovery verified, current broker flat verified.
- Crypto read-only visibility: PAXOS resolved `True`, ZEROHASH resolved `True`, one BTC/USD candidate on each venue.
- Aggregate `FINAL READ-ONLY GATE: PASS`.
- `REAL ORDER SENT BY WRAPPER: False`; `LIVE ORDER SENT BY WRAPPER: False`.

## Verified real IBKR Paper evidence

- SPY stock/ETF: controlled BUY 1 and later position-reducing SELL 1 completed; broker and trusted local quantity returned to `0`.
- AAPL: dedicated Paper flatten reset SELL 3 completed and broker returned to `0`. The reset remains excluded from ordinary trusted PnL because the historical opening basis was not proven.
- 9432/TSEJ/JPY: controlled BUY 100 and flatten SELL 100 completed; broker/local quantity returned to `0`; confirmed SELL reconciliation completed.
- Bounded stock/ETF read-only soak previously passed `3/3` consecutive cycles with no order transmission and stable trusted accounting.
- ESU6/CME/USD futures: exact Paper round trip completed, BUY 1 @ `7668.25`, SELL 1 @ `7667.75`, ending quantity `0`, broker flat, Live order not sent. Exact contract evidence: expiry `20260918`, multiplier `50`, conId `649180671`.
- Pinned SPY option `SPY   260828C00765000`: expiry `20260828`, strike `765 C`, multiplier `100`, conId `900369377`. Broker history captured BUY 1 @ `4.08` and SELL 1 @ `4.07`; broker position is flat; recovered gross realized PnL is `-1.00 USD`; exact What-If preview is ready.
- No verified flow above sent a Live order.

## Derivative accounting boundary

- Futures use product-specific multiplier-aware accounting and a read-only post-fill audit that requires exact broker execution identity, broker-flat state, realized/unrealized PnL, equity/drawdown and restart-style recovery.
- Options use a separate multiplier-aware accounting/recovery path. The pinned long-option BUY-to-open/SELL-to-close round trip is evidenced.
- Historical `reqExecutions` windows are not assumed to retain old fills forever. Exact previously captured broker execution IDs and contract identity are persisted as immutable evidence; current broker-flat state is still required before the final derivative audit can pass.
- Option exercise, assignment, expiration settlement, opening short options and multi-leg options remain explicitly unverified and must fail closed.
- A successful single futures or option round trip must not be generalized to arbitrary contracts or lifecycle behavior.

## FX boundary

- `USD/JPY@IDEALPRO` ContractDetails resolution and IBKR Paper API connectivity are verified.
- Explicit FX What-If submission was rejected by IBKR with error 201: `FX trade would expose account to currency leverage.`
- Therefore leveraged Spot FX Paper capability is not promoted and the broker restriction must not be bypassed by treating Currency Conversion as the same capability.
- Issue #182, whose scope was the safe no-transmit/What-If gate, is complete; the external account restriction remains a product capability blocker.

## Crypto boundary

- Repository contract foundations use broker-derived `CRYPTO` tuples for `PAXOS` or `ZEROHASH`, currency `USD`.
- BTC/USD ContractDetails now resolve on both PAXOS and ZEROHASH through the local Paper Gateway.
- ContractDetails visibility alone does **not** prove account permission, residence eligibility, or Paper crypto order acceptance.
- IBKR documentation states that cryptocurrency trading permission must be requested in Client Portal and that routing eligibility can depend on account type and legal residence; not all accounts are permitted for both routing destinations.
- The next safe broker-side gate is a `whatIf=True` crypto order-validation probe only. It must not be treated as real Paper E2E even if accepted.
- No crypto capability is promoted until actual Paper E2E, product-specific accounting/recovery and all safety gates are evidenced.

## Repository safety state

- Live Trading remains prohibited/fail-closed.
- Broker execution identity (`exec_id`) is persisted and used for reconciliation deduplication.
- Timeout/uncertain order state is never automatically resent.
- Legacy reset executions with unproven cost basis are quarantined from trusted accounting.
- The earlier IB API message-loop teardown `serverVersion() is None` TypeError is contained for guarded probes by `run_ibapi_message_loop_safely`; it is no longer an open defect for those guarded paths.
- `ibkr_all_readonly_completion_once.sh` runs all no-order audits even if one step fails, reports every result, and returns the aggregate gate only after all steps finish.
- The multi-asset evidence matrix is aligned to the exact verified scoped capabilities: US ETF, ESU6 one-contract long round trip, and pinned SPY long-option intraday round trip. Broad FUTURES/OPTIONS claims are still prohibited.

## Completion rule

The platform may be called complete only for the exact verified scope. The bounded stock/ETF, 9432 controlled global-stock, ESU6 controlled futures and pinned SPY long-option evidence now meet the final read-only accounting/recovery gate. FX and crypto remain blocked/unverified at the broader product-capability level unless new direct evidence changes that conclusion. Live Trading must remain disabled.

## Next gate

Run the dedicated crypto `whatIf=True` permission/order-validation audit only after its tests and CI pass. A What-If acceptance may justify the next controlled Paper crypto E2E planning step, but it does not itself prove Paper execution capability. Do not send another already-proven stock, futures or option Paper order merely for duplicate proof.
