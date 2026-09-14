"""Read-only, fail-closed release-integrity gate for pull requests into main.

This script is advisory only:

- It never opens a broker connection and never sends, cancels, or modifies
  any order.
- It never posts a comment or review on the pull request.
- It never re-runs the test suite; that is protect-main's own required
  ``pytest`` check.
- ``LIVE_EXECUTION`` is always reported as the fixed literal ``NO-GO``.
  Nothing in this module can compute or assign any other value for it.

It checks three things that actually determine PASS/FAIL/UNKNOWN:

1. The checked-out commit is exactly the pull request's current head commit
   (not a synthetic merge commit and not a stale checkout).
2. The pull request's base branch is exactly ``main``.
3. The repository's default ``PlatformSettings`` still disables Live trading
   out of the box (``enable_live_trading is False`` and
   ``run_mode != "LIVE"``, i.e. ``live_trading_unlocked is False``).

Two more facts are looked up and printed for a human to read, but neither
one -- regardless of its value -- is ever allowed to change PASS/FAIL/UNKNOWN
on its own:

- The number of unresolved review threads on the pull request.
- Issue #255's current ``state`` (``"open"``/``"closed"``), printed as-is.
  Its body/checkboxes are never parsed and never used to authorize anything.

If a fact cannot be established at all (the GitHub API call fails, the
settings module cannot be imported, etc.) the gate reports ``UNKNOWN`` for
that fact rather than silently treating "unknown" as "fine".
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass

PASS = "PASS"
FAIL = "FAIL"
UNKNOWN = "UNKNOWN"

# This script contains no path that assigns any other value here. Live
# execution readiness is decided elsewhere, by explicit operator action, not
# by this read-only CI check.
LIVE_EXECUTION_VALUE = "NO-GO"

_GITHUB_API_TIMEOUT_SECONDS = 10
_ISSUE_255_NUMBER = 255


@dataclass(frozen=True)
class GateResult:
    status: str
    reasons: tuple[str, ...]


def check_exact_head(checked_out_sha: str, pr_head_sha: str | None) -> tuple[str, str]:
    """Fail unless the checked-out commit is exactly the PR's head commit."""
    expected = str(pr_head_sha or "").strip().lower()
    checked = str(checked_out_sha or "").strip().lower()
    if not expected:
        return FAIL, "PR head sha is missing from the event payload"
    if not checked:
        return FAIL, "checked-out git HEAD could not be determined"
    if checked != expected:
        return FAIL, f"checked-out sha {checked!r} does not match PR head sha {expected!r}"
    return PASS, f"checked-out sha matches PR head sha exactly ({checked})"


def check_base_branch(base_ref: str | None) -> tuple[str, str]:
    """Fail unless the pull request targets exactly ``main``."""
    normalized = str(base_ref or "").strip()
    if normalized != "main":
        return FAIL, f"base branch is {normalized!r}, expected 'main'"
    return PASS, "base branch is main"


def check_live_disabled_by_default(get_default_settings: Callable[[], object]) -> tuple[str, str]:
    """Fail unless the repository's default settings still disable Live trading."""
    try:
        settings = get_default_settings()
        enable_live_trading = settings.enable_live_trading
        run_mode = settings.run_mode
        live_trading_unlocked = settings.live_trading_unlocked
    except Exception as exc:  # noqa: BLE001 - any failure here means "can't verify"
        return UNKNOWN, f"could not evaluate default platform settings: {exc!r}"
    if not isinstance(enable_live_trading, bool) or not isinstance(run_mode, str):
        return UNKNOWN, "default platform settings have an unexpected shape"
    if enable_live_trading is not False or run_mode == "LIVE" or live_trading_unlocked is not False:
        return FAIL, (
            "default PlatformSettings no longer disables Live trading out of the box: "
            f"enable_live_trading={enable_live_trading!r} run_mode={run_mode!r} "
            f"live_trading_unlocked={live_trading_unlocked!r}"
        )
    return PASS, (
        "default PlatformSettings keeps Live trading disabled "
        f"(enable_live_trading={enable_live_trading!r}, run_mode={run_mode!r})"
    )


def fetch_unresolved_review_thread_count(
    *, repo: str, pr_number: int, token: str | None
) -> int | None:
    """Best-effort read-only lookup. Returns ``None`` on any failure."""
    owner, _, name = str(repo or "").partition("/")
    if not owner or not name or not pr_number or not token:
        return None
    query = """
    query($owner: String!, $name: String!, $number: Int!) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
          reviewThreads(first: 100) {
            nodes { isResolved }
          }
        }
      }
    }
    """
    payload = json.dumps(
        {"query": query, "variables": {"owner": owner, "name": name, "number": pr_number}}
    ).encode("utf-8")
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=payload,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "live-pilot-release-gate",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=_GITHUB_API_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    try:
        nodes = body["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    except (KeyError, TypeError):
        return None
    if not isinstance(nodes, list):
        return None
    return sum(1 for node in nodes if isinstance(node, dict) and node.get("isResolved") is False)


def fetch_issue_state(*, repo: str, issue_number: int, token: str | None) -> str | None:
    """Best-effort read-only lookup. Returns ``None`` on any failure.

    Only ``state`` is read. The issue body/checkboxes are never fetched for
    parsing here.
    """
    if not repo or not issue_number:
        return None
    url = f"https://api.github.com/repos/{repo}/issues/{issue_number}"
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "live-pilot-release-gate"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=_GITHUB_API_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    state = body.get("state") if isinstance(body, dict) else None
    return state if isinstance(state, str) else None


def evaluate_release_gate(
    *,
    checked_out_sha: str,
    pr_head_sha: str | None,
    base_ref: str | None,
    get_default_settings: Callable[[], object],
    unresolved_review_thread_count: int | None,
    issue_255_state: str | None,
) -> GateResult:
    """Combine every check into one PASS/FAIL/UNKNOWN verdict.

    The two display-only facts (unresolved review threads, Issue #255 state)
    never contribute PASS or FAIL based on their *value*. A failure to fetch
    either one (represented as ``None``) contributes UNKNOWN rather than
    being silently ignored, so an API outage cannot be mistaken for "clean".
    """
    reasons: list[str] = []
    statuses: list[str] = []

    status, reason = check_exact_head(checked_out_sha, pr_head_sha)
    statuses.append(status)
    reasons.append(f"exact-head: {reason}")

    status, reason = check_base_branch(base_ref)
    statuses.append(status)
    reasons.append(f"base-branch: {reason}")

    status, reason = check_live_disabled_by_default(get_default_settings)
    statuses.append(status)
    reasons.append(f"live-disabled-by-default: {reason}")

    if unresolved_review_thread_count is None:
        statuses.append(UNKNOWN)
        reasons.append(
            "unresolved-review-threads: UNKNOWN (could not query the GitHub API); "
            "display only -- the count itself never determines PASS/FAIL"
        )
    else:
        reasons.append(
            f"unresolved-review-threads: {unresolved_review_thread_count} "
            "(display only, does not affect gate status)"
        )

    if issue_255_state is None:
        statuses.append(UNKNOWN)
        reasons.append(
            "issue-255-state: UNKNOWN (could not query the GitHub API); "
            "display only -- never parsed for an automatic GO decision"
        )
    else:
        reasons.append(
            f"issue-255-state: {issue_255_state} "
            "(display only, never parsed for an automatic GO decision)"
        )

    if FAIL in statuses:
        overall = FAIL
    elif UNKNOWN in statuses:
        overall = UNKNOWN
    else:
        overall = PASS
    return GateResult(status=overall, reasons=tuple(reasons))


def _git_head_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def _load_event_payload() -> dict:
    path = os.environ.get("GITHUB_EVENT_PATH")
    if not path or not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def main() -> int:
    event = _load_event_payload()
    pull_request = event.get("pull_request")
    pull_request = pull_request if isinstance(pull_request, dict) else {}

    head = pull_request.get("head")
    pr_head_sha = head.get("sha") if isinstance(head, dict) else None

    base = pull_request.get("base")
    base_ref = base.get("ref") if isinstance(base, dict) else None

    pr_number = pull_request.get("number")

    try:
        checked_out_sha = _git_head_sha()
    except (subprocess.CalledProcessError, OSError) as exc:
        checked_out_sha = ""
        print(f"could not determine checked-out git HEAD: {exc}", file=sys.stderr)

    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY", "")

    unresolved_count = (
        fetch_unresolved_review_thread_count(repo=repo, pr_number=pr_number, token=token)
        if isinstance(pr_number, int)
        else None
    )
    issue_state = fetch_issue_state(repo=repo, issue_number=_ISSUE_255_NUMBER, token=token)

    from ai_asset_platform.core.settings import PlatformSettings

    result = evaluate_release_gate(
        checked_out_sha=checked_out_sha,
        pr_head_sha=pr_head_sha,
        base_ref=base_ref,
        get_default_settings=PlatformSettings,
        unresolved_review_thread_count=unresolved_count,
        issue_255_state=issue_state,
    )

    for reason in result.reasons:
        print(reason)
    print(f"RELEASE_INTEGRITY_GATE={result.status}")
    print(f"LIVE_EXECUTION={LIVE_EXECUTION_VALUE}")

    return 0 if result.status == PASS else 1


if __name__ == "__main__":
    sys.exit(main())
