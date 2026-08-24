# Project State

Last updated: 2026-08-24

This file is the concise, evidence-based handoff ledger for AI agents. Update it after meaningful verified progress. Do not replace verified facts with guesses.

## Current phase
Final IBKR Paper integrated runtime validation plus repository-only multi-asset foundation work. The previously pending SPY one-share Paper close lifecycle has now been observed end-to-end on the user's local IBKR Paper environment. The later AAPL broker/local mismatch has also been resolved by a dedicated, fail-closed Paper-only flatten reset with real broker execution evidence and no Live order. The post-reset normal read-only checkpoint passed, and a subsequent bounded three-cycle read-only soak also passed consecutively with no order transmission, no reconciliation errors, no legacy blocker, and Paper E2E readiness remaining true. A controlled Japan-stock Paper round trip for 9432/TSEJ/JPY is now also complete: the known 100-share BUY was closed by a dedicated 100-share flatten-only SELL, broker and local positions both reached zero, and the confirmed SELL was reconciled into durable accounting. Repository work continues on issue #56 without enabling unsupported asset classes or Live Trading.

## Verified repository state
- Repository: `kimurakougyouk-creator/stock_v2`
- Branch: `main`
- PRs #114-#118: account-currency accounting, fail-closed verified Paper preflight, dedicated verified IBKR Paper execution path, one-command operator checkpoint, and account-timezone handling.
- PR #135: read-only broker execution-history evidence plus broker/local position reconciliation guard.
- PR #136: deterministic broker execution reconciliation into the durable local Paper ledger.
- PR #138: `ibkr_auto.sh` reconciles broker-confirmed executions before the fail-closed checkpoint.
- PR #139: broker historical MIDPOINT FX evidence can be anchored to confirmed execution time for recovery accounting.
- PR #140: broker execution/order identity persists; reconciliation deduplicates by broker `exec_id` across application and recovery intents.
- PR #141: dedicated fail-closed, position-reducing SPY Overnight Paper SELL path with separate SELL what-if and explicit confirmation gate.
- PR #145: session-aware one-command SPY Paper close cycle chooses only an already-supported close route and never opens exposure.
- PRs #146-#149: read-only multi-asset discovery plus fail-closed futures/options/crypto Contract foundations. No unsupported product trading capability was promoted.
- PR #151: read-only auto-recovery hook ordering is regression-tested.
- PR #152: narrow fail-closed tolerance for broker average-cost vs execution-price recovery evidence.
- PR #153: paired closed-SPY accounting safely reconstructs the exact one-share round trip without weakening broker-order gates.
- PR #154: regression coverage ensures the closed SPY round trip no longer leaves its own stale-FX blocker.
- PR #155: user-level read-only IBKR autopilot repeatedly fast-forwards `main` and runs only `ibkr_auto.sh`; it never calls close-cycle scripts or enables Paper/Live order approval.
- PR #165: fail-closed stale legacy fill retirement foundation plus safe one-command Paper E2E wrapper.
- PR #166: read-only IBKR reconciliation evidence audit correlating broker positions, execution snapshots, and local Paper evidence.
- PR #167: read-only AAPL completed-order evidence audit; unavailable completed-order history remains unknown rather than inferred.
- PR #168: dedicated fail-closed AAPL Paper three-share flatten reset, reconciliation pause/exclusion registry, targeted legacy retirement, and explicit human confirmation gate.
- PR #169: dedicated AAPL reset wrapper explicitly enables IBKR Paper while leaving Live Trading locked.
- PR #170: AAPL reset Paper opt-in is scoped only to the reset process, preserving default-safe pytest behavior.
- PR #173: bounded read-only soak wrapper repeatedly runs the normal non-order IBKR audit path; no Paper/Live approval is supplied.
- PR #175: dedicated fail-closed 9432/TSEJ/JPY 100-share Paper flat-close path with exact broker/local position agreement, known BUY execution identity, broker ContractDetails/lot evidence, liquid-session gate, SELL what-if, no-open-order gate, exact human confirmation, no automatic resend, broker-flat proof, and durable local reconciliation.
- Live Trading remains prohibited.

## Verified real IBKR Paper evidence
- Controlled SPY Paper BUY: quantity `1`, terminal `Filled`, average fill price `765.45 USD`, order id `3`, broker exec id `00012ec5.6ab91096.01.01`.
- The prior SPY BUY execution was recovered into the durable local ledger after exact broker/local safety checks.
- Controlled SPY position-reducing Overnight Paper SELL: quantity `1`, fill price `766.34 USD`, exchange `OVERNIGHT`, order id `7`, broker exec id `0000e511.6a8b602c.01.01`.
- After the SELL, the broker Paper account reported `SPY quantity = 0` and the local confirmed position also reported `SPY quantity = 0`.
- Latest observed USD/JPY evidence was available from broker market data and the post-close checkpoint reported `FX READY=True`.
- Post-close accounting reported `ACCOUNTING SAFE=True`, `REALIZED PNL=141.39875 JPY`, `UNREALIZED PNL=0.0`, `MAX DRAWDOWN=0.0` for the trusted accounting set.
- A separate broker execution was observed for `9432` BUY quantity `100` at `166.5 JPY`, exchange `TSEJ`, order id `6`, exec id `0000f0df.6a8b7328.01.01`; reconciliation treated it idempotently on the subsequent run.
- Controlled 9432/TSEJ/JPY Paper flatten SELL on 2026-08-24: broker and local quantities were both exactly `100` before send; broker market price `166.53642275 JPY`; auto limit price `164.8 JPY`; order id `9`; terminal fill quantity `100`; average fill price `166.5 JPY`; broker exec id `0000f0df.6a8bb66c.01.01`.
- The 9432 close reported `BROKER 9432 FLAT AFTER=True`, `LOCAL 9432 FLAT AFTER=True`, and `RECONCILED COUNT=1`, completing the controlled Japan-stock Paper round trip without a Live order.
- The 9432 close was attempted only after `PLAN READY=True`, exact 100-share broker/local agreement, the known broker-backed BUY identity, broker lot/Contract evidence, an open TSEJ liquid session, a successful SELL what-if, and no current 9432 open order.
- The local run completed the full test suite immediately before the 9432 close with `1148 passed in 22.86s`.
- Two background `ibapi.client.run` threads raised `TypeError: '>=' not supported between instances of 'NoneType' and 'int'` during connection teardown/failed-attempt handling, but the controlled close itself still completed with terminal full fill, broker-flat proof, local-flat proof, durable reconciliation, and `REAL LIVE ORDER SENT=False`. Treat this thread exception as a robustness defect to fix, not as evidence that the completed close failed.
- Read-only AAPL evidence audit observed `broker AAPL quantity = 3` while trusted local AAPL quantity was `1`; the gap was `2` and no AAPL executions were available in the then-current execution snapshot.
- AAPL completed-order audit later returned `completed count = 0` while broker still held `3` shares; this was treated as unavailable history, not as proof that no prior orders existed.
- Controlled AAPL Paper flatten reset: exact broker quantity `3`, local trusted quantity `1`, broker market price `309.6000061`, auto limit price `306.5`, order id `8`, terminal fill quantity `3`, average fill price `309.66`, broker exec id `0000e511.6a8b66fa.01.01`.
- The AAPL reset execution was stored in the reconciliation-exclusion registry so it is not misinterpreted as an ordinary accounting SELL against an unproven legacy cost basis.
- After the AAPL reset, broker reported `AAPL quantity = 0`; the exact identity-less legacy AAPL row was then targeted for retirement/quarantine only after broker-flat proof.
- AAPL reset completed with `RECONCILIATION_PAUSED=False` at the end, confirming the temporary safety pause was released after the terminal outcome.
- Post-reset normal read-only reconciliation observed three current broker executions (`9432` BUY, `SPY` SELL, `AAPL` reset SELL), reconciled `0`, skipped `3`, with `ERRORS=[]`; the reset execution therefore remained excluded/idempotent rather than re-entering trusted accounting.
- Post-reset operator checkpoint reported `LEGACY EVIDENCE BLOCKERS=[]`, `SPY CONFIRMED HELD QTY=0`, `BROKER SPY HELD QTY=0`, `ACCOUNTING SAFE=True`, `PREFLIGHT ALLOWED=True`, `PREFLIGHT ERROR=None`, and `READY FOR PAPER E2E REVIEW=True`.
- Post-reset accounting remained `CONFIRMED FILLS=3`, `ENDING EQUITY=1000141.39875 JPY`, `REALIZED PNL=141.39875 JPY`, `UNREALIZED PNL=0.0`, `MAX DRAWDOWN=0.0`, confirming the AAPL reset was not injected into trusted PnL.
- Post-reset broker account was ready in JPY, with one broker position remaining in the account; AAPL and SPY were both flat in the verified reset/checkpoint evidence. That remaining position was subsequently identified as the controlled 9432/TSEJ/JPY 100-share holding and was later closed to broker/local flat as described above.
- Post-reset multi-asset read-only audit resolved global stock `9432/TSEJ/JPY` and FX `USD/JPY@IDEALPRO`, with `CORE_RESOLVED=True`, `CORE_CONTRACTS_READY=True`, and `ORDER SENT=False`.
- Bounded read-only soak on 2026-08-24 completed `3/3` consecutive cycles successfully. Each cycle detected the Paper endpoint on port `4002`, observed the same three broker executions, reported `RECONCILED COUNT=0`, `ERRORS=[]`, `LEGACY EVIDENCE BLOCKERS=[]`, `ACCOUNTING SAFE=True`, `PREFLIGHT ALLOWED=True`, `READY FOR PAPER E2E REVIEW=True`, and `CORE_CONTRACTS READY=True`.
- Across all three soak cycles, trusted accounting remained stable at `CONFIRMED FILLS=3`, `ENDING EQUITY=1000141.39875 JPY`, `REALIZED PNL=141.39875 JPY`, `UNREALIZED PNL=0.0`, and `MAX DRAWDOWN=0.0`.
- The soak ended with `SOAK RESULT: PASS (3 consecutive read-only cycles)` and `REAL ORDER SENT BY SOAK WRAPPER: False`.
- No Live order was sent by any verified flow above.

## Current verified Paper execution model
- Live Trading remains disabled/unimplemented in the active path.
- New BUY exposure requires broker/local position agreement, verified quantity, account-currency preflight, risk gates, and broker evidence.
- Existing broker executions are reconciled into local durable state before the normal operator checkpoint.
- Broker `exec_id` is persisted and used for cross-process deduplication so one confirmed execution cannot be counted twice under different local intent ids.
- Cross-currency recovery uses explicit evidence and fails closed when historical FX cannot be established; it is never guessed globally.
- The exact closed one-share SPY round trip may use the explicit SELL FX only for its uniquely matched BUY/SELL accounting pair, with distinct broker execution identities.
- Protective/position-reducing SELL preflight intentionally does not require a fresh FX quote merely to reduce an already-confirmed position.
- Timeout or uncertain order state is never automatically resent.
- Read-only checkpoint repetition is automated locally by `ibkr_readonly_autopilot.sh`; order-transmitting scripts remain outside that autopilot.
- Legacy-position reset executions with unproven opening basis are excluded from ordinary accounting reconciliation and require broker-flat proof before targeted legacy retirement.
- The controlled 9432 close uses a separate exact-confirmation flatten-only route and records the ordinary broker-backed SELL into durable accounting only after a confirmed full fill and broker-flat proof.
- After the verified AAPL reset, normal checkpoint, three-cycle soak, and 9432 close, no remaining legacy evidence blocker is evidenced in the verified flows; normal verified Paper preflight readiness evidence exists, but this is not permission to transmit unattended orders.

## Multi-asset issue #56 boundary
- US stock and US ETF Paper foundations have real broker evidence. The SPY Overnight close route and the dedicated AAPL flatten reset both have real Paper SELL evidence.
- Global-stock Paper evidence now also includes a complete controlled Japan-stock 9432/TSEJ/JPY round trip: broker-backed BUY 100 and broker-backed flatten SELL 100, with broker/local flat afterward. This verifies the specifically controlled 9432/TSEJ/JPY path, not arbitrary global-stock symbols or venues.
- Read-only runtime evidence confirms contract resolution for `9432/TSEJ/JPY` and `USD/JPY@IDEALPRO`; this still does not promote arbitrary global-stock or FX Paper order transmission.
- Futures, options and crypto remain unverified trading capabilities: no Paper quantity is assigned, no new exposure order path is enabled, and account/region/product permission is not inferred.
- Crypto venue/currency constraints are represented explicitly; account/residence availability remains a separate evidence gate.
- Promotion to a verified capability still requires product-specific safety checks, no-transmit evidence and real Paper E2E evidence.

## Current blockers and their meaning
- The SPY broker/local position mismatch is resolved: both sides are zero after the verified close.
- The earlier SPY missing-historical-FX blocker is resolved for the uniquely matched closed round trip by fail-closed paired accounting.
- The prior AAPL broker/local mismatch is resolved: the dedicated Paper-only reset filled exactly `3` AAPL shares, broker reported flat afterward, and the exact old identity-less AAPL row was retired/quarantined only after broker-flat proof.
- The controlled 9432 broker/local position is now also resolved to zero: the dedicated Paper-only close filled exactly `100` shares and both broker/local states proved flat afterward.
- The post-reset normal operator checkpoint and subsequent three-cycle soak report `LEGACY EVIDENCE BLOCKERS=[]` and `PREFLIGHT ALLOWED=True`; the prior AAPL legacy blocker no longer blocks normal verified Paper readiness.
- No broker/local AAPL, SPY, or 9432 mismatch is currently evidenced by the verified post-close results.
- One non-ordering robustness defect remains visible: rare failed/teardown connection threads in `ibapi.client.run` can raise a `serverVersion() is None` TypeError. This did not invalidate the successful 9432 close, but it should be contained so routine endpoint probing never emits uncaught background-thread tracebacks.
- Remaining work is final evidence-based completion auditing plus issue #56 product-by-product verification. No additional Paper order should be sent merely to re-prove already verified fills.

## Accounting and reporting
- Only accounting-effective records are included; IBKR Paper requires confirmed `FILLED` evidence.
- Confirmed fills are idempotent by local `order_intent_id` and broker execution identity.
- Cross-currency confirmed fills require explicit per-fill FX evidence for account-currency accounting, except the narrowly verified closed-SPY pairing rule described above.
- The verified SPY round trip reconstructs realized PnL and equity safely from broker-backed evidence.
- The AAPL flatten reset is intentionally excluded from trusted PnL/accounting because the missing legacy opening basis was never reconstructed; broker flatness and auditability are preserved without fabricating cost basis.
- The controlled 9432 BUY and SELL are JPY-denominated broker-backed ordinary accounting fills and now form a closed Japan-stock Paper round trip.
- The post-reset checkpoint and three-cycle soak confirm trusted accounting remained stable at `3` confirmed fills before the later 9432 close. Post-9432-close accounting now also contains the confirmed 9432 SELL reconciliation; final aggregate PnL/equity values should be taken from the next completion audit rather than guessed from the fill price alone.
- Equity, realized/unrealized PnL, trade history, and maximum drawdown remain reconstructable only from records that pass currency/accounting safety rules.

## Verification boundary
- GitHub CI cannot access the user's local TWS/Gateway or local runtime ledger.
- Repository CI validates code paths and safety invariants but cannot substitute for real Paper broker evidence.
- Read-only local monitoring is automated; user interaction should be requested only for local broker login, explicit Paper order approval, or other actions impossible from GitHub/CI.
- `READY FOR PAPER E2E REVIEW=True` and `PREFLIGHT ALLOWED=True` mean safety/readiness gates passed in the verified checkpoint/soak; they do not authorize unattended order transmission.
- No Live Trading completion claim is permitted.

## Next work
1. Treat the verified three-cycle read-only soak and the controlled 9432/TSEJ/JPY round trip as completed evidence; do not ask the user to repeat them merely for proof.
2. Fix/contain the background `ibapi.client.run` `serverVersion() is None` teardown/failed-connect TypeError without weakening any broker/order safety gate.
3. Continue repository-only issue #56 verification in sequence, using the now-flat Paper baseline: ETF/global-stock reuse audit first, then FX, futures, options, and crypto product-specific gates.
4. Before declaring the platform complete, require a final evidence-based completion audit covering integrated signals/backtest/trade-history/PnL/equity/drawdown/restart recovery plus the chosen scope of verified Paper capabilities.
5. Keep Live Trading disabled.
