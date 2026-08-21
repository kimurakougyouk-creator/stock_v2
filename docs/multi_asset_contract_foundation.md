# Multi-asset Contract Foundation

This layer separates broker-independent instrument identity from IBKR Contract construction.

## Safety boundary

- Creating a Contract never transmits an order.
- `VERIFIED_CAPABILITIES` remains unchanged until a real Paper E2E is proven.
- Live Trading remains disabled.
- CRYPTO intentionally fails closed until the account/region/API path is verified.
- STOCK and ETF map to IBKR `STK`; FX to `CASH`; FUTURE to `FUT`; OPTION to `OPT`.
- Derivative-specific fields are validated before Contract construction.

## Integration rule

Do not replace the existing AAPL Paper path until regression tests prove byte-for-behavior-compatible STOCK Contract defaults and the no-transmit smoke remains green. The next integration step is to let `prepare_ibkr_paper_order` accept an optional `InstrumentSpec`, preserving the current AAPL defaults when none is supplied.
