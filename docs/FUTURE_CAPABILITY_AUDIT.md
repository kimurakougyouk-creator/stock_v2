# ESU6 futures Paper capability audit

## Verified evidence

The broker-observed Paper evidence is intentionally scoped to one ESU6 round-trip:

- Contract: `ESU6`
- conId: `649180671`
- Expiry: `20260918`
- Multiplier: `50`
- BUY 1 @ `7668.25`
- SELL 1 @ `7667.75`
- Broker position after close: `0`
- Gross realized futures PnL: `-25.00 USD`
- Unrealized PnL after close: `0 USD`
- Ending equity delta: `-25.00 USD`
- Max drawdown for the closed round-trip: `25.00 USD`
- Restart-style execution identity recovery: verified
- Live order sent: false

## Supported scope

Only `US_ESU6_FUTURE_LONG_ROUNDTRIP / FUTURE / IBKR / Paper` is treated as verified.
The scope is pinned to ESU6/conId 649180671, exactly one contract, BUY first then SELL to close, start flat and end flat.

## Explicitly NOT verified

The following remain outside the capability and must fail closed rather than be inferred:

- General futures support across contracts/exchanges
- Other ES expiries or automatic contract rolling
- Short-first futures trading
- More than one contract
- Overnight futures holding
- Expiry/settlement handling
- Margin stress/liquidation behavior
- Live trading

This narrow scope records what the broker evidence actually proves without promoting the whole FUTURE asset class.
