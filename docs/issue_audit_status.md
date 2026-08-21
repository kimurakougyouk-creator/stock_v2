# Remaining issue audit status

This document prevents legacy issues from being reimplemented blindly.

## #6 — Security

Code-side status: backup/save artifacts removed from current main; ignore rules exist; this branch adds tracked-file secret scanning, CI enforcement, safe credential documentation, and regression tests.

External blocker: provider-side revocation/removal of the historically exposed Gmail app password cannot be proven from the repository and must be confirmed in the Google Account before #6 is closed.

## #8 — One-command environment/run flow

Existing `scripts/setup.sh` already creates the environment, installs dependencies, and runs tests. This branch adds `.env.example` and `scripts/run.sh`, which loads the ignored local environment and delegates to the existing `start.sh` flow. This avoids duplicating the trading pipeline.

## #23 — Signal automation legacy issue

Current main has evolved beyond the original analysis-only/no-order design. `signal_runner.py` is part of the current signal pipeline, while IBKR Paper execution is separately opt-in and Live Trading remains fail-closed. #23 must be closed as superseded only after its remaining output/notification expectations are mapped to current tests and behavior; do not restore the obsolete no-order architecture.

## #50 — Final foundation audit

Keep open until the common Paper foundation has evidence for signals, backtesting, trade history, realized/unrealized PnL, equity history, drawdown, risk guards, IBKR Paper no-transmit smoke, Live fail-closed behavior, and a one-command audit path.
