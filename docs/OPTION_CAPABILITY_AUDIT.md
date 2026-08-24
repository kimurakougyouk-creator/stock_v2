# SPY option Paper capability audit

## Verified evidence

The broker-recovered Paper evidence is intentionally scoped to one long SPY call round-trip:

- Contract: `SPY   260828C00765000`
- conId: `900369377`
- Expiry: `20260828`
- Strike/right: `765 C`
- Multiplier: `100`
- BUY 1 @ 4.08, order 1, exec `00020057.6a8c86b2.01.01`
- SELL 1 @ 4.07, order 2, exec `00020057.6a8c86b3.01.01`
- Same US/Eastern trading date: 2026-08-24
- Broker position after close: 0
- Matching open orders after close: 0
- Gross realized option PnL: -1.00 USD
- Restart-style execution recovery: verified
- What-If on the same pinned contract: verified
- Market order support, SMART routing, min tick and broker liquid-hours metadata: verified
- Live order sent: false

## Supported scope

Only `US_SPY_OPTION_LONG_INTRADAY / OPTION / IBKR / Paper` is treated as verified.
The scope requires BUY-to-open then SELL-to-close, start flat, end flat, same-session close, and close before expiration day.

## Explicitly NOT verified

The following remain outside the capability and must fail closed rather than be inferred from the round-trip evidence:

- General US option support across underlyings/contracts
- Short options / naked options / SELL-to-open
- Multi-leg spreads
- Overnight option holding
- Expiry-day holding
- Automatic exercise
- Manual exercise
- Assignment handling
- Expiration/settlement processing
- Corporate-action edge cases
- Live trading

This narrow scope avoids overclaiming lifecycle support: because positions must be long-only and closed in the same session before expiry day, assignment and expiration are outside the allowed operating path rather than silently assumed to work.
