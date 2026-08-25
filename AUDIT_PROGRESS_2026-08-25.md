# Completion audit progress — 2026-08-25

This ledger records only evidence already observed in repository CI or the user's IBKR Paper environment. It does not authorize Live Trading and does not infer untested capabilities.

## Verified broker/runtime evidence

- US ETF/SPY: controlled Paper BUY 1 and later position-reducing SELL 1 completed; broker/local SPY position returned to zero.
- US stock/AAPL: controlled Paper flatten reset SELL 3 completed; broker AAPL returned to zero; reset execution is quarantined from ordinary trusted PnL because the legacy opening basis was not proven.
- Japan stock 9432/TSEJ/JPY: controlled Paper BUY 100 and flatten SELL 100 completed; broker and local positions returned to zero; ordinary confirmed SELL reconciliation completed.
- Futures ESU6/CME/USD: Paper round-trip BUY 1 @ 7668.25 then SELL 1 @ 7667.75 completed and broker returned flat. Dedicated futures accounting code uses multiplier 50 and requires realized/unrealized PnL, equity/drawdown, and restart-recovery evidence before capability promotion.
- SPY option 2026-08-28 765C, conId 900369377, multiplier 100: broker history recovers BUY 1 @ 4.08 then SELL 1 @ 4.07; position is flat; prior round-trip recovery is true; gross realized PnL is -1.00 USD; exact What-If preview for the pinned contract is ready.
- Option capability boundary explicitly leaves exercise, assignment, expiration settlement, opening short options, and multi-leg options unverified.
- FX USD/JPY contract resolution and Paper API connectivity are verified, but the attempted What-If was rejected by IBKR with `FX trade would expose account to currency leverage`; FX Paper trading capability is therefore not promoted.
- Crypto account/region/Paper availability remains unverified and no crypto order path is promoted.
- Live Trading remains disabled/fail-closed; no verified flow above sent a Live order.

## Repository safety state

- The IB API message-loop teardown `serverVersion() is None` TypeError is contained for guarded probes by `ibkr_thread_runner.run_ibapi_message_loop_safely`; it is no longer an unresolved repository defect in those guarded paths.
- Derivatives are separated from the trusted stock/ETF accounting path through `derivative_accounting_boundary.py` and product-specific futures/options accounting modules.
- Unknown or unproven option lifecycle capabilities fail closed through `ibkr_verified_capabilities.py`.
- Repeating an already-proven Paper order is not required merely to obtain duplicate evidence.

## Remaining completion gates

1. Restore the local IBKR Gateway/TWS connection after the user's computer reboot, then run read-only completion checks before any further broker-dependent validation.
2. Resolve issue #182 by recording the FX external/account restriction as a capability blocker unless a no-leverage supported FX path is explicitly proven; do not bypass the broker restriction.
3. Resolve issue #184 with read-only account/region/Paper evidence for crypto before any crypto implementation or order work.
4. Refresh `PROJECT_STATE.md` so it no longer says futures/options are wholly unverified or that the guarded IB API teardown race is still unresolved.
5. Run a final integrated completion gate covering tests, controlled positions, trade history, realized/unrealized PnL, equity, drawdown, restart recovery, and the exact list of verified Paper capabilities.

## Non-goals

- No Live Trading enablement.
- No inference that all futures or all options are supported from one pinned contract.
- No inference that option exercise/assignment/expiration is supported.
- No retry or resend of uncertain broker orders.
