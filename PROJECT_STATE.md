# Project State

Last updated: 2026-08-20

This file is the concise, evidence-based handoff ledger for AI agents. Update it after meaningful verified progress. Do not replace verified facts with guesses.

## Current phase
Recovery final audit — restore the accidentally deleted, previously uncommitted Equity/Reporting work on a dedicated recovery branch and minimize unrelated changes before merge.

## Verified repository state
- Repository: `kimurakougyouk-creator/stock_v2`
- Recovery branch: `recovery/equity-20260820`
- Baseline before recovery: main `0831cb5` (`Align preflight tests with Gateway default`).
- Phases 1–8 of the IBKR Paper migration are already present in the baseline repository; do not repeat their real broker validation.
- `maximum_drawdown` persistence to `performance_history.csv` is implemented with legacy-CSV migration and unknown-column fail-safe behavior.
- GitHub Actions pytest run #134 for recovery head `736ea0a` completed successfully.
- Earlier full-suite recovery verification reached 718 passed / 0 failed; later head #134 is also green. Do not infer a newer exact collected-test count without reading that run's pytest log.

## Recovery implementation now present
- Total-asset Equity History with CSV persistence.
- Equity Curve uses `total_assets`, not realized PnL.
- Total-asset maximum drawdown calculation.
- Browser-native HTML/SVG Equity chart generation.
- Legacy paper-order ledger -> existing Account/Portfolio fill replay -> Equity bridge.
- `order_intent_id` idempotency prevents duplicate Equity accounting for confirmed IBKR fills.
- Confirmed IBKR Paper Fill -> legacy durable ledger -> realized-PnL regeneration -> Equity reporting sync is wired in `paper_trading_runner.py`.
- Dashboard Equity summary, Equity Curve, and total-asset Drawdown integration plus tests.
- Mock/file-only Fill-to-Equity E2E tests; they do not connect to IBKR or send an order.

## Audit findings
- The stable `order_intent_id` formula (`ticker + side + shares + reference_price`) already existed in baseline main `0831cb5`; it is not an Equity-recovery regression. Do not redesign it inside this recovery PR. Any future intent-ID redesign must be a separate safety change spanning signal creation through broker execution.
- Current recovery diff still contains a large Dashboard refactor: most original `dashboard.py` was moved to new `dashboard_core.py`, while `dashboard.py` became an Equity wrapper. Tests are green, but this is larger than the desired minimal recovery diff and must be reviewed before merge.
- `performance_history.py` changes are functionally required for adding `maximum_drawdown` while preserving legacy CSV compatibility; unknown columns fail safely rather than being silently discarded.

## Safety status
- No Live Trading enablement was added.
- No IBKR/TWS/Gateway connection was made during this recovery.
- No new Paper order was sent during this recovery.
- Runtime `data/`, send-locks, and runtime fill-state files were not recreated or modified by the GitHub recovery work.
- Do not fabricate deleted runtime evidence. Historical evidence and runtime files are different things.

## Verification status
- Recovery head `736ea0a` is VERIFIED GREEN by GitHub Actions pytest run #134.
- A green suite is necessary but not sufficient for merge: the PR diff must also satisfy the minimal-change and broker/runtime safety audit.
- Keep PR #42 draft/unmerged until the remaining Dashboard structural-diff review is resolved and the resulting head is green again.

## Single next action
Resolve the oversized Dashboard structural diff without losing Equity functionality, then run the complete pytest workflow again and re-audit the final PR diff before merge.
