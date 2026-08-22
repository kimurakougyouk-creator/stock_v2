# Project State

Last updated: 2026-08-22

This file is the concise, evidence-based handoff ledger for AI agents. Update it after meaningful verified progress. Do not replace verified facts with guesses.

## Current phase
Final IBKR Paper integrated runtime validation. Repository-side safety, multicurrency accounting, verified Paper preflight, market-neutral Paper execution, operator checkpoint, and account-timezone fixes are merged. The remaining verification boundary is the user's local Chromebook/TWS Paper runtime.

## Verified repository state
- Repository: `kimurakougyouk-creator/stock_v2`
- Branch: `main`
- PR #114 merged: account-currency realized trade history for same- and cross-currency confirmed fills.
- PR #115 merged after full CI success: fail-closed verified Paper preflight using explicit FX, confirmed holdings, position/allocation/cash/risk/daily-notional limits.
- PR #116 merged after fixing an initial CI failure and re-running to full success: signal analysis is separated from IBKR Paper execution so legacy JPY/100-share sizing cannot size or block US stock/ETF Paper pilots; execution consumes only verified instruments/quantities and explicit account-currency preflight.
- PR #117 merged after full CI success: one-command operator checkpoint combines Overnight what-if, read-only FX snapshot, multicurrency durable-ledger accounting, and verified Paper preflight without transmitting a real order.
- PR #118 merged after full CI success: explicit account calendar timezone (`Asia/Tokyo` for the current JPY account), timezone-aware confirmed-fill timestamps, and daily realized-loss evaluation by account calendar instead of host timezone.
- Current open pull requests: none. Obsolete, non-mergeable early PRs #16, #18, and #21 were closed to remove misleading stale work from the active queue.

## Verified real IBKR Paper evidence (2026-08-22)
- User's Chromebook/TWS Paper session resolved SPY as `STK / SMART / USD` with `CONNECTED=True`, `CONTRACT RESOLVED=True`, `ORDER SENT=False` before transmission.
- Controlled SPY Paper BUY: quantity 1, `SENT=True`, order id `3`, terminal status `Filled`, filled quantity `1.0`, average fill price `765.45`, timeout `False`.
- Local fill-state evidence persisted order id `3`, execution id `00012ec5.6ab91096.01.01`, quantity `1.0`, price `765.45`, and `processed_filled[3] = 1.0`.
- Do not send another order merely to re-prove this already verified direct broker fill.

## Current verified Paper execution model
- Live Trading remains disabled/unimplemented in the active path.
- `paper_trading_runner.py` first performs analysis with legacy order creation disabled, then routes actionable signals through the dedicated verified IBKR Paper executor.
- Broker-verified pilot quantities are explicit per instrument. Current verified examples include AAPL=1 share, SPY=1 share, and 9432.T=100 shares. Unverified symbols fail closed.
- New cross-currency BUY exposure requires read-only IBKR FX evidence before transmission. No FX rate is guessed.
- The verified preflight checks confirmed holdings, max positions, per-position allocation, portfolio allocation, minimum cash reserve, portfolio risk, and daily trading amount in account currency.
- Protective/position-reducing SELL preflight intentionally depends on confirmed quantity evidence rather than a fresh FX quote so exits are not trapped by unavailable market-data conversion.
- Per-order failures are collected; uncertain/timeout state is not automatically retried.

## Accounting and reporting
- Only accounting-effective records are included; IBKR Paper requires confirmed `FILLED` evidence.
- Confirmed fills are idempotent by `order_intent_id`.
- Cross-currency confirmed fills require explicit per-fill FX evidence for account-currency accounting. Missing FX fails closed rather than being guessed from a later rate.
- Account-currency realized trade history is persisted separately from the legacy same-currency JSON.
- Equity, realized/unrealized PnL, and maximum drawdown can be reconstructed from confirmed evidence in configured account currency.
- New confirmed IBKR fills use timezone-aware timestamps. The current JPY account uses the `Asia/Tokyo` account calendar for daily realized-loss boundaries.

## Operator checkpoint
- The one-command IBKR operator checkpoint is deliberately non-real-order.
- It combines Overnight server-side what-if, broker contract evidence, read-only FX snapshot, multicurrency accounting, historical missing-FX detection, existing-position detection, and verified Paper BUY preflight.
- It can identify historical confirmed IBKR fills whose currency/FX evidence is insufficient and fail closed with the affected ticker/intent rather than silently converting them.

## Verification boundary
- GitHub CI cannot access the user's local TWS/Gateway or local `results/paper_orders.jsonl`.
- Direct SPY contract resolution and one controlled real Paper fill are already verified from local runtime evidence.
- The latest integrated operator checkpoint and current `paper_trading_runner.py` path have not yet been observed against the user's current local TWS Paper session after PRs #114-#118.
- Therefore no claim that end-to-end live-connected Paper operation is fully complete is permitted until that local checkpoint is observed.
- No Live Trading completion claim is permitted.

## Single next action
On the user's Chromebook with TWS/Gateway Paper logged in, sync current `main` and run the non-real-order one-command operator checkpoint first. Inspect its complete output before any additional Paper transmission. Do not repeat the standalone SPY test order merely for proof.
