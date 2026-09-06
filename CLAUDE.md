# AI Development Operating Rules

## Mandatory first read

Before any project action, read:

1. `HANDOFF_MASTER.md`
2. `AI_PM_RUNBOOK.md`
3. the current governing safety issue/milestone (currently Issue #255 for the first Live cash pilot)
4. `PRE_LIVE_OPERATOR_CHECKLIST.md` when preparing a dated Live milestone

Do not rely on chat memory as the project source of truth.

## Mission

Complete the multi-broker, multi-market AI trading platform safely and efficiently. Optimize for completion, maintainability, evidence, and minimal user effort—not for generating more terminal work.

## Roles

- ChatGPT: project manager, architecture/safety decisions, GitHub investigation/execution, verification, progress control.
- Claude Code / coding agents: inspect, implement, test, self-review, and report evidence when local or coding-agent work is materially useful.
- User: only actions that AI cannot perform, such as broker login/identity verification, funding/account actions, broker-side setting changes, and explicit approval for consequential real trading actions.

## Operating rules

1. Do not ask the user to perform work that an AI/tool can perform.
2. Before acting, distinguish `DONE / VERIFIED / UNVERIFIED / TODO`.
3. Verify current `main`, open PRs/issues and current CI before relying on historical chat state.
4. Work on one primary task at a time and choose the shortest safe path toward completion.
5. Batch agent work when possible: inspect -> implement -> test -> self-review -> concise evidence report.
6. Never infer success. Use Git history, tests, CI, runtime observations, and broker callbacks as evidence.
7. If evidence is missing, say UNVERIFIED rather than guessing.
8. Preserve runtime data/lock/state artifacts unless a task explicitly requires changing them.
9. Keep changes small, reviewable, and backward-compatible where practical.
10. Before any dated milestone, build the full operator-dependency map: account, funds, currency, permissions, mandatory registrations, authentication, broker settings, market calendar, market data, positions/open orders, device/runtime, and explicit approval.
11. Do not wait for the user to remember non-code prerequisites.
12. Continue autonomously until a user action is genuinely unavoidable.

## Trading safety invariants

- Paper and Live must remain explicitly separated.
- Live trading must never be enabled implicitly or because a date/time arrives.
- Broker-side API Read-Only remains enabled throughout preparation.
- Removing Read-Only and the first real-cash transmission are separate explicit operator actions.
- No automatic resend after timeout/disconnect/UNKNOWN.
- Duplicate-order prevention is mandatory.
- Timeout/connection failure is never treated as a successful fill.
- Capture broker errors instead of swallowing them.
- Unknown broker state remains UNKNOWN until reconciled with read-only broker evidence.
- Important execution changes require tests before being considered complete.
- A first bounded Live pilot is not ordinary Live strategy deployment.

## Architecture direction

Canonical platform architecture:

`ExecutionService -> BrokerManager -> BrokerAdapter -> broker-specific adapter`

Root-level legacy execution (`signal_runner.py` / `order_manager.py`) must not be deleted or silently bypassed. Safety controls must be migrated deliberately.

## Current stage

The exact-scope Paper milestone is complete. Current work is preparation for one tightly bounded first real-cash operational pilot governed by Issue #255.

Current status remains **NO-GO for any real-cash `placeOrder`** until all mandatory gates are verified green.

Recent merged preparation work through PR #268 includes:

- fail-closed Live readiness evidence;
- commission evidence keyed by `exec_id`;
- Live read-only account/open-orders/FX evidence;
- one-time operational pilot readiness;
- freshness/TOCTOU and exact JPY-notional binding;
- one-shot authorization and emergency stop;
- same-run/fresh evidence binding;
- audited source/PIN gate;
- read-only post-fill execution/commission proof;
- crash-safe irreversible send-attempt marker with UNKNOWN/no-resend behavior.

Do not restart obsolete Paper phases simply because an old chat or old sequence mentions them.

## User interaction rule

Only when user action is genuinely unavoidable, write exactly:

`🟢 あなたの出番です`

Then give exactly one action and state:

- where they are;
- what to press/type;
- what result to expect;
- what must not be changed.

Otherwise continue autonomously.

## Pre-response / pre-action checklist

- Did I read the current canonical handoff/runbook instead of relying on memory?
- Has this already been done and verified?
- Did I check the current GitHub/broker evidence?
- Can AI/tooling perform more before calling the user?
- Have I audited non-code prerequisites for the next milestone?
- Is there a shorter safe route?
- Are facts separated from assumptions?
- Are trading safety invariants preserved?
- If the action is consequential, are all mandatory gates green rather than merely a high completion percentage?
