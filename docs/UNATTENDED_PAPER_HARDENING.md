# Unattended Paper hardening

This checklist applies only to the exact verified IBKR Paper scope. It does not enable Live trading and does not broaden the verified product set.

## Invariants

- The unattended/read-only path must never supply a Paper transmission confirmation token.
- The unattended/read-only path must not invoke an IBKR What-If/order-preview `placeOrder` request. What-If remains a deliberate operator-only diagnostic even though it does not transmit a real order.
- Live enable/unlock flags must never be supplied.
- The unattended service must execute only an exact locally pinned, audited `main` commit.
- The unattended service must never `git pull`, `git fetch`, switch/checkout a branch, or execute newly downloaded source code. Future source updates require a deliberate installer run after its regression tests pass.
- A one-time migration bootstrap may pin the exact current `main` HEAD when upgrading from the previously audited self-updating daemon. The pin is persisted locally with mode 0600 so later restarts do not silently adopt a different HEAD.
- A local branch/HEAD mismatch against the pin must block monitor-code execution for that cycle without placing, changing, cancelling, closing, or retrying an order.
- Tracked source changes outside runtime-output directories (`results/` and `data/`) must block monitor-code execution. Runtime artifacts may continue changing normally.
- A GitHub/network outage must not prevent the already-installed pinned read-only monitor from running because routine cycles do not depend on GitHub availability.
- Missing virtualenv or monitor failure remain fail-closed/non-order conditions.
- No uncertain order state may be automatically retried.
- Broker account state is usable only after the account-download and account-summary completion callbacks have both been observed. Partial snapshots fail closed.
- Monitoring must cover the exact verified AAPL / SPY / 9432.T scope, including broker/local quantity gaps, all open orders across API clients, trusted accounting, and the latest deliberate verified-runtime result.
- A broker position is verified only when symbol, security type, currency, and aggregate quantity match the exact approved contract: AAPL/STK/USD/1, SPY/STK/USD/1, or 9432/STK/JPY/100. Same-symbol options/derivatives or wrong-currency contracts are not equivalent.
- Any open order, accounting failure, reconciliation blocker, quantity gap, unverified broker contract/position, or Live safety-lock failure is recorded as `CRITICAL`. The monitor must not cancel, change, close, or retry the order.
- Broker/API unavailability and a missing/stale structured runtime report are recorded as `WARNING` while later read-only monitoring cycles continue.
- Latest monitoring state is written atomically; bounded JSONL history is kept locally and is not committed to GitHub.
- When existing local Gmail credentials are available, warning/critical status transitions and bounded repeat alerts are emailed to the configured owner. Missing credentials remain an explicit monitoring warning; secrets are never written into monitoring output.

## Evidence required

1. Static regression tests proving no order-confirmation, What-If/order-preview invocation, or Live-unlock strings exist in unattended/read-only wrappers.
2. Static regression tests proving the daemon contains no unattended pull/fetch/branch-switch/self-update path and verifies local `main`, the pinned HEAD, and tracked-source cleanliness before monitor execution.
3. Regression tests proving incomplete account snapshots fail closed and same-symbol non-stock contracts cannot pass as verified positions.
4. CI success for the full test suite.
5. A bounded local read-only soak/restart check when local-runtime evidence is needed; never send a duplicate Paper trade or What-If request merely for this hardening audit.

## Operations monitor outputs

- `results/ibkr_paper_operations_monitor_latest.json`: latest machine-readable state
- `results/ibkr_paper_operations_monitor_history.jsonl`: bounded observation history
- `results/ibkr_paper_operations_monitor_status.txt`: short operator summary
- `results/ibkr_paper_operations_monitor_latest.log`: latest service-cycle console output
- `results/ibkr_verified_paper_runtime_latest.json`: latest deliberate runtime outcome
- `results/ibkr_verified_paper_runtime_history.jsonl`: deliberate runtime history
- `results/ibkr_paper_operations_monitor_notification_state.json`: alert deduplication/cooldown state without credentials
- `results/ibkr_readonly_autopilot.log`: bounded unattended-service log, including pinned revision evidence

The monitor does not run the deliberate Paper ordering entry point or the What-If/order-preview checkpoint. Ordinary verified Paper scans and diagnostics remain separately initiated and explicitly confirmed.
