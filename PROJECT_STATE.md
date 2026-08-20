# Project State

Last updated: 2026-08-20

This file is the concise, evidence-based handoff ledger for AI agents. Update it after meaningful verified progress. Do not replace verified facts with guesses.

## Current phase
Recovery — restore the accidentally deleted, previously uncommitted Equity/Reporting work on a dedicated recovery branch.

## Verified repository state
- Repository: `kimurakougyouk-creator/stock_v2`
- Recovery branch: `recovery/equity-20260820`
- Baseline before recovery: main `0831cb5` (`Align preflight tests with Gateway default`).
- Phases 1–8 of the IBKR Paper migration are already present in the baseline repository; do not repeat their real broker validation.
- Recovery commit `78841b2` added backward-compatible `maximum_drawdown` persistence to `performance_history.csv` and its tests.
- GitHub Actions pytest run #62 for recovery commit `78841b2` completed successfully.

## Recovery implementation now present
- Total-asset Equity History with CSV persistence.
- Equity Curve uses `total_assets`, not realized PnL.
- Total-asset maximum drawdown calculation.
- Equity chart generation.
- Legacy paper-order ledger -> Account/Portfolio replay -> Equity bridge.
- `order_intent_id` idempotency prevents duplicate Equity accounting for confirmed IBKR fills.
- Confirmed IBKR Paper Fill -> legacy durable ledger -> Equity reporting sync is wired in `paper_trading_runner.py`.
- Dashboard-safe Equity summary helper and tests.
- Mock/file-only Fill-to-Equity E2E test; it does not connect to IBKR or send an order.

## Safety status
- No Live Trading enablement was added.
- No IBKR/TWS/Gateway connection was made during this recovery.
- No new Paper order was sent during this recovery.
- Runtime `data/`, send-locks, and runtime fill-state files were not recreated or modified by the GitHub recovery work.
- Do not fabricate deleted runtime evidence. Historical evidence and runtime files are different things.

## Verification status
- The first recovery slice (`maximum_drawdown` persistence) is VERIFIED by GitHub Actions pytest #62 success.
- The later Equity recovery commits are IMPLEMENTED_UNVERIFIED until their current-head GitHub Actions pytest completes successfully.
- Do not merge the recovery PR until the current recovery head is green.

## Single next action
Obtain the GitHub Actions pytest result for the current recovery head. If it fails, fix only the evidenced code failure and re-run CI; if it succeeds, review the recovery PR diff and merge only after confirming no broker/runtime safety boundary changed.
