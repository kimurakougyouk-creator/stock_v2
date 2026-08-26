# stock_v2 / AI Asset Platform — Canonical Handoff Master

Last verified: 2026-08-27 (JST)

This is the canonical cross-chat handoff entry point. Keep it concise. Detailed bounded capability evidence remains in `PROJECT_STATE.md`; current code is always determined from GitHub `main`.

## Current operating model

- **ChatGPT chat** is the primary project-management and GitHub execution environment.
- **GitHub `main`** is the canonical remote code/evidence source.
- **Chromebook + IBKR Paper** is used only when local runtime evidence is genuinely indispensable.
- **Work** is optional/supplemental only; do not require migration to Work or extra paid usage to continue this project.
- **Claude Code** is used only when local-filesystem implementation/testing is materially required or clearly faster than remote GitHub work.
- **User action is last resort**. Do all GitHub-side investigation, implementation, review, CI/status checking, issue cleanup, and documentation first. When local action is truly unavoidable, show `🟢 あなたの出番です` and provide exactly one complete copy-paste command.

## Absolute safety boundary

- Live Trading is prohibited and must remain fail-closed.
- Do not enable or add a Live order path.
- Do not repeat an already-proven Paper order merely to recreate evidence.
- Timeout or uncertain broker state must never be automatically resent.
- Unattended monitoring must never place, change, cancel, close, retry, or transmit an order.
- Unattended monitoring must not issue IBKR What-If/order-preview `placeOrder` requests.
- Broad FUTURES / OPTIONS / FX / CRYPTO claims remain prohibited beyond the exact evidence recorded in `PROJECT_STATE.md`.

## Repository / environment

- Repository: `kimurakougyouk-creator/stock_v2`
- Canonical branch: `main`
- Chromebook directory: `~/stock_v2_latest`
- Python venv: `.venv`
- Proven IBKR Paper Gateway endpoint: `127.0.0.1:4002`
- TWS Paper alternative: `7497`
- Account currency: JPY
- Account timezone: Asia/Tokyo

## Source-of-truth priority

When sources disagree:

1. Current GitHub `main` code.
2. Latest actual Chromebook / IBKR Paper runtime evidence.
3. This `HANDOFF_MASTER.md`.
4. `PROJECT_STATE.md` for the bounded capability ledger.
5. Historical chats, old handoffs, old branches, old version labels.

Do not return to old Version 1.x / 31-test / 32-test states.

## Current verified GitHub state

The following work is merged:

- PR #242 — exact-scope IBKR Paper milestone completion record.
- PR #243 — comprehensive Paper operations monitoring.
- PR #244 — unattended monitor made strictly read-only by removing `ibkr_auto.sh` / operator-checkpoint What-If requests.
- PR #245 — installer now restarts an already-running older autopilot so the latest strict read-only script is actually loaded.

`main` after PR #245 was `3a54261ef6dc45bd6badbfe6feb4428a0d3d9c90`. Always verify current `main` before acting because later documentation or safety commits may advance it.

At the last checked state there were no open PRs requiring engineering action.

## Exact verified Paper scope

The deliberate verified signal/order bridge remains limited to:

- AAPL: 1 share
- SPY: 1 share
- 9432.T: 100 shares

Unsupported ticker/quantity combinations remain fail-closed.

The final deliberate verified runtime already completed successfully with:

- AAPL final `HOLD`
- SPY final `HOLD`
- 9432.T final `HOLD`
- 3 analysis records
- 0 data/runtime/execution errors
- 0 new fills, correctly expected because all final decisions were HOLD
- Live order sent: `False`

Do not force a BUY/SELL merely to generate another fill.

Detailed ESU6 futures, pinned SPY option, stock/ETF, FX, crypto, accounting, reconciliation, execution-ID, and historical FX boundaries are recorded in `PROJECT_STATE.md` and must not be generalized.

## Chromebook runtime state verified 2026-08-27

The user synchronized local `main` and installed the strict read-only systemd autopilot.

Observed installation result:

- monitoring installation tests: `33 passed in 2.88s`
- `ibkr-readonly-autopilot.service`: loaded and enabled
- service state: `active (running)`
- service started: 2026-08-27 02:31:51 JST
- process: `bash /home/kimurakougyouk/stock_v2_latest/ibkr_readonly_autopilot.sh`
- local generated artifact remained modified: `M results/decision_log_report.csv`; do not reset/stash/delete/commit it merely to clean the tree

The autopilot default interval is 300 seconds and monitors:

- IBKR Paper account/API readiness
- exact AAPL / SPY / 9432.T broker/local reconciliation
- all open orders across API clients
- trusted accounting / equity / drawdown state
- active risk limits
- latest verified-runtime status and freshness
- WARNING / CRITICAL alert state

The strict unattended path sends no real Paper order, no What-If/order-preview request, and no Live order; it does not modify, cancel, close, or retry broker orders.

## Alerting / observation

The monitor can use existing local Gmail credentials when available. Initial HEALTHY status records a baseline without sending mail. WARNING / CRITICAL transitions and bounded repeat alerts may send `[IBKR Paper Monitor] ...` messages; missing mail credentials must not weaken broker safety.

A separate ChatGPT condition-watch checks Gmail hourly for new `[IBKR Paper Monitor]` WARNING/CRITICAL messages and notifies only on meaningful new alerts. This external watch is supplemental; the local 5-minute monitor remains the primary operational evidence source.

## Current development stage

The exact verified-scope Paper milestone is complete. The current stage is **monitored Paper operation over time**, not endless feature creation and not duplicate broker proof.

The next objectives are:

1. accumulate safe ordinary monitoring/runtime evidence over time;
2. detect and repair operational/reconciliation/accounting/risk defects only when evidence shows one;
3. evaluate strategy quality from real Paper decisions/fills when they naturally occur;
4. improve reporting and recovery only where monitoring exposes a concrete gap;
5. keep Live Trading outside scope until a separate future decision explicitly authorizes it.

Do not invent a requirement for new orders, broader assets, or paid tooling just to make progress.

## What the next agent must do first

Do **not** immediately give the user commands.

First, on the AI side:

1. verify current GitHub `main`;
2. verify open PRs/issues and any new CI evidence;
3. read this file and `PROJECT_STATE.md`;
4. preserve Live fail-closed and strict unattended no-order-request behavior;
5. inspect available alert/monitor evidence before asking for local logs;
6. continue GitHub-side work automatically when a concrete gap is found.

Only if Chromebook/IBKR state cannot be obtained or proven any other way should the user receive one local action.

---

If a future chat conflicts with this handoff, only newer `main` code or newer measured Chromebook/IBKR evidence may override it. Old chat text alone is not authoritative.
