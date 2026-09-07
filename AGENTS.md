# AGENTS.md — coding-agent coordination entrypoint

This repository does not use chat memory as the project source of truth.

Before changing anything, read in this order:

1. `HANDOFF_MASTER.md`
2. `AI_PM_RUNBOOK.md`
3. `COMPLETION_ROADMAP.md`
4. `PRE_LIVE_OPERATOR_CHECKLIST.md` when Live preparation is involved
5. the current governing GitHub issue/milestone (currently Issue #255 for the first bounded Live pilot)

Then verify current `main`, open PRs/issues, and current CI. Classify work as `DONE / VERIFIED / UNVERIFIED / TODO` before acting.

## Agent roles

- **Claude Code / primary implementation agent:** preserve implementation continuity, inspect current repository state, implement the smallest safe blocker-closing change, add/repair tests, run local/relevant tests, review its own diff, and leave concrete evidence.
- **Codex / independent second reviewer:** do not duplicate Claude's full implementation by default. For safety-critical trading changes, independently inspect the actual diff/code/tests and try to break assumptions. Codex may implement only when explicitly delegated because Claude is blocked or when the task is clearly separable and non-overlapping.
- **ChatGPT:** project manager, cross-agent coordinator, completion-roadmap control, safety/architecture acceptance, GitHub investigation/execution, evidence integration, progress control, and user handoff only when unavoidable.
- **GitHub:** canonical project state and evidence source. Diff + CI + broker/runtime evidence outrank any agent narrative.
- **User:** operator of last resort for broker login, identity/authentication, funding/account actions, broker-side setting changes, and explicit approval of consequential real-money actions.

Do not change the primary-agent role or introduce another development process without an explicit user decision recorded in the canonical project documents.

## Mandatory multi-agent gate

For safety-critical trading changes, no single AI's self-review is final acceptance.

Safety-critical includes at least:
- Live order transport or `placeOrder` paths;
- account/fingerprint/session binding;
- funds/currency/permission gates;
- one-shot authorization, emergency stop, duplicate prevention;
- timeout/disconnect/UNKNOWN handling;
- execution/commission/position/open-order reconciliation;
- source/PIN release gates;
- any change that could widen Live scope or relax a safety invariant.

Required acceptance sequence:

1. Claude Code implements from current canonical source by default.
2. Full relevant tests run locally or in the implementation environment.
3. Codex independently reviews the actual diff/code/tests from a clean perspective and tries to break assumptions; it does not redo the whole task unless a separate implementation is specifically justified.
4. Any finding is fixed by the primary implementation path and re-reviewed as needed.
5. GitHub CI and secret scan pass on the exact proposed commit/PR.
6. ChatGPT verifies the evidence against the current roadmap and governing issue before merge/acceptance.
7. Real-money execution still requires separate explicit operator approval after fresh runtime gates are green.

For non-safety-critical documentation or low-risk refactors, Claude Code or another single coding agent plus passing CI and ChatGPT verification may be sufficient; Codex review is not automatically required.

## Critical-path freeze

Until the first bounded Live pilot reaches a reconciled terminal outcome:

- do not add unrelated features;
- do not broaden ticker/quantity/market/broker scope;
- do not create new management/process layers unless they directly remove a verified blocker;
- prefer finishing the existing completion-roadmap path over improving tooling for its own sake.

## Operating rules

- Do not ask the user to do work that repository tools or agents can do.
- Prefer execution and evidence over explanatory prose.
- Do not repeat completed work unless evidence is stale or invalidated.
- Keep changes small, reviewable, and tied to one concrete blocker.
- Never infer success from a passing unit test alone; inspect end-to-end assumptions and failure paths.
- Treat stale broker/account/market evidence as invalid for consequential actions.
- Preserve Paper/Live separation and broker-side API Read-Only during preparation.
- Never auto-resend after timeout/disconnect/UNKNOWN.
- Never broaden ticker/quantity/market/broker scope silently.
- If facts are missing, mark `UNVERIFIED` and gather evidence instead of guessing.

## User interaction rule

Only when a human-only action is genuinely unavoidable, use exactly:

`🟢 あなたの出番です`

Then give one clear action with where to go, what to press/type, expected result, and what must not be changed.

Otherwise continue autonomously.
