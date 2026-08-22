# Repository-side audit checkpoint — 2026-08-22

This file exists to force a pull-request CI validation of the current repository after adding broker-only historical FX evidence. It contains no runtime configuration or credentials.

Validated intent:
- No Live Trading path is enabled.
- Historical FX fallback is read-only and uses IBKR CASH/IDEALPRO historical MIDPOINT data.
- Confirmed-fill persistence still preserves fills even when FX evidence is unavailable.
- Operator checkpoint remains non-real-order.
- The one-command operator script remains the only intended local manual entry point.
