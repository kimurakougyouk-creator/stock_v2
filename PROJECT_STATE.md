# Project State

Last updated: 2026-08-22

This file is the concise, evidence-based handoff ledger for AI agents. Update it after meaningful verified progress. Do not replace verified facts with guesses.

## Current phase
Final IBKR Paper integration validation. Do not repeat verified contract/fill/equity recovery work. The next required evidence is the integrated `paper_trading_runner.py` path on the user's local TWS Paper session.

## Verified repository state
- Repository: `kimurakougyouk-creator/stock_v2`
- Branch: `main`
- PR #57 squash-merged as `e242ecd66e6df3b082d96a4684dc6a4095f72309`: broker-neutral instrument foundation, fail-closed ETF/STOCK IBKR contract mapping, confirmed-fill reconciliation into reporting, duplicate-intent coverage.
- PR #58 squash-merged as `b5c6dcbf2a87b5cbbd4b1668455559a40cd15704`: shared pre-send risk gate attached to the IBKR approved-signal runtime.
- PR #58 merge candidate passed secret scan and the complete suite: 773 passed / 0 failed.

## Verified real IBKR Paper evidence (2026-08-22)
- User's Chromebook/TWS Paper session resolved SPY as `STK / SMART / USD` with `CONNECTED=True`, `CONTRACT RESOLVED=True`, `ORDER SENT=False` before transmission.
- Controlled SPY Paper BUY: quantity 1, `SENT=True`, order id `3`, terminal status `Filled`, filled quantity `1.0`, average fill price `765.45`, timeout `False`.
- Local fill-state evidence persisted order id `3`, execution id `00012ec5.6ab91096.01.01`, quantity `1.0`, price `765.45`, and `processed_filled[3] = 1.0`.
- Do not send another order merely to re-prove this already verified direct broker fill.

## Equity/Reporting status
- Total-asset Equity History with CSV persistence.
- Equity Curve based on `total_assets`.
- Total-asset maximum drawdown calculation and persistence.
- Browser-native HTML/SVG Equity chart generation.
- Confirmed IBKR Paper Fill -> durable legacy ledger -> realized-PnL regeneration -> Equity reporting sync in `paper_trading_runner.py`.
- `order_intent_id` idempotency prevents duplicate confirmed-fill/Equity accounting.
- Mock/file E2E coverage exists for Fill -> trade/PnL -> Equity -> Drawdown and restart-safe duplicate prevention.

## Shared safety gate now merged
- Emergency stop and Paper-enabled checks.
- Maximum shares per order.
- Daily BUY/SELL count limits.
- Daily realized-loss and consecutive-loss limits block new BUY exposure only so protective SELL exits remain possible.
- Repurchase cooldown.
- Legacy durable paper ledger is the state source during migration.
- State-read failure fails closed.
- Price-dependent cash/allocation/portfolio-risk/daily-notional controls remain in the existing `signal_runner.py` priced path; they were not guessed into an unpriced `OrderRequest` gate.
- Live Trading remains forbidden/unimplemented.

## Audit findings retained
- `paper_trading_runner.py` is the integrated Paper entry point. It requires both Paper opt-ins, rejects Live-enabled state, replaces the legacy paper recorder only for the run, sends through the approved IBKR Paper runtime, persists only confirmed Filled results, then synchronizes realized PnL/Equity/Drawdown.
- The stable `order_intent_id` formula currently uses ticker + side + shares + reference price. Any redesign must preserve retry idempotency and be a separate safety change.
- The user's local working tree previously showed `M results/decision_log_report.csv` and untracked `data/`; do not delete or overwrite those runtime/local artifacts automatically.

## Verification boundary
- GitHub CI cannot access the user's local TWS/Gateway.
- Direct SPY contract resolution, one controlled Paper fill, and fill-state persistence are verified from the user's local runtime evidence.
- The integrated end-to-end `paper_trading_runner.py` path with the newly merged shared risk gate has not yet been observed against the user's local TWS Paper session.
- No Live Trading completion claim is permitted.

## Single next action
On the user's Chromebook with TWS Paper logged in, sync `main` and run one controlled integrated Paper runner validation with explicit IBKR Paper opt-in, then inspect its output and generated reporting state. Do not repeat the standalone SPY test order.
