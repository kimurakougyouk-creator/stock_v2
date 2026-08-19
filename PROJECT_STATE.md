# Project State

Last updated: 2026-08-19

This file is the concise, evidence-based handoff ledger for AI agents. Update it after meaningful verified progress. Do not replace verified facts with guesses.

## Current phase
Phase 1 — IBKR adapter asynchronous send-and-observe path.

## Verified repository state
- Repository: `kimurakougyouk-creator/stock_v2`
- Branch: `main`
- Phase 1 commit is present on main: `1d12eda39071be9c5dfd4a6ce351dfcf38128e24` — `Add place_order_and_await_fill() with intent-based duplicate-send guard`.
- Earlier relevant commits on main include:
  - `ca65686d10ced8a1751049debcabc094b92b554d` — reconciliation reconnect stabilization.
  - `54b2956e4d684e5478148028512770e99f7797b1` — IBKR Paper order TIF fix.
  - `5586136b04536be93bd5e77dd05198440e17e1f2` — IBKR Paper API observability improvements.

## Verified functional evidence from the development session
- IB Gateway Paper API connection succeeded at `127.0.0.1:4002`.
- Paper E2E after the TIF fix reached `Filled` for the controlled AAPL BUY 1 market test; `orderStatus`, `openOrder`, and `execDetails` were observed and fill state was persisted.
- The prior error 10052 (blank Time in Force) was traced to missing `Order.tif` and fixed with `DAY`.
- Read-only reconciliation later returned `FOUND` for that tested order, with server version 223 and next valid id advanced to 2.
- Phase 1 implementation adds `place_order_and_await_fill()` and intent-id duplicate-send protection. The commit message explicitly states in-process plus cross-process locking, no inferred fill status, and no auto-retry.

## Unverified / do not overclaim
- The final repository-wide IBKR pytest run and full pytest run *after the Phase 1 commit* have not been evidenced in the conversation log available to the PM. Treat them as UNVERIFIED until an actual test/CI result is observed.
- Do not infer Live readiness from Paper success.

## Architecture decision
Canonical target architecture is `src/ai_asset_platform`:

ExecutionService -> BrokerManager -> BrokerAdapter -> broker-specific adapter.

Legacy root execution (`signal_runner.py` / `order_manager.py`) remains separate for now. Its safety controls must be migrated into a shared risk gate before it is replaced or connected to the new execution path.

## Next implementation plan
1. Obtain only the missing Phase 1 test evidence (IBKR-related pytest and full pytest) without repeating Paper E2E or changing runtime artifacts.
2. Phase 2: ExecutionService IBKR Paper asynchronous path, preserving existing synchronous behavior.
3. Phase 3: BrokerManager/settings explicit `IBKR_PAPER` opt-in; no implicit/default IBKR selection.
4. Shared risk gate migration from legacy safety controls.
5. Incremental legacy execution migration.
6. Integration tests and final Paper validation.

## Single next action
Run/obtain the missing Phase 1 test evidence on the current main without changing code or sending any broker order. If evidence already exists in CI, use it instead of rerunning locally.

## Safety status
- No Live-trading enablement is authorized by this state file.
- Do not send a new Paper order merely to re-prove already verified E2E behavior.
- Do not delete or modify runtime `data/` lock/state artifacts as housekeeping.
