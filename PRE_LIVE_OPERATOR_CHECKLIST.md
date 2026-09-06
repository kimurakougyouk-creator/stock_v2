# First Live Cash Pilot — Operator Prerequisites

Last verified: 2026-09-06 JST

This checklist exists so non-code prerequisites are not discovered at the last minute. It does not authorize a Live order.

## Today / before the pilot day

The following must be prepared or verified before the execution day where possible:

- [ ] Correct IBKR **Live** account is active and login works.
- [ ] MFA / passkey / mobile authentication works.
- [ ] Funds have actually arrived and are available/settled for trading; a transfer instruction alone is insufficient.
- [ ] Appropriate currency/cash is available for the intended instrument, with a buffer for commissions/fees.
- [ ] Trading permission for the intended market/product is approved.
- [ ] Any mandatory market registration is complete (for Japanese cash equities, verify JASDEC eligibility/registration as applicable to the account).
- [ ] TWS or IB Gateway can be launched in **Live** mode.
- [ ] API **Read-Only remains ON** throughout preparation.
- [ ] Chromebook/network/power/runtime environment is available for the intended session.
- [ ] No planned software update/reboot should interrupt the execution window.
- [ ] The intended market is scheduled to be open on the pilot date.

## Must be re-verified fresh on the pilot day

Do not rely on yesterday's `latest.json` or screenshots for these:

- [ ] audited/pinned Git commit and safety-critical working tree;
- [ ] correct Live endpoint/session/account fingerprint;
- [ ] available funds and permissions;
- [ ] exact target position;
- [ ] zero unexpected Live open orders;
- [ ] fresh quote and FX evidence as applicable;
- [ ] exact LIMIT price × quantity × FX-derived JPY notional under the pilot cap;
- [ ] market/session is currently open and allowed by the guard;
- [ ] emergency-stop latch is clear immediately before any future sender;
- [ ] one-shot authorization is fresh, exact, unused, and bound to account/instrument/quantity/price/source;
- [ ] Paper monitor/safety state remains healthy where required;
- [ ] operator has explicitly approved the exact single real-cash pilot action.

## Actions that must NOT be done early

- [ ] Do **not** turn API Read-Only OFF during preparation.
- [ ] Do **not** enable ordinary/unbounded Live strategy deployment.
- [ ] Do **not** create a second authorization as a workaround after timeout/disconnect/UNKNOWN.
- [ ] Do **not** retry, cancel, modify, flatten, or close automatically while broker state is UNKNOWN.

## Current 2026-09-07 calendar note

- NYSE regular session: closed for Labor Day; do not use AAPL/SPY as a regular-session pilot candidate.
- JPX: scheduled regular trading day; within the already-bounded exact pilot scope, `9432.T` is the calendar-compatible candidate, subject to every other gate.

This is execution-mechanics preparation only, not an investment recommendation.
