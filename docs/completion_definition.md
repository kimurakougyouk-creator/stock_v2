# Paper foundation completion definition

The common Paper foundation is complete only when all of the following are evidenced on the current main branch:

- full automated test suite passes;
- Live Trading remains disabled/fail-closed by default;
- IBKR Paper requires explicit opt-in;
- IBKR Paper API no-transmit smoke succeeds against the user's Paper TWS/Gateway when an external connection check is required;
- confirmed Paper fills feed trade reporting/equity/drawdown state;
- signal, backtest, trade-history, PnL, equity and drawdown outputs have automated coverage;
- risk guards have automated boundary coverage;
- tracked-file secret scanning passes in CI;
- generated runtime artifacts and local backup/save files do not pollute Git tracking;
- setup/run/audit entrypoints are documented and minimized;
- all legacy open issues are either completed or explicitly superseded with evidence;
- historically exposed provider credentials are revoked/removed at the provider.

Passing pytest alone is necessary but not sufficient for completion.
