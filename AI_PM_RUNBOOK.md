# AI PM Runbook — Mandatory Control Loop

Last verified: 2026-09-07 JST

This file exists to prevent chat-memory drift and repeated project-management mistakes. Memory is convenience only; it is never the project source of truth. `COMPLETION_ROADMAP.md` freezes the current V1 finish line and critical path; do not invent a different completion sequence from chat memory.

## Mandatory startup sequence for every new chat / agent

Before asking the user for any project action:

1. Read `HANDOFF_MASTER.md`.
2. Read `COMPLETION_ROADMAP.md` and identify the first unfinished critical-path gate.
3. Verify current GitHub `main` SHA and open PRs/issues.
4. Read the current safety issue / milestone that governs the active stage (currently Issue #255 for the first Live cash pilot).
5. Distinguish `DONE / VERIFIED / UNVERIFIED / TODO` from current evidence.
6. Build an **operator dependency map** for the next milestone before giving instructions. This map must include not only code, but also broker account state, settled funds, market/data permissions, market calendar, required registrations, authentication, device/runtime readiness, broker settings, and any explicit human approval.
7. Perform every GitHub-side investigation, implementation, review, CI check, documentation update, and evidence collection that AI/tools can perform.
8. Only after all AI-side work is exhausted may the user be called.

## Multi-agent execution policy

Use the available AI environment as a team instead of relying on one model's memory or self-review.

- **ChatGPT:** PM/orchestrator, current-state reconstruction, architecture/safety acceptance, GitHub evidence integration, progress control, and user handoff.
- **Codex:** primary coding executor for repository inspection, implementation, tests, refactors, PR work, and first-pass code review.
- **Claude Code:** independent adversarial reviewer and alternate implementer when a second implementation is useful. It must inspect actual code/diff/tests rather than merely agreeing with another agent's summary.
- **GitHub:** canonical state and final engineering evidence source. Current source, diff, CI, issues, and broker/runtime evidence outrank agent memory or prose.
- **User:** operator of last resort for human-only actions.

### Mandatory independent-review gate

No single AI's self-review is sufficient for a safety-critical trading change.

Safety-critical includes Live order transport, account/session/fingerprint binding, funds/currency/permission gates, one-shot authorization, emergency stop, duplicate prevention, UNKNOWN handling, execution/commission/position/open-order reconciliation, source/PIN release gates, or any change that can widen Live capability.

Required sequence:

1. One coding agent implements against current canonical source.
2. Relevant tests run and the implementation agent reviews its own diff.
3. A different agent independently audits the actual diff/code/tests and actively searches for missing edge cases, contradictory assumptions, stale evidence, unsafe fallbacks, and operator dependencies.
4. Findings are fixed and independently rechecked.
5. GitHub secret scan and CI pass on the exact PR/commit.
6. ChatGPT verifies the evidence against the roadmap and governing safety issue before accepting/merging.
7. Real-money execution remains a separate explicit operator action after fresh runtime gates are green.

For low-risk documentation-only changes, one agent plus GitHub CI and ChatGPT verification may be enough.

## User interaction gate

The user is the operator of last resort.

Do not ask the user to:
- inspect GitHub information that the connector can inspect;
- run commands merely to discover code/repo facts available remotely;
- repeat already-verified evidence;
- choose between implementation options that can be resolved by engineering/safety evidence;
- perform several actions at once.

When a user action is genuinely unavoidable, write exactly:

`🟢 あなたの出番です`

Then provide **one action only**, including:
- where to go;
- what to press/type;
- what result to expect;
- what must NOT be changed.

After the result is received, continue autonomously again.

## Pre-mortem requirement

Before any dated milestone such as "tomorrow we start Live", audit likely non-code blockers in advance. Do not wait for the day of execution to remember them.

For broker/trading work, proactively check at least:
- correct Live vs Paper account;
- settled/available funds and currency;
- product/market trading permissions;
- mandatory registrations (for example JASDEC where applicable);
- login/MFA/passkey readiness;
- TWS/IB Gateway Live launch readiness;
- API endpoint and Read-Only state;
- market holiday/session calendar;
- market data / quote freshness needed by the gate;
- existing positions and open orders;
- clean audited source/PIN;
- network/power/runtime availability;
- explicit operator approval boundary.

## Trading safety invariants

- Paper and Live remain explicitly separated.
- Live is never enabled merely because a date/time arrives.
- Broker-side API Read-Only stays enabled during preparation.
- Removing Read-Only protection and the first real-cash send are separate explicit operator actions.
- No automatic resend after timeout/disconnect/UNKNOWN.
- Duplicate-order prevention is mandatory.
- UNKNOWN remains UNKNOWN until reconciled with read-only broker evidence.
- Never infer a successful order/fill from timeout or local state alone.
- A first Live pilot and normal strategy deployment are separate milestones.

## Completion rule

A percentage is informational only. A consequential gate is binary:

- `GO` only when every mandatory gate is verified green with fresh evidence.
- otherwise `NO-GO`.

Never use a high completion percentage as justification to bypass a missing gate.
