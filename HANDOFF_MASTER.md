# stock_v2 / AI Asset Platform — Canonical Handoff Master

Last verified: 2026-09-06 JST

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

Verified `main` before this documentation branch: `4d956e353ff7972b1468af8af9cced26c165babb`, merge commit for PR #268.

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

The full test suite reported `1533 passed` for the latest PR #268 CI before merge.

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
- read-only Live execution + commission post-fill evidence.

### Still mandatory before first real-cash send

- bind the raw ephemeral account ID used by the final order to the same final Live session and verify its fingerprint;
- check emergency stop at the last possible point inside the actual sender;
- implement and independently audit the single-send Live transport/orchestrator;
- complete post-pilot completion judgment with final position, unexpected-open-order check, account/risk/reconciliation evidence, and alert result;
- on the Chromebook, run the exact approved pinned source with a clean safety-critical working tree and verify Paper monitoring remains intact;
- obtain fresh Live read-only evidence immediately before the operator step: account/fingerprint, funds, permissions, target position, open orders, quote/FX, notional, session state;
- keep broker-side API Read-Only enabled throughout preparation;
- removing Read-Only and the first real-cash transmission are separate explicit operator actions and are never date/time triggered.

## 2026-09-07 execution-calendar note

- NYSE is closed for Labor Day; AAPL/SPY cannot be a regular-session pilot candidate on 2026-09-07.
- JPX is scheduled open; within the existing bounded scope, `9432.T` is the calendar-compatible execution-mechanics candidate, subject to every other gate.

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
