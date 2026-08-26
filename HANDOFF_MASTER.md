# stock_v2 / AI Asset Platform — Canonical Handoff Master

Last verified: 2026-08-26 (JST)

This file is the canonical handoff entry point for ChatGPT/Claude/Codex agents. It exists to stop repeated re-discovery, duplicate Paper orders, and confusion between remote GitHub state and the user's Chromebook runtime state.

## Handoff destination — critical

The primary continuation destination is **ChatGPT Project `自動売買システム開発` -> `Work`**.

Do not restart the project in an unrelated normal chat. Do not treat GitHub alone as the handoff destination. GitHub stores the canonical code/evidence; ChatGPT Project keeps the long-running project context; Work is the primary place for the longer multi-step development workflow.

After entering Work, the next agent must read this file and `PROJECT_STATE.md` before asking the user to repeat anything.

### Operating model after handoff

- **ChatGPT Project / Work**: primary project manager and remote execution coordinator. Inspect GitHub, audit code, make safe changes, create PRs, check CI, review issues, research, and maintain project state before asking the user to do anything.
- **GitHub `main`**: canonical remote code and durable evidence source. Do not treat old chats or historical branches as newer than `main`.
- **Chromebook + IBKR Paper**: local runtime/evidence environment. Use only when remote work cannot answer the question. The user should receive one complete copy-paste command only when local execution is genuinely required.
- **Claude Code**: use only when local-filesystem implementation/testing is materially required or is clearly faster than remote GitHub work. Do not duplicate the same implementation in ChatGPT Work and Claude Code.
- **User**: performs only unavoidable local/authentication/approval actions. Mark those moments with `🟢 あなたの出番です`.

### No-more-handoff-loop rule

Once the project is running in Project `自動売買システム開発` -> Work, do not create another handoff merely because the chat becomes long. Update this file after substantive verified changes and continue from it. Create a new handoff only when the user explicitly migrates to a different environment or a genuine context boundary requires it.

### Work start sequence

On the first Work run after migration:

1. Read `HANDOFF_MASTER.md` and `PROJECT_STATE.md`.
2. Verify current `main`, open PRs, open issues, CI, and Live fail-closed state.
3. Identify the single current blocker from newer evidence; do not repeat old Paper proof.
4. Do all GitHub-side investigation/fixes/tests/PR/CI first.
5. Only if Chromebook/IBKR runtime evidence is indispensable, give exactly one user action with `🟢 あなたの出番です`.
6. When the user returns the result, continue automatically instead of restarting diagnosis.
7. Update canonical state only after substantive progress; documentation must follow implementation, not replace it.

### Current Paper milestone completion rule

The current development target is not merely “the wiring exists.” The Paper milestone is complete only when the verified scope can operate safely through an unattended Paper runtime with explicit opt-in, deterministic recovery, monitoring/reporting, and the final runtime gates pass. The normal safe startup may remain non-ordering; a deliberate Paper runtime/entry point may be separate. Live Trading is not part of this milestone and remains locked.

## Operator rules

- The user is a beginner. Minimize manual work, repeated confirmation, and long explanations.
- Top priority: finish as fast as possible without weakening safety.
- Do everything possible on the AI/GitHub side first: code audit, GitHub inspection, fixes, PRs, CI, issue cleanup, documentation, and static verification.
- Only when Chromebook / IBKR Paper state is genuinely required, explicitly say `🟢 あなたの出番です`.
- Give only one user action at a time. Commands must be complete and copy-pasteable.
- Do not repeat an already-proven Paper order merely to recreate evidence.
- Keep facts, inference, and unknowns separate. Never claim an unverified item is complete.

## Absolute safety boundary

- Live Trading is prohibited and must remain fail-closed.
- `enable_live_trading=False`; do not add or enable a Live order path.
- Timeout / uncertain broker state must never be automatically resent.
- Broker execution IDs are used for deduplication/reconciliation.
- AAPL reset fills with unproven opening basis remain excluded from ordinary trusted PnL.
- ESU6 success must not be generalized to all futures.
- The pinned SPY long-option round trip must not be generalized to exercise, assignment, expiry settlement, opening short options, multi-leg options, or arbitrary options.
- Crypto ContractDetails visibility is not proof of trading permission.
- Currency Conversion is not equivalent to leveraged Spot FX.

## Repository / environment

- Repository: `kimurakougyouk-creator/stock_v2`
- Canonical branch: `main`
- Chromebook directory: `~/stock_v2_latest`
- Python venv: `.venv`
- Proven IBKR Paper Gateway endpoint: `127.0.0.1:4002`
- TWS Paper alternative: `7497`
- Account currency: JPY
- Account timezone: Asia/Tokyo

Remote implementation `main` before this final evidence record: `2ab0f5ba39206e6d6bd6a649db3b5464cedbe36d`.

Do not assume the Chromebook checkout is already at the latest remote commit unless verified locally.

## Source-of-truth priority

When sources disagree:

1. Current `main` code.
2. Latest actual Chromebook / IBKR Paper runtime evidence.
3. This `HANDOFF_MASTER.md`.
4. `PROJECT_STATE.md` as the bounded capability ledger.
5. Historical chats, old handoff text, old branches.

Old feature/version branches are not authoritative just because their names look newer or more specific.

## GitHub status at handoff

- PR #234: Phase 7 signal-runner final IBKR Paper wiring — merged.
- PR #235: exact verified derivative rows can be safely quarantined from the legacy whole-share ledger — merged.
- PR #236: post-cleanup reconciliation audit runs automatically in the cleanup wrapper — merged.
- PR #238: the read-only reconciliation audit recognizes the exact closed SPY stock pair using the SELL row's explicit FX without mutating the ledger — merged.
- PR #239: the clean reconciliation state and bounded-soak next gate were recorded — merged.
- PR #240: the exact closed-SPY BUY row can be durably repaired from its uniquely matching SELL row's explicit FX, with backup first and no broker order — merged.
- PR #241: an explicit bounded, fail-closed IBKR Paper runtime entry point for AAPL 1 / SPY 1 / 9432.T 100 was added — merged.
- Open PRs: 0 at the last pre-workflow check.
- Open Issues: 0 at the last pre-workflow check.
- `main` branch protection: disabled.
- Many historical feature/version branches remain and are not authoritative.
- `fix/quarantine-verified-derivative-ledger-rows-2` is a stray historical work branch, not a newer source than `main`.

## Phase 7: exact meaning of COMPLETE

PR #234 completed the safe wiring:

`signal_runner -> execute_approved_signal_via_ibkr_paper -> ExecutionService -> shared risk gate -> IBKR Paper adapter`

The old production final dispatch through local `create_paper_order()` is no longer the final broker dispatch path.

But Phase 7 COMPLETE does **not** mean normal startup automatically sends Paper orders:

- `run_signal_scan(..., allow_orders=False)` defaults to no orders.
- `signal_runner.main()` does not pass `allow_orders=True`.
- `start.sh` explicitly says it does not place real orders and invokes `python -m signal_runner` in the non-ordering default mode.

Therefore:

- Safe IBKR Paper dispatch wiring: complete.
- Ordinary default startup auto-ordering: intentionally off.

## Explicit verified Paper signal universe

Current signal-order bridge broker-evidenced Paper quantities:

- AAPL: 1 share
- SPY: 1 share
- 9432.T: 100 shares

Unregistered ticker/quantity combinations remain fail-closed.

IBKR Paper dispatch requires both:

- `enable_paper_trading=True`
- `enable_ibkr_paper=True`

`enable_ibkr_paper` is controlled by `AI_ASSET_ENABLE_IBKR_PAPER` and defaults to `False`.

The current Chromebook `.env` value for this flag is unknown at handoff and must not be guessed.

## Verified capability boundary

### Stocks / ETF

- US stock Paper capability: verified within bounded existing evidence.
- US ETF Paper capability: verified within bounded existing evidence.
- 9432/TSEJ/JPY: controlled BUY 100 -> SELL 100 -> broker/local flat evidence exists. This does not prove all Japanese/global stocks.
- AAPL reset SELL 3 returned broker quantity to 0, but historical opening basis was not proven; the reset is not ordinary trusted PnL evidence.

### ESU6 futures

- ESU6 / CME / USD
- expiry: 20260918
- multiplier: 50
- conId: 649180671
- BUY 1 @ 7668.25, exec_id `0000e1a7.6a8f948c.01.01`
- SELL 1 @ 7667.75, exec_id `0000e1a7.6a8f948d.01.01`
- returned flat
- multiplier-aware accounting/recovery evidence exists

Do not generalize to other futures, expiries, short-first, multi-contract, roll, overnight, settlement, or margin-stress behavior.

### Pinned SPY option

- `SPY 260828C00765000`
- expiry: 20260828
- strike: 765
- right: C
- multiplier: 100
- conId: 900369377
- BUY 1 @ 4.08, exec_id `00020057.6a8c86b2.01.01`
- SELL 1 @ 4.07, exec_id `00020057.6a8c86b3.01.01`
- realized gross PnL: -1.00 USD
- returned flat
- restart recovery evidence exists

Unverified and fail-closed: exercise, assignment, expiry settlement, opening short option, multi-leg option, arbitrary option contracts.

### FX

- USD/JPY@IDEALPRO ContractDetails and Paper API connectivity are verified.
- Explicit What-If reached IBKR but was rejected with error 201: `FX trade would expose account to currency leverage.`
- Leveraged Spot FX Paper capability is not promoted.

### Crypto

- BTC/USD ContractDetails resolve on PAXOS and ZEROHASH.
- Paper order validation was not proven.
- ZEROHASH returned invalid-account; PAXOS did not produce an acceptance preview.
- Crypto remains unpromoted and fail-closed.

## Earlier completion audit vs latest runtime state

Do not confuse these two facts.

### Earlier bounded capability audit

The earlier exact-scope consolidated audit passed for the then-verified stock/ETF/global-stock evidence, ESU6, pinned SPY option, and capability boundaries.

### Latest Chromebook runtime evidence

A later read-only soak on 2026-08-26 produced:

- `1342 passed in 25.12s`
- IBKR Paper endpoint 4002
- broker account ready
- broker position count 0
- broker SPY held qty 0
- no real order sent
- no Live order sent
- soak stopped at cycle 1 because legacy whole-share accounting was not safe

Latest observed blockers before PR #235/#236 were executed locally:

1. SPY BUY 1 @ 765.45 — exec_id `00012ec5.6ab91096.01.01` — missing historical FX
2. ES BUY 1 @ 7668.25 — exec_id `0000e1a7.6a8f948c.01.01` — missing historical FX
3. ES SELL 1 @ 7667.75 — exec_id `0000e1a7.6a8f948d.01.01` — missing historical FX
4. SPY SELL 1 @ 4.07 — exec_id `00020057.6a8c86b3.01.01` — missing historical FX

At that point:

- `ACCOUNTING SAFE: False`
- `PREFLIGHT ALLOWED: False`
- `READY FOR PAPER E2E REVIEW: False`
- real order sent: False

A subsequent reconciliation evidence audit confirmed account ready, execution snapshot ready, AAPL broker/local 0/0, SPY broker/local 0/0, 0 currently recoverable execution matches for all four blockers, no ledger change, and no order sent.

A subsequent Completed Orders audit confirmed READY=True, port 4002, ORDER COUNT=0, REAL ORDER SENT=False.

Current IBKR dynamic history therefore cannot recover those old executions.

### Latest cleanup and reconciliation result

The verified-derivative cleanup was executed on the Chromebook on 2026-08-26 JST:

- targeted cleanup tests: `4 passed`
- exact derivative rows retired: `4`
- backup: `results/verified_derivative_cleanup_backups/paper_orders.before_verified_derivative_cleanup.20260826T161456+0900.jsonl`
- quarantine: `results/quarantined_verified_derivative_ledger_rows.jsonl`
- order sent: `False`

The remaining SPY stock BUY 1 @ 765.45 has a matching SELL 1 @ 766.34 with a distinct broker execution ID and explicit `fx_to_account_rate=158.875`. PR #238 made the read-only reconciliation audit reuse the existing calculation-only exact-pair rule. It copies and enriches audit records in memory only; it does not write the durable ledger. Ambiguous or overlapping execution identity still fails closed.

Chromebook verification after PR #238:

- targeted reconciliation tests: `8 passed`
- account ready: `True`
- execution snapshot ready: `True`
- endpoint: `4002`
- AAPL broker/local: `0/0`
- SPY broker/local: `0/0`
- blocker count: `0`
- next action: `RECONCILIATION_EVIDENCE_IS_CLEAN`
- ledger changed: `False`
- Paper order sent: `False`
- Live order sent: `False`

### Final Paper milestone evidence

The closed SPY ledger repair was executed on the Chromebook on 2026-08-26 JST:

- targeted repair/audit tests: `16 passed`
- repaired intent: `broker-recovery:00012ec5.6ab91096.01.01`
- persisted FX rate: `158.875`
- exact reference SELL exec_id: `0000e511.6a8b602c.01.01`
- backup: `results/closed_spy_fx_repair_backups/paper_orders.before_closed_spy_fx_repair.20260826T164549+0900.jsonl`
- reconciliation remained clean with AAPL/SPY broker/local `0/0` and blocker count `0`
- accounting safe, preflight allowed, and Paper E2E review ready were all `True`
- broker order sent: `False`; Live order sent: `False`

The bounded read-only soak then passed three consecutive process cycles:

- full suite before soak: `1348 passed in 25.23s`
- every cycle: account ready, broker positions `0`, SPY held `0`, legacy blockers `[]`, accounting safe `True`, preflight allowed `True`, Paper E2E review ready `True`
- every cycle: Paper order sent `False`; Live order sent `False`
- final result: `PASS (3 consecutive read-only cycles)`

Targeted restart/network-loss/reconciliation tests passed `31` tests. They cover connection loss blocking dispatch, failed reconnect remaining fail-closed, fill-state recovery after restart, and durable order-intent duplicate suppression. PR #241's bounded Paper runtime passed `37` targeted tests; its remote-equivalent full suite passed `1359` tests.

The deliberate runtime `ibkr_verified_paper_runtime_once.sh` was then executed after synchronizing local `main`:

- runtime tests: `37 passed in 2.80s`
- exact scope: AAPL `1`, SPY `1`, 9432.T `100`
- Live Trading: `PROHIBITED`
- AAPL: technical `HOLD`, AI `SELL`, final `HOLD`
- SPY: technical `HOLD`, AI `HOLD`, final `HOLD`
- 9432.T: technical `BUY`, AI `SELL`, final `HOLD`
- analysis records: `3`; data failures: `0`
- confirmed new Paper fills: `0`
- runtime errors: `0`; execution errors: `0`
- Live order sent: `False`

Zero new fills is the correct result for this scan because no ticker had a final BUY or SELL decision. It is not an execution failure and is not a reason to force or repeat an order.

The Paper milestone completion rule is therefore satisfied for the exact verified scope. Normal `start.sh` remains intentionally non-ordering; Paper dispatch is available only through the deliberate, explicitly opted-in bounded entry point. Live Trading and unsupported/broader products remain outside this completion claim and fail closed.

## Interpretation of the four legacy blockers

Three blockers exactly match immutable derivative evidence already stored in the repository:

- ES BUY 7668.25 -> verified ESU6 futures
- ES SELL 7667.75 -> verified ESU6 futures
- SPY SELL 4.07 -> verified pinned SPY option

These three rows should not remain in the legacy whole-share stock/ETF ledger.

The remaining blocker:

- SPY BUY 1 @ 765.45
- exec_id `00012ec5.6ab91096.01.01`

is not covered by the immutable derivative evidence identified above. Do not guess historical FX and do not delete it without evidence.

## PR #235 cleanup behavior

`ibkr_verified_derivative_ledger_cleanup_once.sh` is **not fully read-only with respect to local files**.

It may change the local legacy ledger only after strict checks:

- exact immutable derivative exec_id
- exact side
- exact quantity
- exact price
- exact broker order id
- matching current derivative broker position is flat

When eligible rows are found it:

1. backs up the original ledger
2. appends exact records to a quarantine file
3. removes only those verified derivative rows from the active whole-share ledger
4. runs the reconciliation evidence audit afterward

It does not create, change, cancel, or transmit any broker order.

Do not call this wrapper fully read-only. It is broker-read-only but may change the local ledger after backup/quarantine.

## Chromebook local state: do not invent

At the latest observed local run, `git status` showed:

`M results/decision_log_report.csv`

The current status of that file is unknown.

Do not automatically run `git reset`, `git clean`, `git stash`, delete runtime artifacts, or commit generated files merely to make the tree clean.

Still unknown:

- the persistent `.env` value of `AI_ASSET_ENABLE_IBKR_PAPER`; the verified wrapper used process-scoped explicit Paper opt-in
- systemd read-only autopilot installed/enabled/active state
- whether IB Gateway/TWS is running at a future resume time

These remain unknown until a local check is genuinely needed.

## Repository hygiene note

- `main` is currently unprotected.
- Many historical branches remain.
- This is not the immediate runtime blocker and should not distract from Paper runtime validation.
- Do not mass-delete branches or perform repository cleanup during handoff/recovery work unless separately reviewed and authorized.

## What the next agent must do first

Do **not** immediately give the user commands.

First, on the AI side:

1. confirm current remote `main`
2. confirm open PRs/issues
3. confirm PR #234/#235/#236 remain merged
4. inspect current `HANDOFF_MASTER.md` and `PROJECT_STATE.md`
5. confirm Live remains fail-closed
6. avoid re-running already-proven Paper orders

Only if local runtime evidence is genuinely required should the user be asked for one action.

## Next development objective after handoff

The exact verified-scope Paper milestone is complete. Do not create duplicate broker proof or force an actionable signal merely to produce a new fill.

The next single stage is monitored Paper operation over time: accumulate ordinary deliberate-run results and evaluate strategy quality, reporting, and operational alerts without broadening the capability registry. Any future FX/Crypto or broader derivative expansion requires new broker/account evidence first. Live Trading is a separate, unauthorized stage and remains prohibited/fail-closed.

---

If a future chat conflicts with this handoff, it must show newer `main` code or newer local runtime evidence. Old chat text alone is not enough to override this file.
