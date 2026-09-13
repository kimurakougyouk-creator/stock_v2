# Codex PR #271/#273/#274 safety fix notes

This branch is a corrective safety branch created from `main` at `c18a8778fb96755509d08e23d2480e0b07f9daf1` after the independent Codex reviews of merged PRs #271, #273, and #274 found 17 unresolved items.

Targeted findings:

- pilot-wide immutable single-send marker; changing `intent_id` must never permit a second transport attempt
- directory-durable attempt/authorization mutations
- exact same-run account fingerprint binding
- advancing clock at each final-send safety boundary
- reject inactive/non-accepted `openOrder` acknowledgement states
- emergency stop read immediately before `placeOrder`
- account-bound Live open-order evidence
- strict Paper `HEALTHY` broker evidence
- exact Live report schema and explicit false transport flags
- exact empty open-order count plus empty order rows
- authoritative immutable attempt marker required for completion
- expected instrument currency required for executions and commissions
- global `exec_id` uniqueness across the complete execution snapshot
- exact Decimal fill quantity equality
- finite aggregate VWAP/commission/cash arithmetic
- failure-safe completion/alert persistence that invalidates stale success before replacing the report

No broker connection, Live unlock, Read-Only removal, or real-money order is performed by this corrective branch or its CI.
