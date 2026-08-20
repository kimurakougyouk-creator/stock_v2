# Project State

Last updated: 2026-08-20

This file is the concise, evidence-based handoff ledger for AI agents. Update it after meaningful verified progress. Do not replace verified facts with guesses.

## Current phase
Post-recovery main audit — Equity/Reporting recovery is merged. Continue from the new main baseline; do not repeat the recovery work or previously verified real-broker validation.

## Verified repository state
- Repository: `kimurakougyouk-creator/stock_v2`
- Branch: `main`
- Current recovery merge commit: `9a4a0a272da635583ec3d7ef8b8f518f34607d85` — `Restore equity history, curve, drawdown, and IBKR fill reporting`.
- Parent baseline: `0831cb57ae53f4843f63c9c9b94414feef4aca61` — `Align preflight tests with Gateway default`.
- PR #42 was reviewed as mergeable, marked ready, and squash-merged to main.
- The PR merge candidate passed the complete repository pytest suite: 718 passed / 0 failed.
- Phases 1–8 of the IBKR Paper migration were already present before the Equity recovery; do not repeat their real broker validation merely to re-prove historical evidence.

## Equity/Reporting recovery now merged
- `maximum_drawdown` persistence to `performance_history.csv`, including legacy-CSV migration and unknown-column fail-safe behavior.
- Total-asset Equity History with CSV persistence.
- Equity Curve based on `total_assets`, not realized PnL.
- Total-asset maximum drawdown calculation.
- Browser-native HTML/SVG Equity chart generation.
- Legacy paper-order ledger -> existing Account/Portfolio fill replay -> Equity bridge.
- `order_intent_id` idempotency prevents duplicate Equity accounting for confirmed IBKR fills.
- Confirmed IBKR Paper Fill -> durable legacy ledger -> realized-PnL regeneration -> Equity reporting sync in `paper_trading_runner.py`.
- Dashboard Equity summary, Equity Curve, and total-asset Drawdown integration.
- Mock/file-only Fill-to-Equity E2E coverage; tests do not connect to IBKR or send an order.

## Audit findings retained for future work
- The stable `order_intent_id` formula (`ticker + side + shares + reference_price`) existed in baseline main before the Equity recovery. It is not an Equity-recovery regression. Any future redesign must be a separate safety change spanning signal creation through broker execution and must preserve retry idempotency.
- Dashboard recovery uses `dashboard_core.py` to preserve the existing Dashboard body while `dashboard.py` adds Equity integration. This structure was retained because the complete merge candidate was green and re-collapsing the files would add unnecessary recovery risk.
- `performance_history.py` changes are required for `maximum_drawdown` persistence while preserving legacy CSV compatibility; unknown columns fail safely rather than being silently discarded.

## Safety status
- No Live Trading enablement was added by the recovery.
- No IBKR/TWS/Gateway connection was made during the GitHub recovery work.
- No new Paper order was sent during the recovery.
- Runtime `data/`, send-locks, and runtime fill-state files were not recreated or modified by the GitHub recovery work.
- Do not fabricate deleted runtime evidence. Historical evidence and runtime files are different things.

## Verification status
- PR #42 merge candidate: VERIFIED GREEN — 718 passed / 0 failed.
- Recovery is merged to main; do not reopen or repeat it unless a new failing test or concrete defect is observed.
- A future change must be verified independently on its own head before merge.

## Single next action
Audit the new main baseline for the remaining unfinished auto-trading milestones only, then implement the highest-priority missing milestone without repeating completed Equity recovery or real-broker validation.
