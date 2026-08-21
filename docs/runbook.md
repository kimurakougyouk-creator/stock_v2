# Minimal operator runbook

Normal development setup:

```bash
bash scripts/setup.sh
```

Normal application flow after setup:

```bash
bash scripts/run.sh
```

Foundation verification:

```bash
bash scripts/audit_foundation.sh
```

The audit command does not transmit an order. A real IBKR Paper order should only be used as an explicit, separately reviewed end-to-end test. Live Trading is outside the Paper foundation completion scope and remains disabled/fail-closed.
