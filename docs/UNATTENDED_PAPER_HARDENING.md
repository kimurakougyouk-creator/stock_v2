# Unattended Paper hardening

This checklist applies only to the exact verified IBKR Paper scope. It does not enable Live trading and does not broaden the verified product set.

## Invariants

- The unattended/read-only path must never supply a Paper transmission confirmation token.
- Live enable/unlock flags must never be supplied.
- A transient GitHub/network outage must not prevent already-installed, read-only local broker reconciliation and health checks from running from the current `main` checkout.
- Failure to switch to local `main` remains fatal. The system must never silently run an arbitrary feature branch.
- A failed `git pull --ff-only origin main` must be logged prominently and the cycle may continue from the unchanged local `main` revision.
- A successful fast-forward update must cause the long-running autopilot to reload itself before the next audit work so the new revision is actually used.
- Missing virtualenv, unavailable IBKR Paper endpoint, reconciliation failure, or checkpoint failure remain fail-closed/non-order conditions.
- No uncertain order state may be automatically retried.
- Monitoring must cover the exact verified AAPL / SPY / 9432.T scope, including
  broker/local quantity gaps, all open orders across API clients, trusted
  accounting, and the latest deliberate verified-runtime result.
- Any open order, accounting failure, reconciliation blocker, quantity gap, or
  Live safety-lock failure is recorded as `CRITICAL`. The monitor must not
  cancel, change, close, or retry the order.
- Broker/API unavailability and a missing/stale structured runtime report are
  recorded as `WARNING` while later read-only monitoring cycles continue.
- Latest monitoring state is written atomically; bounded JSONL history is kept
  locally and is not committed to GitHub.
- When existing local Gmail credentials are available, warning/critical status
  transitions and bounded repeat alerts are emailed to the configured owner.
  Missing credentials remain an explicit monitoring warning; secrets are never
  written into monitoring output.

## Evidence required

1. Static regression tests proving no order-confirmation or Live-unlock strings exist in unattended/read-only wrappers.
2. Static regression tests proving `git switch main` remains mandatory while `git pull` failure has an explicit offline/local-main continuation path.
3. CI success for the full test suite.
4. A bounded local read-only soak/restart check when local-runtime evidence is needed; never send a duplicate Paper trade merely for this hardening audit.

## Operations monitor outputs

- `results/ibkr_paper_operations_monitor_latest.json`: latest machine-readable state
- `results/ibkr_paper_operations_monitor_history.jsonl`: bounded observation history
- `results/ibkr_paper_operations_monitor_status.txt`: short operator summary
- `results/ibkr_paper_operations_monitor_latest.log`: latest service-cycle console output
- `results/ibkr_verified_paper_runtime_latest.json`: latest deliberate runtime outcome
- `results/ibkr_verified_paper_runtime_history.jsonl`: deliberate runtime history
- `results/ibkr_paper_operations_monitor_notification_state.json`: alert deduplication/cooldown state without credentials

The monitor does not run the deliberate Paper ordering entry point. Ordinary
verified Paper scans remain separately initiated and explicitly confirmed.
