# stock_v2 / AI Asset Platform — Canonical Handoff Master

Last verified: 2026-09-08 JST

This is the canonical cross-chat handoff entry point. **Do not rely on chat memory alone.** Read `AI_PM_RUNBOOK.md` before asking the user for project work. Detailed capability evidence remains in `PROJECT_STATE.md`; current code/evidence is determined from GitHub `main` plus fresh broker/runtime evidence.

## Current operating model

- **ChatGPT chat** is the primary project-management, safety-audit, GitHub investigation and GitHub execution environment.
- **GitHub `main`** is the canonical remote code/evidence source.
- **Claude Code / local coding agents** are used only when local-filesystem implementation/testing is materially required or clearly faster than remote GitHub work.
- **Chromebook + IBKR** is used only when local/broker runtime evidence is genuinely indispensable.
- **User action is last resort**. Complete all AI/tool work first.
- When user action is genuinely unavoidable, show `🟢 あなたの出番です` and provide exactly one action with location, operation, expected result, and what not to change.
- Before any dated milestone, audit non-code operator prerequisites in advance. See `PRE_LIVE_OPERATOR_CHECKLIST.md`.

## Mandatory PM control loop

At the start of every chat/agent continuation:

1. read this file and `AI_PM_RUNBOOK.md`;
2. verify current `main`, open PRs/issues and governing safety issue;
3. classify current work as `DONE / VERIFIED / UNVERIFIED / TODO`;
4. build the operator-dependency map (code + account + funds + permissions + registrations + authentication + broker settings + market calendar + device/runtime + explicit approval);
5. exhaust all GitHub/AI work before asking the user for anything;
6. when a user action becomes unavoidable, request one action only, then resume autonomous work.

## Source-of-truth priority

When sources disagree:

1. Current GitHub `main` code and merged PR evidence.
2. Fresh actual Chromebook / IBKR runtime evidence.
3. Current governing GitHub issue / milestone safety checklist.
4. This `HANDOFF_MASTER.md` and `AI_PM_RUNBOOK.md`.
5. `PROJECT_STATE.md` for bounded capability history.
6. Historical chats, old handoffs, old branches, old version labels, memory.

## Repository / environment

- Repository: `kimurakougyouk-creator/stock_v2`
- Canonical branch: `main`
- Chromebook directory: `~/stock_v2_latest`
- Python venv: `.venv`
- IBKR Paper Gateway: `127.0.0.1:4002`
- TWS Paper: `7497`
- IB Gateway Live: `4001`
- TWS Live: `7496`
- Account currency: JPY
- Account timezone: Asia/Tokyo

## Current verified GitHub state

Verified `main` before this documentation branch: `59a3bf7980efebd5f079f3311540da8c78dabd2c`, merge commit for PR #278.

Recent Live-preparation work merged includes:

- PR #254 — fail-closed real-cash readiness evidence gate.
- PR #256 — read-only commission evidence keyed by `exec_id`.
- PR #257 — explicit Live read-only account preflight on ports 4001/7496.
- PR #258 — Live all-open-orders read-only preflight.
- PR #259 — one-time operational Live pilot readiness gate; separate from ordinary strategy deployment.
- PR #260 — Live read-only FX evidence with account-base-currency validation.
- PR #261 — freshness/TOCTOU hardening.
- PR #262 — exact price × quantity × FX-derived JPY notional binding.
- PR #263 — natural strategy execution-record matching hardening.
- PR #264 — durable one-shot authorization + emergency-stop primitives.
- PR #265 — same-run/fresh pre-send evidence binding.
- PR #266 — audited source/PIN cutover gate.
- PR #267 — read-only Live post-fill execution/commission evidence.
- PR #268 — crash-safe irreversible send-attempt marker and UNKNOWN/no-resend state handling.
- PR #271 — fail-closed single-send Live pilot transport: same-socket raw account ID bound to pinned fingerprint, last-point emergency-stop check, exactly one `placeOrder` call site, UNKNOWN/no-resend on timeout or ambiguous acknowledgement.
- PR #272 — settled-cash-in-instrument-currency gate (plus reserve) required in the same-run preflight before the first Live pilot.
- PR #273 — exact post-pilot completion judge: journal identity, execution + commission evidence, final account/position, zero Live open orders, endpoint/fingerprint/freshness/Paper-safety evidence, durable local alert.
- PR #274 — split/partial-execution aggregation by exact orderId/permId/account/ticker/side; duplicate/missing/underfill/overfill/conflicting evidence fails closed.
- PR #275 — Paper daily risk limits use the account calendar/timezone.
- PR #276 — support for IBKR's current `$LEDGER-`-prefixed per-currency SettledCash evidence; conflicting prefixed/legacy evidence fails closed.
- PR #277/#278 — AI operating-role documents (`AGENTS.md`/`CLAUDE.md`/`AI_PM_RUNBOOK.md`) aligned to Claude-primary implementation, Codex independent review.

**Independent-review gate note (2026-09-08):** no GitHub PR review is recorded on PR #271, #273, or #274 (`gh pr view <n> --json reviews,comments` returns empty for all three). These are safety-critical under `AGENTS.md` (Live order transport / `placeOrder` path, post-fill reconciliation, execution/commission matching). Per the mandatory multi-agent gate, implementation completeness alone does not close this line item until Codex has independently reviewed the actual diff/tests for these three PRs and any finding is resolved. Treat this as open until that review is recorded.

The full test suite reported `1581 passed` locally on this exact `main` commit on 2026-09-08 (matches the PR #276 CI figure; no drift since).

## Current development stage

The exact-scope Paper milestone is complete. The current stage is **preparation for one tightly bounded first real-cash operational pilot**, not ordinary Live strategy deployment.

Current governing safety issue: **Issue #255**.

Current verdict: **NO-GO for any real-cash `placeOrder`** until every remaining mandatory gate is verified green.

### Already-closed preparation primitives

- fresh bounded operational-pilot readiness;
- durable one-shot authorization;
- independent emergency-stop latch;
- fresh endpoint/account-fingerprint/notional evidence binding;
- audited source/PIN cutover gate;
- crash-safe UNKNOWN / no-resend journal;
- read-only Live execution + commission post-fill evidence;
- same-final-session raw account-ID → pinned-fingerprint binding, implemented inside the actual sender (PR #271);
- last-possible-point emergency-stop check implemented inside the actual sender, after the one-shot authorization is irreversibly consumed (PR #271);
- single-send Live transport/orchestrator implemented (PR #271), including settled-cash-plus-reserve gating (PR #272);
- integrated post-pilot completion judge with split/partial-fill aggregation (PR #273, PR #274).

### Still mandatory before first real-cash send

- **Codex independent review** of the merged safety-critical sender/completion/reconciliation code (PR #271, #273, #274) — not yet recorded on GitHub as of 2026-09-08; see the independent-review gate note above;
- on the Chromebook, run the exact approved pinned source with a clean safety-critical working tree and verify Paper monitoring remains intact;
- obtain fresh Live read-only evidence immediately before the operator step: account/fingerprint, funds, permissions, target position, open orders, quote/FX, notional, session state;
- external/operator prerequisites not provable from GitHub (see the 2026-09-07 operator-state handoff below): JPY funding settlement, Japanese-stock trading permission approval, JASDEC registration completion, and a proven Live TWS/IB Gateway read-only API socket;
- keep broker-side API Read-Only enabled throughout preparation;
- removing Read-Only and the first real-cash transmission are separate explicit operator actions and are never date/time triggered.

## 2026-09-07 operator-state handoff (from Issue #255)

Canonical external/runtime state while broker-side prerequisites are pending — do not repeat or reverse these:

- IBKR Live Client Portal login: verified working.
- JPY funding: operator submitted a JPY 60,000 domestic transfer scheduled for 2026-09-08. Do not resend or create another funding instruction. Live `SettledCash`/`AvailableFunds` are not yet verified as credited.
- Domestic bank instruction registration: completed.
- JASDEC shareholder-information form: fields were filled and the portal showed a save confirmation; whether the backend status is formally submitted/processing/completed is UNVERIFIED.
- Japanese stock trading permission: portal shows pending approval. Do not remove/re-submit the permission request.
- Live TWS/IB Gateway API runtime: Live read-only socket proof is still UNVERIFIED. Read-Only stays ON.
- No real-cash order, What-If, cancel, modify, close/flatten, retry, or Read-Only removal is authorized.

## Execution-calendar note (verified 2026-09-08 from `verified_market_session.py`, not re-guessed)

- 2026-09-07 (Mon): NYSE closed for Labor Day; JPX scheduled open — `9432.T` was the only calendar-compatible candidate that day.
- 2026-09-08 (Tue, today): both the US core session and the TSE cash session evaluate as regular open sessions (no weekend/holiday block) per the pinned calendar in `verified_market_session.py`; this does not by itself change NO-GO status — every other gate above still applies, and the external/operator prerequisites remain the binding constraint.

This is not an investment recommendation.

## Operator prerequisite rule

Do not wait until the execution day to remember non-code prerequisites. Before the pilot day, proactively verify/prepare where possible:

- Live account login + MFA/passkey;
- settled/available funds and correct currency;
- intended market/product trading permission;
- mandatory market registration, including JASDEC where applicable for Japanese cash equities;
- TWS/IB Gateway Live launch readiness;
- network/power/runtime availability;
- market calendar;
- API Read-Only remains ON during preparation.

See `PRE_LIVE_OPERATOR_CHECKLIST.md` for the full split between pre-day preparation and fresh execution-day evidence.

## Exact bounded pilot scope

Existing exact-scope pilot quantities remain:

- AAPL: 1 share
- SPY: 1 share
- 9432.T: 100 shares

Unsupported ticker/quantity combinations remain fail-closed. The pilot is execution-mechanics validation only. It does not approve ordinary or expanded Live strategy deployment.

## Absolute safety boundary

- Paper and Live remain explicitly separated.
- Live must never be enabled implicitly or merely because the calendar date arrives.
- Broker-side API Read-Only remains ON during preparation.
- No automatic resend after timeout/disconnect/UNKNOWN.
- Duplicate-order prevention is mandatory.
- UNKNOWN remains UNKNOWN until reconciled with read-only broker evidence.
- Unattended monitoring must never place, change, cancel, close, retry, or transmit an order.
- A high completion percentage never overrides a missing mandatory gate.

## What the next agent must do first

Do **not** immediately give the user commands.

First, on the AI side:

1. verify current GitHub `main`;
2. read `AI_PM_RUNBOOK.md`, Issue #255, and `PRE_LIVE_OPERATOR_CHECKLIST.md`;
3. verify open PRs/issues and current CI evidence;
4. continue closing remaining Live-pilot blockers on GitHub;
5. independently audit any final sender before allowing a GO decision;
6. proactively audit operator prerequisites before the scheduled pilot day;
7. call the user only at the first genuinely unavoidable operator step.

If later evidence conflicts with this handoff, only newer GitHub `main`, newer governing issue evidence, or newer measured Chromebook/IBKR runtime evidence may override it.
