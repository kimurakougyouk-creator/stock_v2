# One-command foundation audit

After local setup and with IBKR Gateway/TWS Paper logged in when connection validation is desired:

```bash
bash scripts/audit_foundation.sh
```

The command runs, in order:

1. tracked-file secret scan;
2. the full pytest suite;
3. the IBKR Paper no-transmit smoke test.

The smoke test performs the Paper API handshake and safety guard checks but does not transmit an order. Live Trading is not enabled by this audit command.
