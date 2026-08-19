# Phase 7 — Signal Runner Final Wiring

Status: implementation target verified against `signal_runner.py` on this branch.

## Required final change

Replace only the legacy final paper-order dispatch after all existing signal/risk/position/daily-limit checks have passed:

`build_paper_order_sync(...) -> create_paper_order(...)`

with the existing IBKR Paper bridge:

`execute_signal_via_ibkr_paper(...) -> ExecutionService -> risk gate -> IBKR Paper adapter`

## Non-negotiable safety constraints

- Do not add a Live Trading order path.
- Require both Paper Trading and IBKR Paper opt-ins before IBKR dispatch.
- HOLD must never dispatch an order.
- Preserve emergency stop, daily loss, consecutive loss, max positions, daily BUY/SELL limits, repurchase cooldown, cash/allocation/risk limits, trailing stop, time stop, and daily trading amount checks.
- Do not call both `create_paper_order()` and the IBKR bridge for the same intent.
- Preserve deterministic order-intent duplicate protection.
- Do not commit `data/` runtime artifacts.
- Final verification must use mocks/fakes first; no new real Paper order during code wiring.

This file is a branch-local checkpoint and does not claim the final wiring is complete.