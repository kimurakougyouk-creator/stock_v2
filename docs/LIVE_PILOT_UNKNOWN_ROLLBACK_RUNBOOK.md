# Live Pilot UNKNOWN / Rollback Runbook

Status: HUMAN PROCEDURE ONLY. Live execution remains NO-GO unless separately and explicitly authorized.

## Purpose

This runbook defines what a human operator must do when a future Live pilot reaches an UNKNOWN, timeout, ambiguous acknowledgement, source-cutover uncertainty, or other state where the broker outcome cannot be proven immediately.

The procedure is fail-closed. UNKNOWN never means "try again."

## Absolute rules

- Do not resend the order.
- Do not cancel, modify, flatten, or close automatically.
- Do not submit a What-If request as a substitute for reconciliation.
- Do not switch from Paper to Live or enable Live Trading.
- Do not change source revision, branch, or runtime PIN while an order state is unresolved.
- Do not infer "not filled" from a missing open-order row.
- Do not infer "filled" from elapsed time.
- Preserve all available evidence before any recovery decision.

## When to declare UNKNOWN

Treat the pilot as UNKNOWN when any of the following occurs:

- transport timeout after the irreversible send-attempt marker was written;
- broker connection drops before a definitive accepted/rejected/fill result is proven;
- order acknowledgement is ambiguous or conflicting;
- order_id / perm_id / exec_id evidence does not reconcile;
- account fingerprint, endpoint, source SHA, or evidence freshness no longer matches the approved pilot;
- post-fill evidence is incomplete or contradictory.

## Human recovery procedure

1. **Stop.**
   - Do not press any button that sends, retries, cancels, modifies, closes, or flattens an order.
   - Keep Live execution blocked.

2. **Preserve the exact runtime identity.**
   - Record the exact Git commit SHA that was running.
   - Do not pull, checkout, reset, or update the repository.
   - Preserve the one-shot authorization record and send journal.

3. **Collect read-only broker evidence only.**
   - Confirm the Live account fingerprint.
   - Read current positions.
   - Read all open orders.
   - Read executions and their exec_id values.
   - Read matching commission reports.
   - Preserve endpoint port and timestamps.
   - No broker mutation is allowed during this step.

4. **Reconcile the specific pilot identity.**
   Match only evidence bound to the approved:
   - account fingerprint;
   - ticker;
   - side;
   - quantity;
   - order_id;
   - perm_id;
   - exec_id;
   - source SHA.

   Evidence from another account, order, instrument, or stale run must not be substituted.

5. **Classify the state.**
   - **PROVEN_FILLED:** complete execution evidence proves the full intended quantity filled and post-fill state reconciles.
   - **PARTIAL_RECONCILED:** broker evidence proves that only part of the intended quantity filled and the remainder is definitively cancelled/rejected/inactive. Preserve the real partial position exactly as observed. Do not send the unfilled remainder, do not "top up" to the intended quantity, and do not flatten merely to restore the planned size.
   - **PROVEN_REJECTED/CANCELLED:** definitive broker evidence proves zero quantity filled, no matching order remains active, and no unexpected position exists.
   - **OPEN/PENDING:** a matching broker order is still active; keep the pilot blocked.
   - **UNKNOWN:** evidence is still incomplete or contradictory.

6. **If still UNKNOWN, remain stopped.**
   - No resend.
   - No automatic or manual "cleanup" order merely to force the account flat.
   - Keep collecting read-only evidence.
   - If broker evidence cannot resolve the ambiguity, use written broker support and preserve the response as evidence.

7. **Rollback source only after broker state is resolved.**
   A source rollback/cutover may be considered only when:
   - the broker/order state is no longer UNKNOWN;
   - read-only monitoring is healthy;
   - the target rollback SHA is independently approved;
   - the source-cutover audit proves the exact SHA and clean audited paths.

   Source rollback itself does not authorize any order.

8. **Require a new authorization for any future Live send.**
   Resolution of an UNKNOWN state never restores or reuses the consumed one-shot authorization.
   A future pilot requires a fresh, separately approved authorization and all readiness gates must be re-proven.

## Evidence to retain

Retain, without altering:

- exact source SHA;
- readiness report;
- same-run preflight report;
- one-shot authorization record;
- irreversible send-attempt journal;
- order_id and perm_id;
- Live account fingerprint;
- endpoint port;
- open-order snapshot;
- position snapshot;
- execution rows including exec_id;
- commission evidence;
- post-fill reconciliation report;
- timestamps and broker errors.

## Completion condition

This runbook is complete only when the operator can determine one of the following from explicit evidence:

- the intended order fully filled and the post-fill state reconciles;
- the order partially filled, the remainder is terminal/inactive, and the actual partial position is reconciled as **PARTIAL_RECONCILED** without resending the remainder;
- the intended order was definitively rejected/cancelled with zero fill and no unexpected position exists;
- the order remains open/pending and requires continued read-only observation;
- the state remains UNKNOWN, in which case Live execution stays blocked.

No step in this document authorizes Live Trading or any broker write.
