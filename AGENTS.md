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

- **Claude Code / primary implementation agent and default day-to-day progress/critical-path owner:** preserve implementation continuity, inspect current repository state, implement the smallest safe blocker-closing change, add/repair tests, run local/relevant tests, review its own diff, verify evidence against the current roadmap and governing issue, and leave concrete evidence.
- **Codex / independent second reviewer:** do not duplicate Claude's full implementation by default. For safety-critical trading changes, independently inspect the actual diff/code/tests and try to break assumptions. Codex may implement only when explicitly delegated because Claude is blocked or when the task is clearly separable and non-overlapping. Remains structurally independent of Claude Code regardless of any other role change.
- **ChatGPT:** optional advisory role only, consulted by explicit user request for a specific bounded question. Not part of the default implementation, acceptance, or merge-gate loop, and must not insert itself into that loop unasked. (Changed 2026-10-09, user-confirmed, after repeated user-documented instances of ChatGPT not following instructions, scope creep beyond critical path, and acceptance judgments the user found unreliable.)
- **GitHub:** canonical project state and evidence source. Diff + CI + broker/runtime evidence outrank any agent narrative.
- **User:** operator of last resort for broker login, identity/authentication, funding/account actions, broker-side setting changes, and explicit approval of consequential real-money actions. Also the final merge/acceptance authority formerly routed through ChatGPT's evidence-verification step; Claude Code's own evidence report plus Codex's independent review (for safety-critical work) now stand in its place, subject to the user's own merge decision.

Do not change the primary-agent role or introduce another development process without an explicit user decision recorded in the canonical project documents.

## GitHub read/write authority

Repository agents may independently use GitHub read-only evidence (including local `gh` or API access) to inspect exact HEAD/base SHA, diffs, CI, review threads, Issues, workflow results, and main drift.

No agent may perform a GitHub write merely because it has technical credentials. A fresh, explicit user authorization is required for the specific write action. This includes merge/auto-merge, `git push`, remote branch/tag changes, PR/Issue creation or mutation, comments/reviews/thread resolution, and repository-setting changes.

A reviewer or Claude GO/NO-GO verdict is advisory evidence, not merge permission. The final merge operation requires separate explicit user authorization after the required exact-HEAD gates are verified.

GitHub read access also grants no broker-write or Live-trading authority.

### Standing autonomous-mode authorization (2026-10-03, user-confirmed)

The user has given standing (not per-instance) authorization for Claude Code to run, without stopping to ask first: read-only repo/GitHub/canonical-doc investigation; Phase/critical-path checks; A/B/C classification; A-blocker root-cause analysis; the smallest fix on a feature branch; running relevant tests; `git push` of follow-up commits to that same feature branch (never `main`); opening the one PR for that fix and pushing further commits to it in response to review feedback (never changing that PR's base branch, reviewers, or other metadata, and never opening or mutating any other PR or Issue); monitoring CI; requesting Codex's independent review on the exact PR HEAD; and, if Codex finds a genuine A blocker, fixing it and repeating this same test/push/CI/review cycle.

This standing authorization never extends to: merge/rebase/squash/auto-merge; Live orders; Paper orders; any other broker write; cancel/modify/retry/flatten/close; removal of broker Read-Only; deposits or withdrawals; FX conversion; credential or security-setting changes; Trading Permission changes; paid market-data subscriptions; dangerous TWS/Gateway configuration changes, restarts, or logouts; relaxing any risk limit or safety gate; or adding/changing any completion condition, Phase, or critical-path item. Every one of those still requires a fresh, per-action explicit user authorization, exactly as before this note was added.

## Independent audit minimum evidence

Before any GO/NO-GO or acceptance decision, independently verify the current `main`, exact proposed HEAD, relevant diff, current exact-head CI, unresolved non-outdated review threads, governing Issue/checklist, and safety invariants. Do not treat an agent's self-report as proof. If the current session cannot directly access a required source, mark that evidence `UNVERIFIED` and state the limitation.

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
6. Claude Code verifies the evidence against the current roadmap and governing issue and presents it to the user before merge/acceptance; the user makes the final merge/acceptance decision.
7. Real-money execution still requires separate explicit operator approval after fresh runtime gates are green.

For non-safety-critical documentation or low-risk refactors, Claude Code or another single coding agent plus passing CI is sufficient; Codex review is not automatically required.

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
