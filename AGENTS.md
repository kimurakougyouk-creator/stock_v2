# AGENTS.md — Codex / coding-agent entrypoint

This repository does not use chat memory as the project source of truth.

Before changing anything, read in this order:

1. `HANDOFF_MASTER.md`
2. `AI_PM_RUNBOOK.md`
3. `COMPLETION_ROADMAP.md`
4. `PRE_LIVE_OPERATOR_CHECKLIST.md` when Live preparation is involved
5. the current governing GitHub issue/milestone (currently Issue #255 for the first bounded Live pilot)

Then verify current `main`, open PRs/issues, and current CI. Classify work as `DONE / VERIFIED / UNVERIFIED / TODO` before acting.

## Agent roles

- **Codex / primary coding agent:** inspect repository state, implement the smallest safe change, add/repair tests, run tests, review its own diff, and leave concrete evidence.
- **Claude Code / independent second agent:** independently audit safety-critical changes and failure modes. Do not merely paraphrase the first agent's reasoning; inspect the actual diff/code/tests and look for contradictory assumptions, missing edge cases, stale evidence, and unsafe operator dependencies.
- **ChatGPT:** project manager, cross-agent coordinator, safety/architecture acceptance, GitHub evidence integration, progress control, and user handoff only when unavoidable.
- **GitHub:** canonical project state and evidence source. Diff + CI + broker/runtime evidence outrank any agent narrative.
- **User:** operator of last resort for broker login, identity/authentication, funding/account actions, broker-side setting changes, and explicit approval of consequential real-money actions.

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

1. Primary agent implements from current canonical source.
2. Full relevant tests run locally or in the agent environment.
3. Independent second agent reviews the actual diff/code/tests from a clean perspective and tries to break assumptions.
4. Any finding is fixed and re-reviewed.
5. GitHub CI and secret scan pass on the exact proposed commit/PR.
6. ChatGPT verifies the evidence against the current roadmap and governing issue before merge/acceptance.
7. Real-money execution still requires separate explicit operator approval after fresh runtime gates are green.

For non-safety-critical documentation or low-risk refactors, one coding agent plus passing CI and ChatGPT verification may be sufficient.

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
