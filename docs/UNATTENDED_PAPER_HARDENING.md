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

## Evidence required

1. Static regression tests proving no order-confirmation or Live-unlock strings exist in unattended/read-only wrappers.
2. Static regression tests proving `git switch main` remains mandatory while `git pull` failure has an explicit offline/local-main continuation path.
3. CI success for the full test suite.
4. A bounded local read-only soak/restart check when local-runtime evidence is needed; never send a duplicate Paper trade merely for this hardening audit.
