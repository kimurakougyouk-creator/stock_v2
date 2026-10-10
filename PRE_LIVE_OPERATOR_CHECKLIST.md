# First Live Cash Pilot — Operator Prerequisites

Last verified: 2026-10-10 JST

This checklist exists so non-code prerequisites are not discovered at the last minute. It does not authorize a Live order.

## Today / before the pilot day

The following must be prepared or verified before the execution day where possible:

- [x] Correct IBKR **Live** account is active and login works. Verified 2026-10-10 via a read-only account snapshot (`ibkr_live_readonly_account.py`, no order capability): `CONNECTED: True`, `READY: True`, `ACCOUNT READY: True`, endpoint port 7496 (TWS Live).
- [ ] MFA / passkey / mobile authentication works. (Implied by the successful login above, but not independently re-tested today; established in earlier session work.)
- [x] Funds have actually arrived and are available/settled for trading; a transfer instruction alone is insufficient. Verified 2026-10-10: `settled_cash_by_currency` JPY 20,000, `available_funds` JPY 20,000, `net_liquidation` JPY 20,000, `segment_trading_type: STKCASH` (Cash account, confirmed). This will need re-verification fresh on the pilot day per the section below; today's figures are a reference point, not pilot-day evidence.
- [x] Appropriate currency/cash is available for the intended instrument, with a buffer for commissions/fees. JPY 20,000 available against the bound 9432.T × 100 × ¥172.7 = ¥17,270 notional, leaving a ¥2,730 buffer; pilot cap is ¥50,000.
- [ ] Trading permission for the intended market/product is approved. (Established via IBKR Client Portal screen confirmation earlier in this project's history; not re-verified by an API call today.)
- [ ] Any mandatory market registration is complete (for Japanese cash equities, verify JASDEC eligibility/registration as applicable to the account). (Established earlier in this project's history; not re-verified today.)
- [x] TWS or IB Gateway can be launched in **Live** mode. Confirmed 2026-10-10: TWS running with `tradingMode=l` (Live), connected successfully on port 7496.
- [x] API **Read-Only remains ON** throughout preparation. Operator-confirmed 2026-10-10 (TWS API Settings checkbox). Not independently verifiable via the API itself — IBKR does not expose this as a queryable field — so this remains an operator-attested, not Claude-Code-verified, item; re-confirm visually if TWS is restarted or reconfigured before the pilot.
- [x] Windows runtime environment: Python 3.13 is installed **for all users** (HKLM-registered, under an admin-only-writable `%ProgramFiles%` root) — the Windows Phase 3 entrypoint (`live_pilot_operational_once.ps1`) deliberately fails closed on a per-user-only install, since that install location is fully writable by the operator's own account and cannot provide the same tamper-resistance POSIX's root-owned `/usr/bin/python3` does. Verified and resolved on the operator's machine 2026-10-10 (see `COMPLETION_ROADMAP.md`'s "Current state" section for detail); re-verify after any Windows reinstall or new machine.
- [ ] PC/network/power/runtime environment is available for the intended session.
- [ ] No planned software update/reboot should interrupt the execution window.
- [ ] The intended market is scheduled to be open on the pilot date.

## Must be re-verified fresh on the pilot day

Do not rely on yesterday's `latest.json` or screenshots for these — every item stays unchecked here regardless of any prior reference run, including the 2026-10-10 one noted below, which is not pilot-day evidence:

- [ ] audited/pinned Git commit and safety-critical working tree;
- [ ] correct Live endpoint/session/account fingerprint;
- [ ] available funds and permissions (reference only, not pilot-day evidence: confirmed JPY 20,000 available/settled on 2026-10-10);
- [ ] exact target position;
- [ ] zero unexpected Live open orders (reference only: `OPEN ORDER COUNT: 0` via `ibkr_live_all_open_orders.py` on 2026-10-10);
- [ ] fresh quote and FX evidence as applicable (no FX conversion needed — account base currency and trade currency are both JPY);
- [ ] exact LIMIT price × quantity × FX-derived JPY notional under the pilot cap;
- [ ] market/session is currently open and allowed by the guard;
- [ ] emergency-stop latch is clear immediately before any future sender (reference only: confirmed clear via `live_pilot_stop_is_active()` on 2026-10-10);
- [ ] one-shot authorization is fresh, exact, unused, and bound to account/instrument/quantity/price/source;
- [ ] Paper monitor/safety state remains healthy where required;
- [ ] operator has explicitly approved the exact single real-cash pilot action.

## Actions that must NOT be done early

- [ ] Do **not** turn API Read-Only OFF during preparation.
- [ ] Do **not** enable ordinary/unbounded Live strategy deployment.
- [ ] Do **not** create a second authorization as a workaround after timeout/disconnect/UNKNOWN.
- [ ] Do **not** retry, cancel, modify, flatten, or close automatically while broker state is UNKNOWN.

## Current 2026-10-10 calendar note

- JPX: 2026-10-10 (Sat) / 10-11 (Sun) / 10-12 (Mon, national holiday — Sports Day) are non-trading days. `9432.T` is not executable until 2026-10-13 (Tue), subject to every other gate being GREEN that day.

This is execution-mechanics preparation only, not an investment recommendation.
