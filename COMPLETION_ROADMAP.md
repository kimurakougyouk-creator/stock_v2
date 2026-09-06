# stock_v2 — Reverse-Engineered Completion Roadmap

Last verified: 2026-09-06 JST

This document defines what **completion** means and works backward from that end state. It is intentionally stricter than a percentage estimate. A phase is complete only when its exit evidence exists; a high percentage never substitutes for a missing mandatory gate.

## 0. Completion definition — freeze the finish line

### V1 production-complete means all of the following are true

1. The already-proven exact Paper scope remains safe and observable.
2. One tightly bounded real-cash operational pilot has completed with broker evidence and full reconciliation.
3. The natural strategy has fee-aware, account-currency net-performance evidence; gross-before-fees evidence alone is insufficient.
4. A versioned, testable strategy-promotion policy exists. Normal Live strategy deployment cannot be enabled merely because one or a few trades were positive.
5. A controlled Live strategy path exists only for explicitly approved scope, with shared risk gates, duplicate prevention, emergency stop, market/session guard, daily limits, account binding, and fail-closed recovery.
6. Live runtime monitoring, reconciliation, accounting, commission evidence, drawdown/risk state and alerts are operational and restart-safe.
7. Release/source control prevents unreviewed or untested code from silently becoming the approved Live build; `main` protection or an equivalently strong pinned-release control is in force.
8. Runbooks exist for normal operation, restart, rejected order, partial fill, timeout/disconnect/UNKNOWN, reconciliation mismatch, emergency stop and rollback to Read-Only.
9. Final acceptance is backed by GitHub diff/CI evidence plus actual broker/runtime evidence; no completion claim is based on chat memory or an AI's self-review.

### Not required for V1 completion

Broad multi-broker/multi-market expansion is **post-V1** unless separately promoted with equivalent evidence. Futures/options/FX/crypto or additional brokers must not be generalized from the exact scope already proven.

---

# Reverse order: from final V1 acceptance back to today

## PHASE 7 — Final production acceptance

### Entry criteria
- Phases 1 through 6 below are all VERIFIED.
- No unresolved safety-critical issue is open.
- Exact approved release SHA/tag is pinned.

### AI work
- Audit the full final diff from the last accepted baseline.
- Verify CI, secret scan, tests and release metadata.
- Verify normal Live enable is explicit, bounded and reversible.
- Verify every safety-critical runtime path has tests.
- Verify operator and recovery runbooks against current code.
- Verify no stale handoff/document contradicts current `main`.

### User-only work
- Only explicit approval of the exact production scope and risk limits after the evidence package is presented.

### Required evidence
- Approved release SHA/tag.
- Passing CI on that exact source.
- Live soak/monitoring evidence from Phase 6.
- Fee-aware strategy promotion evidence from Phase 5.
- Broker reconciliation evidence with no unexplained orders/positions/cash deltas.
- Emergency-stop test evidence.

### Exit criterion
`V1_PRODUCTION_COMPLETE = TRUE` can be stated only here.

---

## PHASE 6 — Controlled Live strategy soak and operational hardening

This is **not** the one-time pilot. It begins only after the strategy-promotion gate is passed and a separately bounded Live strategy path has been approved.

### Work
- Start with the smallest explicitly approved Live scope and risk envelope.
- Observe normal strategy-generated decisions without forcing BUY/SELL signals.
- Persist each intent, order, execution, `exec_id`, commission, FX evidence, position, cash/account state and reconciliation result.
- Exercise restart/reconnect recovery without generating duplicate sends.
- Prove daily loss limit, daily BUY-count limit, position/allocation limits, market-session guard and emergency stop in the integrated Live path.
- Monitor alert delivery and stale-evidence handling.
- Compare broker truth against local truth after every material lifecycle transition.

### Failure handling
- Timeout/disconnect/UNKNOWN: no resend; read-only reconciliation first.
- Rejection: no automatic retry under a new intent.
- Partial fill: preserve partial state; do not manufacture a second order to reach target quantity.
- Reconciliation mismatch: freeze new Live entries until explained.
- Safety-critical alert: fail closed and preserve evidence.

### Exit evidence
- Bounded Live strategy operation over a predeclared observation period with no unexplained duplicate/order/accounting/reconciliation defect.
- All discovered safety defects fixed, tested and re-audited.

---

## PHASE 5 — Net strategy evidence and promotion policy

### Current verified gap
Current `strategy_profitability_evidence.py` explicitly reports gross-before-fees results and states that durable commission/fee evidence is not yet joined to every strategy execution. `net_profitability_proven` and `live_ready` therefore remain false by design.

### Required engineering
1. Build a durable historical commission ledger keyed by broker `exec_id`.
2. Join every natural strategy execution to exactly one fee record; missing/conflicting fee evidence fails closed.
3. Preserve fee currency and convert to account currency only with traceable FX evidence where required.
4. Make the realized-trade accounting path net-of-fees.
5. Persist net PnL, win rate, profit factor, maximum drawdown and trade-level audit records.
6. Add restart/replay/idempotency tests so repeated broker callbacks never double-count fees or fills.
7. Add tests for multiple executions/partial fills, delayed commission callbacks, missing FX, malformed evidence and duplicate `exec_id`.

### Strategy-promotion policy — currently missing as a formal gate
A positive result from one or a few natural closed trades is not sufficient evidence for normal Live deployment. Before Phase 6, implement a **versioned promotion policy** that explicitly defines:
- minimum natural closed-trade evidence required;
- net PnL requirement after commissions/fees;
- maximum permitted drawdown;
- acceptable accounting/evidence health;
- whether win rate/profit factor thresholds are required;
- maximum evidence age and minimum observation span;
- exact strategy/source version to which the evidence applies.

The numeric thresholds must be deliberate and encoded/tested; this roadmap does not invent statistical certainty from an arbitrary number. Until that policy exists and passes, ordinary Live strategy deployment remains BLOCKED.

### Exit criterion
A reproducible report proves the exact strategy/source version passes the encoded net-performance promotion policy. This does **not** retroactively change the one-time pilot into strategy approval.

---

## PHASE 4 — Post-pilot completion and reconciliation

A real-cash send is not a completed pilot. The pilot is complete only after broker truth is reconciled.

### Full-fill path
Require:
- exact execution ID(s), order ID and perm ID;
- exact symbol/side/quantity and actual execution price;
- exact commission evidence joined by `exec_id`;
- final position equals expected position;
- zero unexpected Live open orders;
- account/cash/risk evidence is consistent with the fill;
- local order/fill record agrees with broker evidence;
- alert/result is persisted;
- pilot authorization/attempt journal shows exactly one send attempt.

### Rejected path
- Persist rejection/error evidence.
- Mark pilot attempt consumed.
- Do not automatically retry.
- Diagnose before a separately authorized future attempt.

### Partial-fill path
- Persist every execution and commission.
- Keep the resulting partial position as broker truth.
- Do not automatically send the remainder.
- Reconcile first; any further write action is a new explicit decision.

### Timeout/disconnect/UNKNOWN path
- Irreversible send-attempt marker remains authoritative.
- No resend, automatic cancel, modify, flatten or close.
- Recover using read-only open-order/execution/position/account evidence.
- State remains UNKNOWN until broker evidence resolves it.

### Exit criterion
Pilot status is one of `COMPLETE_RECONCILED`, `REJECTED_RECONCILED`, `PARTIAL_RECONCILED`, or another explicit reconciled terminal outcome. UNKNOWN is never completion.

---

## PHASE 3 — First bounded real-cash operational pilot

### Purpose
Validate execution mechanics only. It is not a recommendation to buy an instrument and not approval for normal Live strategy deployment.

### Hard boundaries
- Exact one-shot authorization.
- Exact instrument/side/quantity/LIMIT price/account/source binding.
- JPY notional cap enforced from actual evidence, not caller-supplied estimates.
- Current pilot ceiling: JPY 50,000.
- No unsupported ticker/quantity combination.
- No automatic retry after any uncertain state.

### Final pre-send sequence
1. Start from exact audited/pinned source.
2. Keep API Read-Only ON while collecting fresh evidence.
3. In one final Live session, obtain raw managed account ID ephemerally and verify its SHA-256 fingerprint equals the pinned account fingerprint.
4. Re-check account readiness/funds/permissions, target position, all open orders, market/session, fresh quote/FX, exact LIMIT notional, Paper-monitor safety state and source/PIN.
5. Re-check emergency-stop latch at the last possible point inside the actual sender.
6. Consume the exact one-shot authorization and create the irreversible send-attempt marker **before** broker transport.
7. Only after every gate is green may the operator be asked for the separate consequential action: broker-side Read-Only removal / exact pilot approval as applicable.
8. Transmit at most once.
9. Immediately enter Phase 4 reconciliation; never infer success from timeout or silence.

### Current 2026-09-07 calendar constraint
- NYSE regular session is closed for Labor Day; AAPL/SPY are not regular-session pilot candidates on 2026-09-07.
- JPX is scheduled open; within the already-bounded scope, `9432.T` 100 shares is the calendar-compatible execution-mechanics candidate **only if every other gate is green**.

### Current blockers before any send
- Same-final-session raw account ID must be bound to pinned fingerprint in the final sender.
- Emergency stop must be checked at the last possible point inside that sender.
- The audited single-send Live transport/orchestrator must be implemented and independently reviewed.
- The Phase 4 completion judge must be fully integrated.
- Actual Chromebook/runtime and fresh Live account evidence must be verified on the execution day.
- The user must explicitly authorize the exact real-cash action; a date or general instruction to continue is not authorization.

### Exit criterion
Exactly one bounded send attempt has occurred under the approved source and authorization, then Phase 4 determines the reconciled outcome.

---

## PHASE 2 — Execution-day GO/NO-GO evidence

This phase is deliberately fresh. Yesterday's screenshot or `latest.json` is not enough.

### AI/automated checks
- exact approved SHA/source PIN;
- safety-critical working-tree cleanliness while preserving known runtime artifacts;
- existing Paper monitoring still intact/healthy;
- correct Live endpoint and account fingerprint;
- fresh account readiness, net liquidation, available funds and cash;
- intended-market permission evidence where obtainable;
- exact target position;
- zero unexpected Live open orders;
- fresh quote and FX as applicable;
- exact LIMIT × quantity × FX JPY notional <= pilot cap;
- market/session currently allowed;
- evidence freshness/skew limits;
- emergency stop clear;
- one-shot authorization exact/fresh/unused;
- no prior irreversible attempt marker for that authorization.

### User-only actions, one at a time when unavoidable
- Live broker authentication if required.
- Any broker UI confirmation not exposed to AI/tools.
- Final consequential approval only after AI returns GO.

### GO rule
Every mandatory item must be GREEN. One red/unknown item => NO-GO. Completion percentages do not override this rule.

---

## PHASE 1 — Pre-day preparation / today

This phase prevents non-code prerequisites from being discovered minutes before the market opens.

### AI work — complete before bothering the user
- Continue implementation/audit of the remaining Phase 3/4 sender and completion blockers.
- Verify open PRs/issues and CI after each change.
- Keep all preparation paths read-only.
- Verify the next market calendar and exact bounded candidate set.
- Prepare exact execution-day commands/runbook in advance.
- Prepare rollback/UNKNOWN procedure in advance.
- Keep documentation synchronized with actual `main`.

### Operator prerequisites that must be prepared/verified before pilot day where possible
- correct IBKR Live account login works;
- MFA/passkey/mobile authentication works;
- funds have actually arrived and are available/settled, not merely transfer-instructed;
- appropriate cash/currency plus fee buffer is available;
- intended market/product trading permission is approved;
- mandatory market registration is complete (including JASDEC eligibility/registration as applicable for Japanese cash equities);
- TWS or IB Gateway can launch in Live mode;
- Chromebook, network and power are available;
- no planned reboot/update will interrupt the window;
- market is scheduled open;
- **API Read-Only remains ON throughout preparation**.

### Interaction rule
The AI does not dump this entire checklist on the user as homework. It first verifies everything available through GitHub/tools, then asks for exactly one unavoidable operator action at a time, records the result, and resumes autonomous work.

### Exit criterion
All pre-day prerequisites that can be known in advance are VERIFIED; execution-day-only items are explicitly marked as such; no hidden operator dependency remains.

---

# Cross-cutting gates that must be closed before V1 production completion

## A. Git/release integrity

Current known process risk: `main` has not been protected by required status checks. Before normal Live strategy deployment, establish one of:
- GitHub branch/ruleset protection requiring PR + passing CI for `main`; preferably this; or
- an equivalently strong release process where Live can execute only an explicitly pinned, reviewed, passing release SHA/tag and unapproved `main` movement cannot change the running build.

The one-time pilot's source/PIN gate reduces but does not erase this production-process risk.

## B. Durable evidence retention

Critical evidence must survive restart and be append-safe/idempotent:
- order intent/authorization;
- irreversible send-attempt marker;
- broker order/execution IDs;
- commissions keyed by `exec_id`;
- FX evidence used for account-currency accounting;
- positions/account snapshots;
- reconciliation outcomes;
- alerts and safety-block reasons;
- strategy/source version.

## C. Recovery/runbook coverage

Before V1 acceptance, documented and tested procedures must exist for:
- Live login/API unavailable;
- rejected order;
- partial fill;
- timeout/disconnect/UNKNOWN;
- stale quote/FX/account evidence;
- unexpected open order;
- unexpected position;
- account/fingerprint mismatch;
- commission missing/conflicting;
- accounting/reconciliation mismatch;
- emergency stop;
- restart after crash;
- rollback to Read-Only / Paper-only operation.

## D. Scope control

Every expansion — new ticker quantity, market, broker, derivative, crypto, wider notional, unattended Live write capability — is a new promotion decision with its own evidence. V1 completion cannot silently widen scope.

---

# Current state at 2026-09-06

## DONE / VERIFIED
- Exact bounded Paper milestone.
- Strict read-only unattended Paper monitoring foundation.
- Live read-only account/open-order/FX evidence.
- Freshness/TOCTOU and exact-notional binding.
- One-shot authorization and emergency-stop primitives.
- Same-run evidence bundle.
- Audited-source/PIN gate.
- Crash-safe UNKNOWN/no-resend attempt journal.
- Read-only Live post-fill execution/commission collector.
- Durable PM/runbook/operator-prerequisite documents.

## TODO before first Live send
1. Same-final-session raw account-ID binding inside final sender.
2. Last-moment emergency-stop check inside final sender.
3. Single-send Live transport/orchestrator implementation + independent audit.
4. Integrated post-pilot completion/reconciliation judge.
5. Execution-day exact-source and fresh Live runtime evidence.
6. One-at-a-time unavoidable operator prerequisites/approval.

## TODO after first pilot but before normal Live strategy deployment
1. Durable fee/commission join for all natural strategy executions.
2. Net-of-fees account-currency performance evidence.
3. Explicit versioned strategy-promotion policy and tests.
4. Controlled Live strategy integration with shared risk gates.
5. Branch/release protection suitable for production.
6. Live monitoring/recovery soak.
7. Final production acceptance audit.

---

# Critical path — shortest safe route to V1

`remaining sender/completion blockers`
→ `pre-day operator prerequisites`
→ `fresh execution-day read-only GO/NO-GO`
→ `explicit one-shot operator approval`
→ `one bounded Live send attempt`
→ `post-pilot reconciliation`
→ `durable commission/net-profitability path`
→ `versioned strategy-promotion gate`
→ `bounded Live strategy integration`
→ `production release protection + soak`
→ `final V1 acceptance`

No feature expansion is allowed to jump ahead of this critical path unless it closes a concrete blocker.
