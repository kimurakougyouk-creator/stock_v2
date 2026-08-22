# Project State

Last updated: 2026-08-23

This file is the concise, evidence-based handoff ledger for AI agents. Update it after meaningful verified progress. Do not replace verified facts with guesses.

## Current phase
Final IBKR Paper integrated runtime validation. Repository-side safety, multicurrency accounting, broker/local reconciliation, broker execution recovery, broker execution-id deduplication, and a dedicated position-reducing SPY Overnight close path are merged. The remaining verification boundary is one local Chromebook/TWS-or-Gateway Paper close-cycle observation and the follow-up checkpoint.

## Verified repository state
- Repository: `kimurakougyouk-creator/stock_v2`
- Branch: `main`
- PRs #114-#118: account-currency accounting, fail-closed verified Paper preflight, dedicated verified IBKR Paper execution path, one-command operator checkpoint, and account-timezone handling.
- PR #135 merged: read-only broker execution-history evidence plus broker/local position reconciliation guard in the Paper execution path.
- PR #136 merged: deterministic broker execution reconciliation into the durable local Paper ledger.
- PR #138 merged after CI success: one-command `ibkr_auto.sh` now performs broker-confirmed execution reconciliation before the fail-closed checkpoint.
- PR #139 merged after CI success: broker historical MIDPOINT FX evidence can be anchored to confirmed execution time for recovery accounting instead of incorrectly comparing an old fill to the current wall clock.
- PR #140 merged after fixing an initial CI failure and re-running to success: confirmed fills persist broker execution/order identity; reconciliation deduplicates by broker `exec_id` across application intents and recovery intents.
- PR #141 merged after CI success: dedicated fail-closed, position-reducing SPY Overnight Paper SELL path, separate SELL what-if, explicit close confirmation gate, and one-command close script. Live Trading remains prohibited.
- Current open pull requests: none.

## Verified real IBKR Paper evidence
- Controlled SPY Paper BUY: quantity 1, terminal status `Filled`, filled quantity `1.0`, average fill price `765.45`, order id `3`.
- Broker execution evidence: `exec_id=00012ec5.6ab91096.01.01`, side `BUY`, quantity `1`, price `765.45`, currency `USD`, exchange `BYX`.
- Latest local operator run connected to IBKR Paper endpoint port `4002`.
- Overnight SPY BUY what-if connected and returned a preview with `PRIMARY EXCHANGE=ARCA`, `DESTINATION=OVERNIGHT`, quantity `1`, and `REAL ORDER SENT=False`.
- Broker account snapshot was ready with base currency `JPY`; it reported one SPY share already held.
- The BUY checkpoint correctly failed closed with `broker Paper account already holds 1 SPY share(s); duplicate BUY is blocked`.
- Latest read-only execution snapshot reported exactly one confirmed SPY BUY execution and sent no order.
- Do not send another BUY merely to re-prove the already verified fill.

## Current verified Paper execution model
- Live Trading remains disabled/unimplemented in the active path.
- New BUY exposure requires broker/local position agreement, verified quantity, account-currency preflight, risk gates, and broker evidence.
- Existing broker executions are recovered into local durable state before the normal operator checkpoint.
- Broker `exec_id` is persisted and used for cross-process deduplication so one confirmed execution cannot be counted twice under different local intent ids.
- Cross-currency recovery may use broker historical MIDPOINT data anchored to the confirmed execution time; unavailable evidence remains fail-closed and is never guessed.
- Protective/position-reducing SELL preflight intentionally does not require a fresh FX quote merely to reduce an already-confirmed position.
- Timeout or uncertain order state is never automatically resent.

## Current blockers and their meaning
- `FX READY=False` in the latest checkpoint is explained by unavailable current USD/JPY market data plus stale historical evidence at that moment. This must not be bypassed for new BUY exposure.
- `LEGACY EVIDENCE BLOCKERS` still includes an older AAPL record with missing currency. That legacy row remains quarantined from safe accounting rather than being guessed.
- `SPY CONFIRMED HELD QTY` was still zero in the pre-reconciliation local checkpoint while the broker held one SPY share. Repository changes after that observation now automatically reconcile broker-confirmed execution evidence before re-running the checkpoint.
- The held SPY share is therefore the intentional next lifecycle target: reconcile it locally, close it through the dedicated position-reducing Paper SELL path, persist the confirmed SELL with broker identity, then verify broker/local quantity returns to zero.

## Accounting and reporting
- Only accounting-effective records are included; IBKR Paper requires confirmed `FILLED` evidence.
- Confirmed fills are idempotent by local `order_intent_id` and broker execution identity.
- Cross-currency confirmed fills require explicit per-fill FX evidence for account-currency accounting. Missing FX is never guessed.
- Equity, realized/unrealized PnL, trade history, and maximum drawdown remain reconstructable only from evidence that passes the currency/accounting safety rules.

## Verification boundary
- GitHub CI cannot access the user's local TWS/Gateway or local runtime ledger.
- Repository CI has validated the new reconciliation, execution-id deduplication, and position-reducing close code, but only the user's local Paper broker can prove the full close-cycle behavior.
- The next real-broker action must be Paper-only and position-reducing. It must not create new exposure.
- No Live Trading completion claim is permitted.

## Single next action
Do not ask the user to perform fragmented diagnostics. First sync current `main` locally. Then use the dedicated one-command SPY Paper close path during an open Overnight session, with its explicit confirmation gate, to close exactly the one reconciled SPY share. After the broker-confirmed SELL is persisted, immediately re-run the non-order `ibkr_auto.sh` checkpoint and require broker/local SPY quantity zero before any new BUY test is considered.
