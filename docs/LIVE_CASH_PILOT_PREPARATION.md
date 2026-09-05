# Real-cash pilot preparation — fail-closed plan

Status: PREPARATION ONLY. Live Trading remains disabled.

## Purpose

Prepare the existing verified IBKR Paper system for a future real-cash pilot without letting a calendar date, a single Paper fill, or a manual setting change silently authorize Live Trading.

## Verified starting point

- Exact-scope IBKR Paper milestone is already complete for AAPL 1 / SPY 1 / 9432.T 100.
- Reconciliation, accounting, risk gates, duplicate-send protection, timeout/no-auto-retry behavior, open-order monitoring, recovery tests, alerting, and market-session blocking already exist.
- Unattended monitoring is strictly read-only and revision-pinned.
- `main` keeps Live Trading disabled/fail-closed.
- The natural-strategy profitability report already separates true strategy fills from validation/reset/recovery fills.

## Current blockers before any real-cash order path may be designed

1. **Net profitability is not proven.** The current strategy report explicitly sets `fees_accounted=False` and `net_profitability_proven=False`.
2. **Durable commission/fee evidence is missing from the strategy accounting path.** IBKR commission/fee callbacks must be captured and associated with `exec_id` without guessing.
3. **No audited real-cash transport exists.** The current broker/session/config path is intentionally Paper-only. Do not repurpose the Paper port/session or merely flip a boolean.
4. **No Live-specific reconciliation/monitor proof exists.** A future Live path needs its own account/position/open-order identity checks before and after the first pilot order.
5. **No explicit real-cash notional cap/one-order pilot gate is implemented.** The first Live design must fail closed unless a separate explicit operator approval and a bounded cash-risk limit are both present.
6. **Chromebook revision pinning must be updated deliberately.** A source update and monitor-pin update must be one reviewed cutover operation; unattended code must never self-update.

## Implementation order

1. Add this read-only `live_cash_readiness` gate and keep it BLOCKED until all evidence exists.
2. Capture IBKR commission/fee evidence by execution ID and extend natural-strategy accounting to true net PnL.
3. Re-run the profitability evidence using only natural strategy fills; validation/reset/recovery trades remain excluded.
4. Design a separate Live connection configuration/session. It must not reuse the Paper endpoint implicitly and must remain disabled by default.
5. Add Live-specific preflight: exact account identity, zero unexpected open orders, clean reconciliation, market session, instrument/quantity, risk/notional cap, duplicate intent, emergency stop, and explicit one-run approval.
6. Add Live-specific post-fill evidence and emergency monitoring. Unknown/timeout remains UNKNOWN; never auto-resend.
7. Only after all tests/CI and local read-only checks pass may the user be asked for the single unavoidable action needed for an explicitly approved first cash pilot.

## Non-negotiable invariants

- No automatic Live enable.
- No unattended Live order.
- No automatic retry, cancel, modify, flatten, or close on unknown state.
- No What-If request from unattended monitoring.
- No reuse of validation profits as strategy-profitability evidence.
- No completion claim based only on elapsed time.
- No branch/source update by the monitoring daemon.

## External IBKR facts checked for this preparation

- IB Gateway defaults: Live `4001`, Paper `4002`; TWS defaults: Live `7496`, Paper `7497`.
- Paper execution can differ from Live because Paper uses simulated technologies.
- IBKR exposes execution-linked commission/fee callbacks containing execution ID, commission, currency, and realized PnL fields.
- Trading through the API requires API socket access and the relevant user trading/market-data permissions.

These facts define requirements only; this document does not enable a Live connection or order path.
