# Project State

Last updated: 2026-08-23

This file is the concise, evidence-based handoff ledger for AI agents. Update it after meaningful verified progress. Do not replace verified facts with guesses.

## Current phase
Final IBKR Paper integrated runtime validation plus repository-only multi-asset foundation work. The remaining real-broker lifecycle boundary is still one local Chromebook/TWS-or-Gateway Paper SPY close-cycle observation and follow-up checkpoint. While that session-dependent proof is pending, repository work continues on issue #56 without enabling any new asset-class trading capability.

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
- PR #145: session-aware one-command SPY Paper close cycle chooses only an already-supported close route and never opens exposure; if no supported session is open, no order path is called.
- PR #146: batch read-only multi-asset ContractDetails audit foundation; default targets are explicit and no order is created or transmitted.
- PR #147: fail-closed futures Contract foundation requiring explicit broker-derived symbol, exchange, currency, expiry and multiplier; no futures quantity or order path is enabled.
- PR #148: fail-closed options Contract foundation requiring explicit broker-derived symbol, exchange, currency, expiry, strike, right and multiplier; no option selection or order path is enabled.
- PR #149: fail-closed crypto Contract foundation requiring explicit broker-derived symbol, documented venue and currency; no token selection, quantity assignment or order path is enabled.
- Live Trading remains prohibited.

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

## Multi-asset issue #56 boundary
- ETF/global stock/FX/futures/options/crypto repository foundations exist, but existence of a Contract builder or discovery helper is not trading support.
- Futures, options and crypto remain unverified trading capabilities: no Paper quantity is assigned, no new exposure order path is enabled, and account/region/product permission is not inferred.
- Crypto venue/currency constraints are represented explicitly; account/residence availability remains a separate evidence gate.
- Promotion to a verified capability still requires product-specific safety checks, no-transmit evidence and real Paper E2E evidence.

## Current blockers and their meaning
- `FX READY=False` in the latest checkpoint is explained by unavailable current USD/JPY market data plus stale historical evidence at that moment. This must not be bypassed for new BUY exposure.
- `LEGACY EVIDENCE BLOCKERS` still includes an older AAPL record with missing currency. That legacy row remains quarantined from safe accounting rather than being guessed.
- The broker held one SPY share while the older local checkpoint still showed zero before reconciliation; repository changes now reconcile broker-confirmed execution evidence before the checkpoint.
- The held SPY share remains the intentional next real-broker lifecycle target: reconcile locally, close through the position-reducing Paper SELL path, persist the confirmed SELL with broker identity, then verify broker/local quantity returns to zero.

## Accounting and reporting
- Only accounting-effective records are included; IBKR Paper requires confirmed `FILLED` evidence.
- Confirmed fills are idempotent by local `order_intent_id` and broker execution identity.
- Cross-currency confirmed fills require explicit per-fill FX evidence for account-currency accounting. Missing FX is never guessed.
- Equity, realized/unrealized PnL, trade history, and maximum drawdown remain reconstructable only from evidence that passes the currency/accounting safety rules.

## Verification boundary
- GitHub CI cannot access the user's local TWS/Gateway or local runtime ledger.
- Repository CI validates code paths and safety invariants but cannot substitute for real Paper broker evidence.
- The next real-broker action must be Paper-only and position-reducing. It must not create new exposure.
- No Live Trading completion claim is permitted.

## Single next real-broker action
Do not ask the user to perform fragmented diagnostics. When a supported close session is open, sync current `main` locally and use the session-aware one-command SPY Paper close path with its explicit confirmation gate to close exactly the one broker-confirmed SPY share. After the broker-confirmed SELL is persisted, immediately re-run the non-order checkpoint and require broker/local SPY quantity zero before any new BUY test is considered.
