# AI Development Operating Rules

## Mission
Complete the multi-broker, multi-market AI trading platform safely and efficiently. Optimize for completion, maintainability, evidence, and minimal user effort—not for generating more terminal work.

## Roles
- ChatGPT: project manager, architecture/safety decisions, verification, progress control.
- Claude Code / coding agents: inspect, implement, test, self-review, and report evidence.
- User: only actions that AI cannot perform, such as login/identity verification and explicit approval for consequential real trading actions.

## Operating rules
1. Do not ask the user to perform work that an AI/tool can perform.
2. Before acting, distinguish DONE / VERIFIED / UNVERIFIED / TODO. Do not redo verified work without new evidence or a concrete reason.
3. Work on one primary task at a time and choose the shortest safe path toward completion.
4. Batch agent work when possible: inspect -> implement -> test -> self-review -> concise report.
5. Do not follow incidental tool suggestions (lint tools, reviews, new dependencies, etc.) unless they materially advance the current goal.
6. Never infer success. Use Git history, tests, CI, runtime observations, and broker callbacks as evidence.
7. If evidence is missing, say UNVERIFIED rather than guessing.
8. Preserve runtime data/lock/state artifacts unless a task explicitly requires changing them.
9. Keep changes small, reviewable, and backward-compatible where practical.
10. At task end, update PROJECT_STATE.md only with verified facts and the single next action.

## Trading safety invariants
- Paper and Live must remain explicitly separated.
- Live trading must never be enabled implicitly.
- No automatic resend after timeout or UNKNOWN state.
- Duplicate-order prevention is mandatory.
- Timeout/connection failure is never treated as a successful fill.
- Capture broker errors instead of swallowing them.
- Unknown broker state remains UNKNOWN until reconciled.
- Important execution changes require tests before being considered complete.

## Architecture direction
The canonical platform architecture is under `src/ai_asset_platform`:

ExecutionService -> BrokerManager -> BrokerAdapter -> broker-specific adapter

Root-level legacy execution (`signal_runner.py` / `order_manager.py`) is not to be deleted or silently bypassed. Its safety controls must be migrated deliberately into a shared risk gate before production integration.

## IBKR work already verified; do not restart without new evidence
- IB Gateway Paper API connectivity at 127.0.0.1:4002.
- Paper order path and account verification work.
- TIF bug fixed with `tif="DAY"`; prior IBKR error 10052 was resolved in Paper E2E.
- `orderStatus`, `openOrder`, `execDetails`, broker errors, serverVersion, nextValidId, message-loop diagnostics, fill-state persistence and read-only reconciliation observability exist.
- Read-only reconciliation has successfully found the tested fill after reconnect.
- Reconciliation reconnect stabilization is committed.
- Phase 1 async adapter work is committed at `1d12eda39071be9c5dfd4a6ce351dfcf38128e24` on main: `place_order_and_await_fill()` with intent-based duplicate-send protection (in-process plus cross-process lock), no inferred fill, and no auto-retry.

## Current implementation sequence
1. Close Phase 1 with any still-missing evidence only; do not redo completed IBKR E2E work.
2. Phase 2: add the IBKR Paper async path to ExecutionService while preserving the existing synchronous path.
3. Phase 3: add explicit IBKR_PAPER opt-in to BrokerManager/settings; never make it an implicit default.
4. Migrate legacy daily limits/emergency-stop and related safety logic into a shared risk gate.
5. Migrate legacy signal/order execution incrementally.
6. Run integration tests and final Paper validation before any completion claim.

## User interaction rule
Only when a user action is genuinely unavoidable, give exactly one action and state: where they are, what to do, where to press/type, and what result to expect. Otherwise continue autonomously.

## Pre-response/pre-action checklist
- Has this already been done and verified?
- Does this move the project forward from the current state?
- Can AI perform it instead of the user?
- Is there a shorter safe route?
- Are facts separated from assumptions?
- Are trading safety invariants preserved?
