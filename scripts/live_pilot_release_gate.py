"""Read-only, fail-closed release-integrity gate for PRs into main.

The workflow runs from trusted base code under ``pull_request_target``. PR
code is never checked out, imported, or executed. The protected settings
path, its package initialization/import context (``ai_asset_platform`` and
``ai_asset_platform.core``'s own ``__init__.py``), and every path in
``_FORBIDDEN_HEAD_ONLY_PATHS`` (stdlib-shadow modules, Python startup
hooks, and a settings-module-shadowing package) are all inspected only as
Git object metadata at immutable base/head commit SHAs -- an unchanged
settings.py blob alone does not prove head's runtime behavior is
unchanged, since importing it can be preceded or intercepted by any of
these without touching settings.py's own bytes: a package initializer that
imports settings.py and then replaces its class or singleton (or
pre-populates ``sys.modules`` with a fake module), a Python startup hook
that runs before this project's own code, or a same-named package that
Python resolves ahead of the settings module itself. ``LIVE_EXECUTION`` is
always the fixed literal ``NO-GO``.
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

# Importing ``ai_asset_platform.core.settings`` first runs these package
# initializers, in this order, before settings.py's own module body ever
# executes. Either one can import settings.py itself and then replace its
# ``PlatformSettings`` class or ``SETTINGS`` singleton (or pre-populate
# ``sys.modules`` with an entirely fake settings module) -- so an unchanged
# settings.py blob alone does not prove head's runtime behavior is
# unchanged. Both must be identical to base for that proof to hold.
_PACKAGE_INIT_CONTEXT_PATHS: tuple[str, ...] = (
    "src/ai_asset_platform/__init__.py",
    "src/ai_asset_platform/core/__init__.py",
)

# Paths where a repo-controlled file would sit on sys.path ahead of the
# real stdlib module for `from dataclasses import dataclass, field` inside
# settings.py, given this project's actual invocation
# (PYTHONPATH=src, `python scripts/live_pilot_release_gate.py` or
# `pytest`, which both place `src/` on sys.path before the stdlib default
# paths). `dataclasses` is an ordinary stdlib module -- not part of
# Python's interpreter bootstrap -- so it is not yet in `sys.modules` when
# settings.py's import statement runs, and a repo-controlled module at
# either of these paths would be imported instead of the real one.
# Confirmed empirically for this project; their *absence* at head is the
# safety condition, so any appearance at head is rejected outright.
#
# `src/os.py` / `src/os/__init__.py` are deliberately NOT included: `os`
# is unconditionally imported into `sys.modules` during CPython's own
# interpreter bootstrap (via `site`), before any user script or test runs
# in this project -- confirmed empirically, not assumed -- so no
# repo-controlled path anywhere on sys.path can ever shadow it here.
_FORBIDDEN_STDLIB_SHADOW_PATHS: tuple[str, ...] = (
    "src/dataclasses.py",
    "src/dataclasses/__init__.py",
)

# ``sitecustomize``/``usercustomize`` are Python's own site-initialization
# hooks: if either is importable, the interpreter imports it automatically
# very early on startup, before this project's own code (including this
# gate script and settings.py) ever runs. With PYTHONPATH=src, `src/` is on
# sys.path at that point, so a repo-controlled hook here could install an
# import hook or pre-populate `sys.modules["ai_asset_platform.core.settings"]`
# with a fake module before the real one is ever imported -- reachable via
# this project's actual startup method, confirmed the same way as the
# stdlib-shadow paths above (not assumed).
_FORBIDDEN_STARTUP_HOOK_PATHS: tuple[str, ...] = (
    "src/sitecustomize.py",
    "src/sitecustomize/__init__.py",
    "src/usercustomize.py",
    "src/usercustomize/__init__.py",
)

# Python resolves a package (a directory with __init__.py) ahead of a
# sibling module of the same name in the same parent package. A newly
# added ``src/ai_asset_platform/core/settings/__init__.py`` would therefore
# be imported instead of the sibling ``src/ai_asset_platform/core/settings.py``
# for `ai_asset_platform.core.settings`, regardless of whether settings.py
# itself is unchanged -- its initializer can define an arbitrary
# ``PlatformSettings``/``SETTINGS``.
_FORBIDDEN_SETTINGS_PACKAGE_SHADOW_PATHS: tuple[str, ...] = (
    "src/ai_asset_platform/core/settings/__init__.py",
)

# Every path above shares the same safety semantics: it must not exist at
# all at the PR's head commit, regardless of base. Combined here so the
# same generic fetch/check wiring covers all of them.
_FORBIDDEN_HEAD_ONLY_PATHS: tuple[str, ...] = (
    *_FORBIDDEN_STDLIB_SHADOW_PATHS,
    *_FORBIDDEN_STARTUP_HOOK_PATHS,
    *_FORBIDDEN_SETTINGS_PACKAGE_SHADOW_PATHS,
)

# The complete, closed set of Git tree entry modes with defined meaning for
# a blob/tree object: 100644 (normal file), 100755 (executable file),
# 120000 (symbolic link), 160000 (submodule/gitlink), 040000 (subtree). Any
# other string is not a Git mode this gate can reason about, so it must
# never be treated as equal to another arbitrary string just because both
# sides of a base/head comparison happen to match.
_KNOWN_GIT_TREE_MODES = frozenset({"100644", "100755", "120000", "160000", "040000"})

# Each known mode has exactly one coherent Git object type. A mode being
# individually allowlisted is not sufficient on its own: e.g. mode="040000"
# (subtree) paired with type="blob", or mode="160000" (submodule) paired
# with type="blob", is malformed/incoherent Git-object evidence and must
# never be treated as FOUND just because the mode alone is known-good.
_GIT_TREE_MODE_TO_TYPE: dict[str, str] = {
    "100644": "blob",
    "100755": "blob",
    "120000": "blob",
    "160000": "commit",
    "040000": "tree",
}


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
    """Verify the event payload's own (unnormalized) head sha is canonical.

    The raw value from ``pull_request.head.sha`` must already be a str of
    exactly 40 lowercase hex characters -- never stripped or lowercased
    before this check, so a non-canonical event sha (surrounding
    whitespace, uppercase A-F) is rejected rather than silently converted
    into an accepted canonical one.
    """
    if not isinstance(pr_head_sha, str) or not pr_head_sha:
        return FAIL, "PR head sha is missing from the event payload"
    if not _is_well_formed_git_sha(pr_head_sha):
        return (
            FAIL,
            (
                f"PR head sha {pr_head_sha!r} is not a canonical 40-character lowercase "
                "hex commit sha"
            ),
        )
    return PASS, f"PR head sha is present and well-formed ({pr_head_sha})"


def check_checked_out_matches_expected_base(
    checked_out_sha: str, expected_base_sha: str | None
) -> tuple[str, str]:
    """Verify the checked-out commit matches the event payload's raw base sha.

    ``expected_base_sha`` (``pull_request.base.sha``) is event-payload
    input and is validated in its raw, unnormalized form -- a non-canonical
    value there (whitespace, uppercase) fails closed to UNKNOWN rather than
    being normalized into a canonical value and accepted.
    ``checked_out_sha`` is trusted local ``git rev-parse HEAD`` output, not
    event-payload input, so it is still normalized for robustness.
    """
    if not isinstance(expected_base_sha, str) or not expected_base_sha:
        return UNKNOWN, "expected base sha (event payload's pull_request.base.sha) is missing"
    if not _is_well_formed_git_sha(expected_base_sha):
        return UNKNOWN, (
            f"expected base sha {expected_base_sha!r} is not a canonical 40-character "
            "lowercase hex commit sha"
        )
    checked = _normalized_sha(checked_out_sha)
    if checked and checked == expected_base_sha:
        return PASS, f"checked-out sha matches the expected base sha exactly ({checked})"
    return FAIL, (
        f"checked-out sha {checked!r} does not match expected base sha "
        f"{expected_base_sha!r}"
    )


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
    """Locate one path in one immutable commit tree, never via mutable PR APIs.

    ``ref_sha`` is event-payload input (the PR's base or head sha) and must
    already be a raw, canonical 40-character lowercase hex string -- it is
    never stripped or lowercased before this check. A non-canonical
    ``ref_sha`` is rejected as UNKNOWN before any GitHub API call is made.
    """
    owner, separator, name = str(repo or "").partition("/")
    path = str(path or "").strip("/")
    if (
        not owner
        or separator != "/"
        or not name
        or not path
        or not token
        or not isinstance(ref_sha, str)
        or not _is_well_formed_git_sha(ref_sha)
    ):
        return GitTreeEntryLookup(_LOOKUP_UNKNOWN)
    ref = ref_sha

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
    if mode not in _KNOWN_GIT_TREE_MODES:
        return GitTreeEntryLookup(_LOOKUP_UNKNOWN)
    if _GIT_TREE_MODE_TO_TYPE.get(mode) != object_type:
        return GitTreeEntryLookup(_LOOKUP_UNKNOWN)
    if not _is_well_formed_git_sha(object_sha):
        return GitTreeEntryLookup(_LOOKUP_UNKNOWN)
    return GitTreeEntryLookup(_LOOKUP_FOUND, mode, object_type, object_sha)


def check_protected_path_identity_unchanged(
    *,
    protected_path: str,
    base_sha: str | None,
    head_sha: str | None,
    base_lookup: GitTreeEntryLookup,
    head_lookup: GitTreeEntryLookup,
) -> tuple[str, str]:
    """Compare exact Git identity for one protected path; missing head covers

    delete and rename-away.

    ``base_sha``/``head_sha`` are event-payload input and are validated in
    their raw, unnormalized form -- a non-canonical value (whitespace,
    uppercase) fails closed to UNKNOWN rather than being normalized into a
    canonical value and accepted.
    """
    if (
        not isinstance(base_sha, str)
        or not _is_well_formed_git_sha(base_sha)
        or not isinstance(head_sha, str)
        or not _is_well_formed_git_sha(head_sha)
    ):
        return (
            UNKNOWN,
            "base/head sha is missing or non-canonical; protected-file identity is unverified",
        )
    base_ref, head_ref = base_sha, head_sha
    if base_lookup.state != _LOOKUP_FOUND or base_lookup.object_type != "blob":
        return UNKNOWN, (
            f"could not establish {protected_path!r} as a normal Git blob at "
            f"exact base sha {base_ref}"
        )
    if head_lookup.state == _LOOKUP_MISSING:
        return FAIL, (
            f"{protected_path!r} is missing at exact PR head sha {head_ref}; "
            "delete or rename-away is rejected"
        )
    if head_lookup.state != _LOOKUP_FOUND:
        return UNKNOWN, (
            f"could not establish {protected_path!r} identity at exact PR "
            f"head sha {head_ref}"
        )
    if head_lookup.object_type != "blob":
        return (
            FAIL,
            f"{protected_path!r} is no longer a normal Git blob at the exact PR head sha",
        )

    base_identity = (base_lookup.mode, base_lookup.object_type, base_lookup.object_sha)
    head_identity = (head_lookup.mode, head_lookup.object_type, head_lookup.object_sha)
    if base_identity != head_identity:
        return FAIL, (
            f"the PR changes {protected_path!r} between immutable base/head refs; "
            f"base_identity={base_identity!r} head_identity={head_identity!r}"
        )
    return PASS, (
        f"{protected_path!r} has identical mode/type/blob sha at exact base/head refs"
    )


def check_settings_file_unchanged_between_exact_refs(
    *,
    base_sha: str | None,
    head_sha: str | None,
    base_lookup: GitTreeEntryLookup,
    head_lookup: GitTreeEntryLookup,
) -> tuple[str, str]:
    """Compare exact Git identity for the protected settings.py path."""
    return check_protected_path_identity_unchanged(
        protected_path=_LIVE_SAFETY_SETTINGS_PATH,
        base_sha=base_sha,
        head_sha=head_sha,
        base_lookup=base_lookup,
        head_lookup=head_lookup,
    )


def check_forbidden_path_absent_at_head(
    *, forbidden_path: str, head_lookup: GitTreeEntryLookup
) -> tuple[str, str]:
    """Fail closed if a path from ``_FORBIDDEN_HEAD_ONLY_PATHS`` exists at head.

    For these paths, *absence* is the safety condition -- their mere
    presence lets a repo-controlled file intercept an import (a stdlib
    module settings.py imports, a Python startup hook, or the settings
    module's own package resolution slot) before settings.py's real
    behavior is ever reached. A GitHub API/network failure that prevents
    even confirming absence is UNKNOWN, never treated as safe.
    """
    if head_lookup.state == _LOOKUP_MISSING:
        return PASS, f"{forbidden_path!r} does not exist at the exact PR head sha"
    if head_lookup.state == _LOOKUP_FOUND:
        return FAIL, (
            f"{forbidden_path!r} exists at the exact PR head sha; a repo-controlled file "
            "at this path could intercept or replace the protected settings import"
        )
    return UNKNOWN, (
        f"could not confirm whether {forbidden_path!r} exists at the exact PR head sha"
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
    package_init_context_lookups: dict[str, tuple[GitTreeEntryLookup, GitTreeEntryLookup]],
    forbidden_path_head_lookups: dict[str, GitTreeEntryLookup],
    unresolved_review_thread_count: int | None,
    issue_255_state: str | None,
) -> GateResult:
    reasons: list[str] = []
    statuses: list[str] = []

    _unknown_lookup = GitTreeEntryLookup(_LOOKUP_UNKNOWN)
    package_init_context_checks = [
        (
            f"package-init-context-unchanged[{path}]",
            check_protected_path_identity_unchanged(
                protected_path=path,
                base_sha=expected_base_sha,
                head_sha=pr_head_sha,
                base_lookup=package_init_context_lookups.get(
                    path, (_unknown_lookup, _unknown_lookup)
                )[0],
                head_lookup=package_init_context_lookups.get(
                    path, (_unknown_lookup, _unknown_lookup)
                )[1],
            ),
        )
        for path in _PACKAGE_INIT_CONTEXT_PATHS
    ]
    forbidden_path_checks = [
        (
            f"no-forbidden-path-at-head[{path}]",
            check_forbidden_path_absent_at_head(
                forbidden_path=path,
                head_lookup=forbidden_path_head_lookups.get(path, _unknown_lookup),
            ),
        )
        for path in _FORBIDDEN_HEAD_ONLY_PATHS
    ]

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
        *package_init_context_checks,
        *forbidden_path_checks,
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
    package_init_context_lookups = {
        path: (
            fetch_git_tree_entry_at_exact_ref(
                repo=repo, path=path, ref_sha=expected_base_sha, token=token
            ),
            fetch_git_tree_entry_at_exact_ref(
                repo=repo, path=path, ref_sha=pr_head_sha, token=token
            ),
        )
        for path in _PACKAGE_INIT_CONTEXT_PATHS
    }
    forbidden_path_head_lookups = {
        path: fetch_git_tree_entry_at_exact_ref(
            repo=repo, path=path, ref_sha=pr_head_sha, token=token
        )
        for path in _FORBIDDEN_HEAD_ONLY_PATHS
    }

    result = evaluate_release_gate(
        checked_out_sha=checked_out_sha,
        pr_head_sha=pr_head_sha,
        base_ref=base_ref,
        expected_base_sha=expected_base_sha,
        get_default_settings=_load_platform_settings,
        settings_base_lookup=settings_base_lookup,
        settings_head_lookup=settings_head_lookup,
        package_init_context_lookups=package_init_context_lookups,
        forbidden_path_head_lookups=forbidden_path_head_lookups,
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
