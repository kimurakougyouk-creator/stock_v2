"""Read-only, fail-closed release-integrity gate for pull requests into main.

This script is advisory only:

- It never opens a broker connection and never sends, cancels, or modifies
  any order.
- It never posts a comment or review on the pull request.
- It never re-runs the test suite; that is protect-main's own required
  ``pytest`` check.
- ``LIVE_EXECUTION`` is always reported as the fixed literal ``NO-GO``.
  Nothing in this module can compute or assign any other value for it.

This job runs under ``pull_request_target`` and checks out only the trusted
base (main), never the PR's own branch/commits -- so a PR cannot modify this
gate's own behavior (this script, the workflow file, or the settings module
it reads) and have that modified version run against itself. Accordingly:

It checks five things that actually determine PASS/FAIL/UNKNOWN:

1. The PR's head sha was recognized: the event payload gave us a non-empty,
   well-formed 40-character hex commit sha to identify the PR commit by.
   This does NOT check out or inspect that commit's code in any way.
2. The checked-out commit (always main/base, never the PR) is exactly the
   base commit the event payload says main was at when the run started.
3. The pull request's base branch is exactly ``main``.
4. The repository's default ``PlatformSettings`` -- imported from this
   trusted base checkout, never from the PR -- still disables Live trading
   out of the box (``enable_live_trading is False`` and
   ``run_mode != "LIVE"``, i.e. ``live_trading_unlocked is False``).
5. The PR does not modify ``src/ai_asset_platform/core/settings.py`` at all.
   This is a blunt, content-blind rejection (scoped to this one file for
   now): a PR that touches the file defining the Live-safety defaults is
   never inspected for whether the change looks safe, it is simply rejected.

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

# The single file this gate currently protects against unreviewed PR edits.
# Scope is deliberately limited to this one file for now; extending this to
# the gate's own workflow/script (or other protected paths) is a separate,
# later change.
_LIVE_SAFETY_SETTINGS_PATH = "src/ai_asset_platform/core/settings.py"

# GitHub's "List pull request files" endpoint returns at most this many
# files for a single PR, however many pages that spans, and silently stops
# paginating beyond it -- it does not error. A listing derived from it can
# therefore never be proven complete for a PR that changed more files than
# this, regardless of how many pages are fetched.
_MAX_FILES_PER_PR = 3000
_FILES_PER_PAGE = 100
_MAX_PR_FILES_PAGES = _MAX_FILES_PER_PR // _FILES_PER_PAGE


@dataclass(frozen=True)
class GateResult:
    status: str
    reasons: tuple[str, ...]


def _is_well_formed_git_sha(value: str) -> bool:
    return len(value) == 40 and all(ch in "0123456789abcdef" for ch in value)


def check_pr_head_sha_present(pr_head_sha: str | None) -> tuple[str, str]:
    """Verify the PR's head sha was recognized from the event payload.

    This job intentionally never checks out the PR's own branch/commits (see
    the module docstring and ``check_checked_out_matches_expected_base``
    below for what actually gets checked out and verified: the trusted base
    commit). So this check does NOT -- and cannot -- prove that any
    checked-out code equals the PR's head commit. It only confirms that the
    ``pull_request_target`` event payload gave us a non-empty, well-formed
    40-character hex commit sha to identify which PR commit this run is
    about.
    """
    candidate = str(pr_head_sha or "").strip()
    if not candidate:
        return FAIL, "PR head sha is missing from the event payload"
    if not _is_well_formed_git_sha(candidate.lower()):
        return FAIL, f"PR head sha {candidate!r} is not a well-formed 40-character hex commit sha"
    return PASS, f"PR head sha is present and well-formed ({candidate.lower()})"


def check_checked_out_matches_expected_base(
    checked_out_sha: str, expected_base_sha: str | None
) -> tuple[str, str]:
    """Verify the checked-out commit is exactly the PR's base commit.

    This job's checkout step deliberately checks out the trusted base
    (main), never the PR's branch/commits. This proves that trusted checkout
    is exactly the commit the ``pull_request_target`` event payload says the
    base was at -- not a stale, unexpected, or (were the trigger ever
    changed back) PR-controlled commit -- rather than proving anything about
    the PR's own code.
    """
    expected = str(expected_base_sha or "").strip().lower()
    checked = str(checked_out_sha or "").strip().lower()
    if not expected:
        return UNKNOWN, "expected base sha (event payload's pull_request.base.sha) is missing"
    if checked and checked == expected:
        return PASS, f"checked-out sha matches the expected base sha exactly ({checked})"
    return FAIL, f"checked-out sha {checked!r} does not match expected base sha {expected!r}"


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


def check_settings_file_not_modified_by_pr(
    *, changed_file_paths: list[str] | None
) -> tuple[str, str]:
    """Fail closed if the PR touches the Live-safety defaults file.

    ``src/ai_asset_platform/core/settings.py`` defines the repository-wide
    default that keeps Live trading disabled out of the box
    (``enable_live_trading``, ``run_mode``, ``live_trading_unlocked``, and
    the derived ``live_trading_unlocked`` property). This check does not
    inspect *what* changed in that file -- any change at all is rejected
    without content review, because even an apparently benign edit could
    flip a default this gate (and the rest of the Live-pilot safety chain)
    relies on.
    """
    if changed_file_paths is None:
        return UNKNOWN, "the PR's changed-file list could not be retrieved from the GitHub API"
    if _LIVE_SAFETY_SETTINGS_PATH in changed_file_paths:
        return FAIL, (
            f"the PR modifies {_LIVE_SAFETY_SETTINGS_PATH!r}, which defines the Live-safety "
            "defaults this gate checks, so this gate rejects it without inspecting the "
            "content of the change. To pass this check, split the PR so it does not touch "
            "this file, or route the change through an explicit safety-review path for this "
            "file -- no such path exists yet as of this gate's current scope"
        )
    return PASS, f"the PR does not modify {_LIVE_SAFETY_SETTINGS_PATH!r}"


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


def _next_page_url(link_header: str | None) -> str | None:
    """Extract the ``rel="next"`` URL from a GitHub API ``Link`` response header."""
    if not link_header:
        return None
    for part in link_header.split(","):
        segment = part.strip()
        if 'rel="next"' not in segment:
            continue
        start = segment.find("<")
        end = segment.find(">", start + 1)
        if start != -1 and end != -1:
            return segment[start + 1 : end]
    return None


def _fetch_pr_metadata(*, repo: str, pr_number: int, token: str | None) -> tuple[int, str] | None:
    """Best-effort read-only lookup of the PR's ``changed_files`` and ``head.sha``.

    This is the PR metadata endpoint's own tally/identity, independent of
    the paginated files listing below. It is the only way to prove that
    listing is both complete and about the exact commit this run cares
    about, so any doubt here -- a failed request, malformed JSON, a missing
    key, a ``changed_files`` that is not a non-negative non-boolean int, or
    a ``head.sha`` that is not a well-formed 40-character hex commit sha --
    must return ``None`` rather than a guessed value.
    """
    owner, _, name = str(repo or "").partition("/")
    if not owner or not name or not pr_number or not token:
        return None
    url = f"https://api.github.com/repos/{owner}/{name}/pulls/{pr_number}"
    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "live-pilot-release-gate",
    }
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=_GITHUB_API_TIMEOUT_SECONDS) as response:
            body = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None
    if not isinstance(body, dict):
        return None
    count = body.get("changed_files")
    if not isinstance(count, int) or isinstance(count, bool) or count < 0:
        return None
    head = body.get("head")
    head_sha = head.get("sha") if isinstance(head, dict) else None
    if not isinstance(head_sha, str) or not _is_well_formed_git_sha(head_sha.strip().lower()):
        return None
    return count, head_sha.strip().lower()


def fetch_pr_changed_file_paths(
    *, repo: str, pr_number: int, token: str | None, expected_pr_head_sha: str | None
) -> list[str] | None:
    """Best-effort read-only lookup of every file path changed by the PR.

    Returns ``None`` -- never a partial, truncated, or otherwise doubtful
    list -- unless completeness can actually be proven:

    - PR metadata (``changed_files`` and ``head.sha``) must be established
      both before and after the paginated files fetch (see
      ``_fetch_pr_metadata``);
    - both metadata reads' ``head.sha`` must exactly equal
      ``expected_pr_head_sha`` (the ``pull_request_target`` event payload's
      own head sha) -- this binds the fetched file list to the exact commit
      this run is evaluating, so a PR pushed to mid-run cannot have its
      files inspected under a stale identity;
    - both metadata reads' ``changed_files`` must agree with each other, and
      must not exceed the files API's hard 3000-file ceiling (beyond that,
      no amount of pagination can prove completeness);
    - every page of the paginated files listing must be fetched within the
      page budget implied by that ceiling;
    - every entry on every page must be a dict with a non-empty string
      ``filename`` -- a single malformed entry invalidates the whole
      listing rather than being silently skipped;
    - the collected filenames must contain no duplicates; and
    - the final count of collected filenames must exactly equal the
      reported ``changed_files`` count.

    Any of these failing means completeness (or head-sha identity) cannot
    be proven, so the whole result is ``None`` -- never a partial list, and
    never a list about a different commit than the caller asked about.
    """
    owner, _, name = str(repo or "").partition("/")
    if not owner or not name or not pr_number or not token:
        return None

    expected_head_sha = str(expected_pr_head_sha or "").strip().lower()
    if not expected_head_sha:
        return None

    before = _fetch_pr_metadata(repo=repo, pr_number=pr_number, token=token)
    if before is None:
        return None
    expected_count, head_sha_before = before
    if head_sha_before != expected_head_sha:
        return None
    if expected_count > _MAX_FILES_PER_PR:
        return None

    headers = {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "User-Agent": "live-pilot-release-gate",
    }
    paths: list[str] = []
    url: str | None = (
        f"https://api.github.com/repos/{owner}/{name}/pulls/{pr_number}/files"
        f"?per_page={_FILES_PER_PAGE}"
    )
    pages_fetched = 0
    while url:
        if pages_fetched >= _MAX_PR_FILES_PAGES:
            return None
        request = urllib.request.Request(url, headers=headers, method="GET")
        try:
            with urllib.request.urlopen(request, timeout=_GITHUB_API_TIMEOUT_SECONDS) as response:
                body = json.loads(response.read().decode("utf-8"))
                link_header = response.headers.get("Link")
        except (urllib.error.URLError, TimeoutError, ValueError, OSError):
            return None
        if not isinstance(body, list):
            return None
        for entry in body:
            if not isinstance(entry, dict):
                return None
            filename = entry.get("filename")
            if not isinstance(filename, str) or not filename:
                return None
            paths.append(filename)
        pages_fetched += 1
        url = _next_page_url(link_header)

    after = _fetch_pr_metadata(repo=repo, pr_number=pr_number, token=token)
    if after is None:
        return None
    count_after, head_sha_after = after
    if head_sha_after != expected_head_sha:
        return None
    if head_sha_after != head_sha_before:
        return None
    if count_after != expected_count:
        return None

    if len(set(paths)) != len(paths):
        return None
    if len(paths) != expected_count:
        return None
    return paths


def evaluate_release_gate(
    *,
    checked_out_sha: str,
    pr_head_sha: str | None,
    base_ref: str | None,
    expected_base_sha: str | None,
    get_default_settings: Callable[[], object],
    changed_file_paths: list[str] | None,
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

    status, reason = check_pr_head_sha_present(pr_head_sha)
    statuses.append(status)
    reasons.append(f"pr-head-sha-present: {reason}")

    status, reason = check_checked_out_matches_expected_base(checked_out_sha, expected_base_sha)
    statuses.append(status)
    reasons.append(f"checked-out-matches-base: {reason}")

    status, reason = check_base_branch(base_ref)
    statuses.append(status)
    reasons.append(f"base-branch: {reason}")

    status, reason = check_live_disabled_by_default(get_default_settings)
    statuses.append(status)
    reasons.append(f"live-disabled-by-default: {reason}")

    status, reason = check_settings_file_not_modified_by_pr(changed_file_paths=changed_file_paths)
    statuses.append(status)
    reasons.append(f"settings-file-not-modified: {reason}")

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


def _load_platform_settings() -> object:
    """Import and construct the repository's default ``PlatformSettings``.

    Kept as a lazy loader (rather than importing at module scope) so an
    import failure -- ``ModuleNotFoundError``/``ImportError`` included --
    surfaces through ``check_live_disabled_by_default``'s own
    ``except Exception`` as UNKNOWN, instead of crashing the whole script
    with an unhandled traceback before the gate can print its verdict.
    """
    from ai_asset_platform.core.settings import PlatformSettings

    return PlatformSettings()


def main() -> int:
    event = _load_event_payload()
    pull_request = event.get("pull_request")
    pull_request = pull_request if isinstance(pull_request, dict) else {}

    head = pull_request.get("head")
    pr_head_sha = head.get("sha") if isinstance(head, dict) else None

    base = pull_request.get("base")
    base_ref = base.get("ref") if isinstance(base, dict) else None
    expected_base_sha = base.get("sha") if isinstance(base, dict) else None

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
    changed_file_paths = (
        fetch_pr_changed_file_paths(
            repo=repo,
            pr_number=pr_number,
            token=token,
            expected_pr_head_sha=pr_head_sha,
        )
        if isinstance(pr_number, int)
        else None
    )

    result = evaluate_release_gate(
        checked_out_sha=checked_out_sha,
        pr_head_sha=pr_head_sha,
        base_ref=base_ref,
        expected_base_sha=expected_base_sha,
        get_default_settings=_load_platform_settings,
        changed_file_paths=changed_file_paths,
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
