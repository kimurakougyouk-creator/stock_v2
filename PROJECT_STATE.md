# Project State

Last updated: 2026-08-25

This is the concise evidence ledger for AI agents. Do not replace verified facts with guesses and do not request duplicate Paper orders merely to re-prove existing broker evidence.

## Current phase

Final IBKR Paper completion audit and remaining product-boundary verification. Stock/ETF/global-stock controlled Paper evidence is flat and reconciled. Futures ESU6 and the pinned SPY option now also have direct Paper execution evidence. FX remains blocked by an IBKR account/currency-leverage restriction. Crypto account/region/Paper trading availability is not yet proven. Live Trading remains disabled/fail-closed.

## Verified real IBKR Paper evidence

- SPY stock/ETF: controlled BUY 1 and later position-reducing SELL 1 completed; broker and trusted local quantity returned to `0`.
- AAPL: dedicated Paper flatten reset SELL 3 completed and broker returned to `0`. The reset remains excluded from ordinary trusted PnL because the historical opening basis was not proven.
- 9432/TSEJ/JPY: controlled BUY 100 and flatten SELL 100 completed; broker/local quantity returned to `0`; confirmed SELL reconciliation completed.
- Bounded stock/ETF read-only soak previously passed `3/3` consecutive cycles with no order transmission and stable trusted accounting.
- ESU6/CME/USD futures: exact Paper round trip completed, BUY 1 @ `7668.25`, SELL 1 @ `7667.75`, ending quantity `0`, broker flat, Live order not sent. Exact contract evidence: expiry `20260918`, multiplier `50`, conId `649180671`.
- Pinned SPY option `SPY   260828C00765000`: expiry `20260828`, strike `765 C`, multiplier `100`, conId `900369377`. Broker history recovers BUY 1 @ `4.08` and SELL 1 @ `4.07`; broker position is flat; recovered gross realized PnL is `-1.00 USD`; exact What-If preview is ready.
- No verified flow above sent a Live order.

## Derivative accounting boundary

- Futures use product-specific multiplier-aware accounting and a read-only post-fill audit that requires exact broker execution identity, broker-flat state, realized/unrealized PnL, equity/drawdown and restart-style recovery.
- Options use a separate multiplier-aware accounting/recovery path. The pinned long-option BUY-to-open/SELL-to-close round trip is evidenced.
- Option exercise, assignment, expiration settlement, opening short options and multi-leg options remain explicitly unverified and must fail closed.
- A successful single futures or option round trip must not be generalized to arbitrary contracts or lifecycle behavior.

## FX boundary

- `USD/JPY@IDEALPRO` ContractDetails resolution and IBKR Paper API connectivity are verified.
- Explicit FX What-If submission was rejected by IBKR with error 201: `FX trade would expose account to currency leverage.`
- Therefore leveraged Spot FX Paper capability is not promoted and the broker restriction must not be bypassed by treating Currency Conversion as the same capability.
- Issue #182, whose scope was the safe no-transmit/What-If gate, is complete; the external account restriction remains a product capability blocker.

## Crypto boundary

- Repository contract foundations explicitly support only broker-derived `CRYPTO` tuples with allowed exchanges `PAXOS` or `ZEROHASH` and currency `USD`.
- `ibkr_crypto_readonly_audit.py` now provides a no-order diagnostic that checks BTC/USD ContractDetails visibility on both allowed venues.
- ContractDetails visibility alone does **not** prove account permission, residence eligibility, or Paper crypto trading capability. Those fields remain unverified until direct evidence exists.
- No crypto Order or What-If order is created by that read-only audit, and no crypto capability is promoted from it.

## Repository safety state

- Live Trading remains prohibited/fail-closed.
- Broker execution identity (`exec_id`) is persisted and used for reconciliation deduplication.
- Timeout/uncertain order state is never automatically resent.
- Legacy reset executions with unproven cost basis are quarantined from trusted accounting.
- The earlier IB API message-loop teardown `serverVersion() is None` TypeError is contained for guarded probes by `run_ibapi_message_loop_safely`; it is no longer an open defect for those guarded paths.
- A one-command read-only completion wrapper now exists: `ibkr_all_readonly_completion_once.sh`. It runs the full pytest suite, stock/ETF/global-stock final completion audit, futures post-fill audit, option post-fill audit, and crypto read-only visibility audit without supplying any Paper-order confirmation or Live enable flag.

## Current blocker after local computer reboot

The remaining broker-dependent audits require the user's local IBKR Paper TWS/Gateway process to be running and reachable. GitHub/CI cannot substitute for that local broker connection or local durable ledger. Repository-only work should be completed before asking the user for that unavoidable local action.

## Completion rule

The platform may be called complete only for the exact verified scope. A final completion decision must cover tests, controlled broker/local flatness, trade history, realized/unrealized PnL, equity, drawdown, restart/idempotency recovery and the exact list of verified Paper capabilities. FX and crypto must remain marked blocked/unverified unless new direct evidence changes that conclusion. Live Trading must remain disabled.

## Next gate

When the local IBKR Paper process is restored, run exactly one read-only command: `bash ./ibkr_all_readonly_completion_once.sh`. Use its output to close remaining evidence gaps; do not send another already-proven stock, futures or option Paper order merely for duplicate proof.
