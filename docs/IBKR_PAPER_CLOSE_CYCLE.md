# IBKR Paper SPY close cycle

This path is Paper-only and position-reducing. It does not create new exposure and it does not enable Live Trading.

The coordinator requires the broker Paper account snapshot to be ready, requires exactly one broker-held SPY share, derives a bounded LIMIT price from the broker-reported SPY market price, runs the dedicated close path, and only after a confirmed fill persists does the wrapper invoke the non-order `ibkr_auto.sh` checkpoint.

If the broker snapshot is unavailable, SPY quantity is not exactly one, the reference price is unavailable, the Overnight session is closed, the dedicated close opt-in is absent, reconciliation is unsafe, the SELL preflight fails, the SELL what-if fails, or the broker does not confirm a fill, the cycle stops fail-closed.

Timeout or uncertain broker state is never automatically resent. Live Trading remains prohibited.