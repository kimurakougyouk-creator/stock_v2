"""Read-only, fail-closed release-integrity gate for PRs into main.

The workflow runs from trusted base code under ``pull_request_target``. PR
code is never checked out, imported, or executed. The protected settings path
is inspected only as Git object metadata at immutable base/head commit SHAs.
``LIVE_EXECUTION`` is always the fixed literal ``NO-GO``.
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
LIVE_EXECUTION_VALUE = "NO-GO"

_GITHUB_API_TIMEOUT_SECONDS = 10
_ISSUE_255_NUMBER = 255
_LIVE_SAFETY_SETTINGS_PATH = "src/ai_asset_platform/core/settings.py"
_LOOKUP_FOUND = "FOUND"
_LOOKUP_MISSING = "MISSING"
_LOOKUP_UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class GateResult:
    status: str
    reasons: tuple[str, ...]


@dataclass(frozen=True)
class GitTreeEntryLookup:
    state: str
    mode: str | None = None
    object_type: str | None = None
    object_sha: str | None = None


def _normalized_sha(value: str | None) -> str:
    return str(value or "").strip().lower()


def _is_well_formed_git_sha(value: str) -> bool:
    return len(value) == 40 and all(ch in "0123456789abcdef" for ch in value)


def check_pr_head_sha_present(pr_head_sha: str | None) -> tuple[str, str]:
    candidate = _normalized_sha(pr_head_sha)
    if not candidate:
        return FAIL, "PR head sha is missing from the event payload"
    if not _is_well_formed_git_sha(candidate):
        return (
            FAIL,
            f"PR head sha {str(pr_head_sha)!r} is not a well-formed 40-character "
            "hex commit sha",
        )
    return PASS, f"PR head sha is present and well-formed ({candidate})"


def check_checked_out_matches_expected_base(
    checked_out_sha: str, expected_base_sha: str | None
) -> tuple[str, str]:
    expected = _normalized_sha(expected_base_sha)
    checked = _normalized_sha(checked_out_sha)
    if not expected:
        return UNKNOWN, "expected base sha (event payload's pull_request.base.sha) is missing"
    if not _is_well_formed_git_sha(expected):
        return UNKNOWN, "expected base sha is not a well-formed 40-character hex commit sha"
    if checked and checked == expected:
        return PASS, f"checked-out sha matches the expected base sha exactly ({checked})"
    return FAIL, f"checked-out sha {checked!r} does not match expected base sha {expected!r}"


def check_base_branch(base_ref: str | None) -> tuple[str, str]:
    normalized = str(base_ref or "").strip()
    if normalized != "main":
        return FAIL, f"base branch is {normalized!r}, expected 'main'"
    return PASS, "base branch is main"


def check_live_disabled_by_default(get_default_settings: Callable[[], object]) -> tuple[str, str]:
    try:
        settings = get_default_settings()
        enabled = settings.enable_live_trading
        run_mode = settings.run_mode
        unlocked = settings.live_trading_unlocked
    except Exception as exc:  # noqa: BLE001 - inability to verify must be UNKNOWN
        return UNKNOWN, f"could not evaluate default platform settings: {exc!r}"
    if not isinstance(enabled, bool) or not isinstance(run_mode, str):
        return UNKNOWN, "default platform settings have an unexpected shape"
    if enabled is not False or run_mode == "LIVE" or unlocked is not False:
        return FAIL, (
            "default PlatformSettings no longer disables Live trading out of the box: "
            f"enable_live_trading={enabled!r} run_mode={run_mode!r} "
            f"live_trading_unlocked={unlocked!r}"
        )
    return PASS, (
        "default PlatformSettings keeps Live trading disabled "
        f"(enable_live_trading={enabled!r}, run_mode={run_mode!r})"
    )


def _github_get_json(url: str, *, token: str | None) -> tuple[str, object | None]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "live-pilot-release-gate",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=_GITHUB_API_TIMEOUT_SECONDS) as response:
            return _LOOKUP_FOUND, json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        return (_LOOKUP_MISSING if exc.code == 404 else _LOOKUP_UNKNOWN), None
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return _LOOKUP_UNKNOWN, None


def fetch_git_tree_entry_at_exact_ref(
    *, repo: str, path: str, ref_sha: str | None, token: str | None
) -> GitTreeEntryLookup:
    """Locate one path in one immutable commit tree, never via mutable PR APIs."""
    owner, separator, name = str(repo or "").partition("/")
    ref = _normalized_sha(ref_sha)
    path = str(path or "").strip("/")
    if (
        not owner
        or separator != "/"
        or not name
        or not path
        or not token
        or not _is_well_formed_git_sha(ref)
    ):
        return GitTreeEntryLookup(_LOOKUP_UNKNOWN)

    commit_url = f"https://api.github.com/repos/{owner}/{name}/git/commits/{ref}"
    state, body = _github_get_json(commit_url, token=token)
    if state != _LOOKUP_FOUND or not isinstance(body, dict):
        return GitTreeEntryLookup(_LOOKUP_UNKNOWN)

    returned_commit_sha = body.get("sha")
    if not isinstance(returned_commit_sha, str) or not _is_well_formed_git_sha(
        returned_commit_sha
    ):
        return GitTreeEntryLookup(_LOOKUP_UNKNOWN)
    if returned_commit_sha != ref:
        return GitTreeEntryLookup(_LOOKUP_UNKNOWN)

    tree = body.get("tree")
    tree_sha = tree.get("sha") if isinstance(tree, dict) else None
    if not isinstance(tree_sha, str) or not _is_well_formed_git_sha(tree_sha):
        return GitTreeEntryLookup(_LOOKUP_UNKNOWN)

    tree_url = f"https://api.github.com/repos/{owner}/{name}/git/trees/{tree_sha}?recursive=1"
    state, body = _github_get_json(tree_url, token=token)
    if state != _LOOKUP_FOUND or not isinstance(body, dict):
        return GitTreeEntryLookup(_LOOKUP_UNKNOWN)

    returned_tree_sha = body.get("sha")
    if not isinstance(returned_tree_sha, str) or not _is_well_formed_git_sha(returned_tree_sha):
        return GitTreeEntryLookup(_LOOKUP_UNKNOWN)
    if returned_tree_sha != tree_sha:
        return GitTreeEntryLookup(_LOOKUP_UNKNOWN)
    if body.get("truncated") is not False:
        return GitTreeEntryLookup(_LOOKUP_UNKNOWN)

    entries = body.get("tree")
    if not isinstance(entries, list):
        return GitTreeEntryLookup(_LOOKUP_UNKNOWN)

    matches: list[dict] = []
    for entry in entries:
        if not isinstance(entry, dict) or not isinstance(entry.get("path"), str):
            return GitTreeEntryLookup(_LOOKUP_UNKNOWN)
        if entry["path"] == path:
            matches.append(entry)

    if not matches:
        return GitTreeEntryLookup(_LOOKUP_MISSING)
    if len(matches) != 1:
        return GitTreeEntryLookup(_LOOKUP_UNKNOWN)

    entry = matches[0]
    mode, object_type, object_sha = entry.get("mode"), entry.get("type"), entry.get("sha")
    if not all(isinstance(value, str) for value in (mode, object_type, object_sha)):
        return GitTreeEntryLookup(_LOOKUP_UNKNOWN)
    if not _is_well_formed_git_sha(object_sha):
        return GitTreeEntryLookup(_LOOKUP_UNKNOWN)
    return GitTreeEntryLookup(_LOOKUP_FOUND, mode, object_type, object_sha)


def check_settings_file_unchanged_between_exact_refs(
    *,
    base_sha: str | None,
    head_sha: str | None,
    base_lookup: GitTreeEntryLookup,
    head_lookup: GitTreeEntryLookup,
) -> tuple[str, str]:
    """Compare exact Git identity; missing head covers delete and rename-away."""
    base_ref, head_ref = _normalized_sha(base_sha), _normalized_sha(head_sha)
    if not _is_well_formed_git_sha(base_ref) or not _is_well_formed_git_sha(head_ref):
        return (
            UNKNOWN,
            "base/head sha is missing or malformed; protected-file identity is unverified",
        )
    if base_lookup.state != _LOOKUP_FOUND or base_lookup.object_type != "blob":
        return UNKNOWN, (
            f"could not establish {_LIVE_SAFETY_SETTINGS_PATH!r} as a normal Git blob at "
            f"exact base sha {base_ref}"
        )
    if head_lookup.state == _LOOKUP_MISSING:
        return FAIL, (
            f"{_LIVE_SAFETY_SETTINGS_PATH!r} is missing at exact PR head sha {head_ref}; "
            "delete or rename-away is rejected"
        )
    if head_lookup.state != _LOOKUP_FOUND:
        return UNKNOWN, (
            f"could not establish {_LIVE_SAFETY_SETTINGS_PATH!r} identity at exact PR "
            f"head sha {head_ref}"
        )
    if head_lookup.object_type != "blob":
        return (
            FAIL,
            "protected settings path is no longer a normal Git blob at the exact PR head sha",
        )

    base_identity = (base_lookup.mode, base_lookup.object_type, base_lookup.object_sha)
    head_identity = (head_lookup.mode, head_lookup.object_type, head_lookup.object_sha)
    if base_identity != head_identity:
        return FAIL, (
            f"the PR changes {_LIVE_SAFETY_SETTINGS_PATH!r} between immutable base/head refs; "
            f"base_identity={base_identity!r} head_identity={head_identity!r}"
        )
    return PASS, (
        f"{_LIVE_SAFETY_SETTINGS_PATH!r} has identical mode/type/blob sha at exact "
        "base/head refs"
    )


def fetch_unresolved_review_thread_count(
    *, repo: str, pr_number: int, token: str | None
) -> int | None:
    owner, _, name = str(repo or "").partition("/")
    if not owner or not name or not pr_number or not token:
        return None
    query = """
    query($owner: String!, $name: String!, $number: Int!) {
      repository(owner: $owner, name: $name) {
        pullRequest(number: $number) {
          reviewThreads(first: 100) { nodes { isResolved } }
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
        nodes = body["data"]["repository"]["pullRequest"]["reviewThreads"]["nodes"]
    except (urllib.error.URLError, TimeoutError, ValueError, OSError, KeyError, TypeError):
        return None
    if not isinstance(nodes, list):
        return None
    return sum(1 for node in nodes if isinstance(node, dict) and node.get("isResolved") is False)


def fetch_issue_state(*, repo: str, issue_number: int, token: str | None) -> str | None:
    if not repo or not issue_number:
        return None
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "live-pilot-release-gate",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/issues/{issue_number}",
        headers=headers,
        method="GET",
    )
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
    expected_base_sha: str | None,
    get_default_settings: Callable[[], object],
    settings_base_lookup: GitTreeEntryLookup,
    settings_head_lookup: GitTreeEntryLookup,
    unresolved_review_thread_count: int | None,
    issue_255_state: str | None,
) -> GateResult:
    reasons: list[str] = []
    statuses: list[str] = []

    checks = (
        ("pr-head-sha-present", check_pr_head_sha_present(pr_head_sha)),
        (
            "checked-out-matches-base",
            check_checked_out_matches_expected_base(checked_out_sha, expected_base_sha),
        ),
        ("base-branch", check_base_branch(base_ref)),
        ("live-disabled-by-default", check_live_disabled_by_default(get_default_settings)),
        (
            "settings-file-unchanged",
            check_settings_file_unchanged_between_exact_refs(
                base_sha=expected_base_sha,
                head_sha=pr_head_sha,
                base_lookup=settings_base_lookup,
                head_lookup=settings_head_lookup,
            ),
        ),
    )
    for label, (status, reason) in checks:
        statuses.append(status)
        reasons.append(f"{label}: {reason}")

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

    overall = FAIL if FAIL in statuses else UNKNOWN if UNKNOWN in statuses else PASS
    return GateResult(overall, tuple(reasons))


def _git_head_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
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
    settings_base_lookup = fetch_git_tree_entry_at_exact_ref(
        repo=repo, path=_LIVE_SAFETY_SETTINGS_PATH, ref_sha=expected_base_sha, token=token
    )
    settings_head_lookup = fetch_git_tree_entry_at_exact_ref(
        repo=repo, path=_LIVE_SAFETY_SETTINGS_PATH, ref_sha=pr_head_sha, token=token
    )

    result = evaluate_release_gate(
        checked_out_sha=checked_out_sha,
        pr_head_sha=pr_head_sha,
        base_ref=base_ref,
        expected_base_sha=expected_base_sha,
        get_default_settings=_load_platform_settings,
        settings_base_lookup=settings_base_lookup,
        settings_head_lookup=settings_head_lookup,
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
