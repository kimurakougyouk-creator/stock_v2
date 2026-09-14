from __future__ import annotations

import importlib.util
import json
import sys
import urllib.error
from pathlib import Path
from types import SimpleNamespace

import pytest

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "live_pilot_release_gate.py"
_SPEC = importlib.util.spec_from_file_location("live_pilot_release_gate", _SCRIPT_PATH)
gate = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = gate
_SPEC.loader.exec_module(gate)

BASE_SHA = "a" * 40
HEAD_SHA = "b" * 40
TREE_SHA = "c" * 40
BLOB_SHA = "d" * 40
OTHER_BLOB_SHA = "e" * 40
SETTINGS_PATH = "src/ai_asset_platform/core/settings.py"


def _default_settings():
    return SimpleNamespace(
        enable_live_trading=False,
        run_mode="DEVELOPMENT",
        live_trading_unlocked=False,
    )


def _found(*, mode="100644", object_type="blob", object_sha=BLOB_SHA):
    return gate.GitTreeEntryLookup(gate._LOOKUP_FOUND, mode, object_type, object_sha)


def _missing():
    return gate.GitTreeEntryLookup(gate._LOOKUP_MISSING)


def _unknown():
    return gate.GitTreeEntryLookup(gate._LOOKUP_UNKNOWN)


def _clean_package_init_context_lookups():
    return {path: (_found(), _found()) for path in gate._PACKAGE_INIT_CONTEXT_PATHS}


def _clean_forbidden_path_head_lookups():
    return {path: _missing() for path in gate._FORBIDDEN_HEAD_ONLY_PATHS}


def _evaluate(**overrides):
    params = {
        "checked_out_sha": BASE_SHA,
        "pr_head_sha": HEAD_SHA,
        "base_ref": "main",
        "expected_base_sha": BASE_SHA,
        "get_default_settings": _default_settings,
        "settings_base_lookup": _found(),
        "settings_head_lookup": _found(),
        "package_init_context_lookups": _clean_package_init_context_lookups(),
        "forbidden_path_head_lookups": _clean_forbidden_path_head_lookups(),
        "unresolved_review_thread_count": 0,
        "issue_255_state": "open",
    }
    params.update(overrides)
    return gate.evaluate_release_gate(**params)


def test_clean_evidence_passes():
    assert _evaluate().status == gate.PASS


@pytest.mark.parametrize("value", [None, "a" * 39, "g" * 40])
def test_missing_or_malformed_pr_head_sha_fails(value):
    assert _evaluate(pr_head_sha=value).status == gate.FAIL


def test_canonical_lowercase_pr_head_sha_passes():
    assert _evaluate(pr_head_sha=HEAD_SHA).status == gate.PASS


def test_uppercase_pr_head_sha_now_fails_closed():
    """Codex P2 regression: event-payload SHAs are validated in their raw

    form. An uppercase head sha must FAIL, never be normalized into a
    canonical value and accepted (this replaces the prior "uppercase is
    accepted" behavior).
    """
    assert _evaluate(pr_head_sha=HEAD_SHA.upper()).status == gate.FAIL


@pytest.mark.parametrize(
    "value", [f" {HEAD_SHA}", f"{HEAD_SHA} ", f"{HEAD_SHA}\n", f"\t{HEAD_SHA}"]
)
def test_whitespace_padded_pr_head_sha_fails(value):
    """Codex P2 regression: leading/trailing whitespace on the event

    payload's head sha must FAIL, never be stripped and accepted.
    """
    assert _evaluate(pr_head_sha=value).status == gate.FAIL


def test_checked_out_sha_mismatch_fails():
    assert _evaluate(checked_out_sha="f" * 40).status == gate.FAIL


@pytest.mark.parametrize("value", [None, "a" * 39, "g" * 40])
def test_missing_or_malformed_expected_base_sha_is_unknown(value):
    assert _evaluate(expected_base_sha=value).status == gate.UNKNOWN


def test_canonical_lowercase_expected_base_sha_passes():
    assert _evaluate(expected_base_sha=BASE_SHA).status == gate.PASS


def test_uppercase_expected_base_sha_is_unknown():
    """Codex P2 regression: an uppercase event-payload base sha must be

    UNKNOWN, never normalized into a canonical value and accepted.
    """
    assert _evaluate(expected_base_sha=BASE_SHA.upper()).status == gate.UNKNOWN


@pytest.mark.parametrize(
    "value", [f" {BASE_SHA}", f"{BASE_SHA} ", f"{BASE_SHA}\n", f"\t{BASE_SHA}"]
)
def test_whitespace_padded_expected_base_sha_is_unknown(value):
    """Codex P2 regression: leading/trailing whitespace on the event

    payload's base sha must be UNKNOWN, never stripped and accepted.
    """
    assert _evaluate(expected_base_sha=value).status == gate.UNKNOWN


def test_wrong_base_branch_fails():
    assert _evaluate(base_ref="develop").status == gate.FAIL


@pytest.mark.parametrize(
    "settings",
    [
        SimpleNamespace(
            enable_live_trading=True,
            run_mode="DEVELOPMENT",
            live_trading_unlocked=False,
        ),
        SimpleNamespace(
            enable_live_trading=False,
            run_mode="LIVE",
            live_trading_unlocked=False,
        ),
    ],
)
def test_unsafe_default_settings_fail(settings):
    assert _evaluate(get_default_settings=lambda: settings).status == gate.FAIL


def test_settings_import_failure_is_unknown():
    def _raise():
        raise ImportError("settings unavailable")

    assert _evaluate(get_default_settings=_raise).status == gate.UNKNOWN


def test_settings_unexpected_shape_is_unknown():
    malformed = SimpleNamespace(
        enable_live_trading="false",
        run_mode="DEVELOPMENT",
        live_trading_unlocked=False,
    )
    assert _evaluate(get_default_settings=lambda: malformed).status == gate.UNKNOWN


def _identity_check(base_lookup, head_lookup, *, base_sha=BASE_SHA, head_sha=HEAD_SHA):
    return gate.check_settings_file_unchanged_between_exact_refs(
        base_sha=base_sha,
        head_sha=head_sha,
        base_lookup=base_lookup,
        head_lookup=head_lookup,
    )


def test_exact_ref_same_identity_passes():
    assert _identity_check(_found(), _found())[0] == gate.PASS


@pytest.mark.parametrize(
    "head_lookup",
    [
        _found(object_sha=OTHER_BLOB_SHA),
        _found(mode="100755"),
        _found(object_type="tree"),
    ],
)
def test_head_identity_change_fails(head_lookup):
    assert _identity_check(_found(), head_lookup)[0] == gate.FAIL


def test_head_missing_fails_for_delete_or_rename_away():
    status, reason = _identity_check(_found(), _missing())
    assert status == gate.FAIL
    assert "delete or rename-away" in reason


@pytest.mark.parametrize("base_lookup", [_missing(), _unknown(), _found(object_type="tree")])
def test_unverifiable_base_identity_is_unknown(base_lookup):
    assert _identity_check(base_lookup, _found())[0] == gate.UNKNOWN


def test_unverifiable_head_identity_is_unknown():
    assert _identity_check(_found(), _unknown())[0] == gate.UNKNOWN


@pytest.mark.parametrize(
    ("base_sha", "head_sha"),
    [
        ("a" * 39, HEAD_SHA),
        (BASE_SHA, "g" * 40),
        (None, HEAD_SHA),
        (BASE_SHA.upper(), HEAD_SHA),
        (BASE_SHA, HEAD_SHA.upper()),
        (f" {BASE_SHA}", HEAD_SHA),
        (BASE_SHA, f"{HEAD_SHA} "),
    ],
)
def test_identity_check_malformed_ref_is_unknown(base_sha, head_sha):
    """Codex P2 regression: base/head sha here is event-payload input and

    must already be raw canonical; whitespace or uppercase must be UNKNOWN,
    never normalized and accepted.
    """
    result = _identity_check(_found(), _found(), base_sha=base_sha, head_sha=head_sha)
    assert result[0] == gate.UNKNOWN


# ---------------------------------------------------------------------------
# Codex P2: "Protect the head package initialization context" -- an
# unchanged settings.py blob alone does not prove head's runtime behavior
# is unchanged, since importing it first runs ai_asset_platform's and
# ai_asset_platform.core's own __init__.py, which could import settings.py
# and then replace its class/singleton (or plant a fake module in
# sys.modules) without touching settings.py's own bytes. It also covers
# repo-controlled files that would shadow a stdlib module (`dataclasses`)
# that settings.py imports, on this project's actual sys.path.
# ---------------------------------------------------------------------------


def test_check_protected_path_identity_unchanged_is_generic_over_path():
    """The generalized identity-check function works for any protected

    path, not just settings.py -- used for both __init__.py files below.
    """
    status, reason = gate.check_protected_path_identity_unchanged(
        protected_path="src/ai_asset_platform/core/__init__.py",
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        base_lookup=_found(),
        head_lookup=_found(object_sha=OTHER_BLOB_SHA),
    )
    assert status == gate.FAIL
    assert "src/ai_asset_platform/core/__init__.py" in reason


@pytest.mark.parametrize("forbidden_path", sorted(gate._FORBIDDEN_HEAD_ONLY_PATHS))
def test_check_forbidden_path_absent_at_head_directly(forbidden_path):
    assert (
        gate.check_forbidden_path_absent_at_head(
            forbidden_path=forbidden_path, head_lookup=_missing()
        )[0]
        == gate.PASS
    )
    assert (
        gate.check_forbidden_path_absent_at_head(
            forbidden_path=forbidden_path, head_lookup=_found()
        )[0]
        == gate.FAIL
    )
    assert (
        gate.check_forbidden_path_absent_at_head(
            forbidden_path=forbidden_path, head_lookup=_unknown()
        )[0]
        == gate.UNKNOWN
    )


# A: settings.py unchanged, but src/ai_asset_platform/core/__init__.py
# changed at head -- must not PASS.
def test_core_init_changed_blocks_pass_even_with_settings_unchanged():
    lookups = _clean_package_init_context_lookups()
    core_init_path = "src/ai_asset_platform/core/__init__.py"
    lookups[core_init_path] = (_found(), _found(object_sha=OTHER_BLOB_SHA))
    result = _evaluate(package_init_context_lookups=lookups)
    assert result.status == gate.FAIL
    assert any(f"package-init-context-unchanged[{core_init_path}]" in r for r in result.reasons)


# B: settings.py unchanged, but src/ai_asset_platform/__init__.py changed
# at head -- must not PASS. Confirmed reachable: importing
# ai_asset_platform.core.settings always runs ai_asset_platform/__init__.py
# first (Python always executes a package's own __init__.py before any of
# its submodules), so it is genuinely part of the import context.
def test_root_init_changed_blocks_pass_even_with_settings_unchanged():
    lookups = _clean_package_init_context_lookups()
    root_init_path = "src/ai_asset_platform/__init__.py"
    lookups[root_init_path] = (_found(), _found(object_sha=OTHER_BLOB_SHA))
    result = _evaluate(package_init_context_lookups=lookups)
    assert result.status == gate.FAIL
    assert any(f"package-init-context-unchanged[{root_init_path}]" in r for r in result.reasons)


def test_core_init_delete_or_rename_away_fails():
    lookups = _clean_package_init_context_lookups()
    core_init_path = "src/ai_asset_platform/core/__init__.py"
    lookups[core_init_path] = (_found(), _missing())
    result = _evaluate(package_init_context_lookups=lookups)
    assert result.status == gate.FAIL


# C: a repo-local dataclasses shadow module/package, confirmed reachable on
# this project's actual import path (PYTHONPATH=src places src/ ahead of
# the stdlib default paths, and `dataclasses` is not pre-loaded into
# sys.modules before user code runs -- see the module docstring), must not
# PASS if newly present at head.
@pytest.mark.parametrize("shadow_path", sorted(gate._FORBIDDEN_STDLIB_SHADOW_PATHS))
def test_new_dataclasses_shadow_at_head_blocks_pass(shadow_path):
    lookups = _clean_forbidden_path_head_lookups()
    lookups[shadow_path] = _found()
    result = _evaluate(forbidden_path_head_lookups=lookups)
    assert result.status == gate.FAIL
    assert any(f"no-forbidden-path-at-head[{shadow_path}]" in r for r in result.reasons)


def test_os_shadow_paths_are_deliberately_not_protected():
    """`os` is unconditionally imported into sys.modules during CPython's

    own interpreter bootstrap before any user script or test runs in this
    project (confirmed empirically), so no repo-local os.py/os/__init__.py
    anywhere on sys.path can ever shadow it here -- this is a deliberate
    scope decision, not an oversight, and is documented on
    ``_FORBIDDEN_STDLIB_SHADOW_PATHS`` / ``_FORBIDDEN_HEAD_ONLY_PATHS``.
    """
    assert "src/os.py" not in gate._FORBIDDEN_HEAD_ONLY_PATHS
    assert "src/os/__init__.py" not in gate._FORBIDDEN_HEAD_ONLY_PATHS


# Codex P2-1 "Reject repo-local Python startup hooks": sitecustomize/
# usercustomize (module or package form) are imported automatically by
# CPython's own site initialization before this project's own code runs,
# and with PYTHONPATH=src, src/ is on sys.path at that point -- confirmed
# reachable the same way as the stdlib-shadow paths. Must not PASS if
# newly present at head.
@pytest.mark.parametrize("hook_path", sorted(gate._FORBIDDEN_STARTUP_HOOK_PATHS))
def test_new_startup_hook_at_head_blocks_pass(hook_path):
    lookups = _clean_forbidden_path_head_lookups()
    lookups[hook_path] = _found()
    result = _evaluate(forbidden_path_head_lookups=lookups)
    assert result.status == gate.FAIL
    assert any(f"no-forbidden-path-at-head[{hook_path}]" in r for r in result.reasons)


# Codex P2-2 "Reject a package that shadows the settings module": Python
# resolves a package ahead of a sibling module of the same name, so
# src/ai_asset_platform/core/settings/__init__.py would be imported instead
# of the sibling settings.py for `ai_asset_platform.core.settings`,
# regardless of whether settings.py itself is unchanged. Must not PASS if
# newly present at head.
@pytest.mark.parametrize(
    "shadow_package_path", sorted(gate._FORBIDDEN_SETTINGS_PACKAGE_SHADOW_PATHS)
)
def test_new_settings_package_shadow_at_head_blocks_pass(shadow_package_path):
    lookups = _clean_forbidden_path_head_lookups()
    lookups[shadow_package_path] = _found()
    result = _evaluate(forbidden_path_head_lookups=lookups)
    assert result.status == gate.FAIL
    assert any(
        f"no-forbidden-path-at-head[{shadow_package_path}]" in r for r in result.reasons
    )


def test_settings_package_shadow_path_is_the_expected_sibling_of_settings_py():
    assert gate._FORBIDDEN_SETTINGS_PACKAGE_SHADOW_PATHS == (
        "src/ai_asset_platform/core/settings/__init__.py",
    )


# D: malformed/incomplete Git evidence for the new checks must fail closed
# to UNKNOWN, never be silently treated as a "PASS because it matches" --
# including a base/head pair that happens to carry identical malformed
# evidence.
def test_package_init_context_unknown_lookup_is_unknown_not_pass():
    lookups = _clean_package_init_context_lookups()
    core_init_path = "src/ai_asset_platform/core/__init__.py"
    lookups[core_init_path] = (_unknown(), _unknown())
    result = _evaluate(package_init_context_lookups=lookups)
    assert result.status == gate.UNKNOWN


def test_package_init_context_incoherent_type_on_both_sides_is_unknown_not_pass():
    """Both base and head report the same non-blob type for a protected

    __init__.py path -- must never be treated as a legitimate match just
    because the two sides agree.
    """
    lookups = _clean_package_init_context_lookups()
    core_init_path = "src/ai_asset_platform/core/__init__.py"
    weird_lookup = gate.GitTreeEntryLookup(gate._LOOKUP_FOUND, "040000", "tree", TREE_SHA)
    lookups[core_init_path] = (weird_lookup, weird_lookup)
    result = _evaluate(package_init_context_lookups=lookups)
    assert result.status != gate.PASS
    assert result.status == gate.UNKNOWN


@pytest.mark.parametrize("forbidden_path", sorted(gate._FORBIDDEN_HEAD_ONLY_PATHS))
def test_forbidden_path_unknown_lookup_is_unknown_not_pass(forbidden_path):
    lookups = _clean_forbidden_path_head_lookups()
    lookups[forbidden_path] = _unknown()
    result = _evaluate(forbidden_path_head_lookups=lookups)
    assert result.status == gate.UNKNOWN


def test_missing_package_init_context_entry_defaults_to_unknown():
    """If a protected path's lookup is absent from the dict passed to

    evaluate_release_gate entirely, the check must default to UNKNOWN,
    never silently PASS.
    """
    result = _evaluate(package_init_context_lookups={})
    assert result.status == gate.UNKNOWN


def test_missing_forbidden_path_entry_defaults_to_unknown():
    result = _evaluate(forbidden_path_head_lookups={})
    assert result.status == gate.UNKNOWN


# E: normal, current base/head evidence must not be blocked by the new
# checks -- covered by test_clean_evidence_passes (its default fixtures
# now include clean package-init-context and forbidden-path evidence too).
def test_clean_package_init_context_and_forbidden_path_evidence_still_passes():
    result = _evaluate(
        package_init_context_lookups=_clean_package_init_context_lookups(),
        forbidden_path_head_lookups=_clean_forbidden_path_head_lookups(),
    )
    assert result.status == gate.PASS


def test_review_count_and_issue_state_values_are_display_only():
    for count in (0, 1, 500):
        assert _evaluate(unresolved_review_thread_count=count).status == gate.PASS
    for state in ("open", "closed", "unexpected"):
        assert _evaluate(issue_255_state=state).status == gate.PASS


def test_display_only_fetch_failures_make_gate_unknown():
    assert _evaluate(unresolved_review_thread_count=None).status == gate.UNKNOWN
    assert _evaluate(issue_255_state=None).status == gate.UNKNOWN


def test_fail_takes_precedence_over_unknown():
    result = _evaluate(pr_head_sha=None, unresolved_review_thread_count=None)
    assert result.status == gate.FAIL


def test_live_execution_constant_is_no_go():
    assert gate.LIVE_EXECUTION_VALUE == "NO-GO"


class _FakeResponse:
    def __init__(self, body):
        self._body = json.dumps(body).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _commit_body(tree_sha=TREE_SHA, *, commit_sha=HEAD_SHA):
    return {"sha": commit_sha, "tree": {"sha": tree_sha}}


def _tree_body(entries, *, truncated=False):
    return {"sha": TREE_SHA, "truncated": truncated, "tree": entries}


def _settings_entry(*, path=SETTINGS_PATH, mode="100644", object_type="blob", sha=BLOB_SHA):
    return {"path": path, "mode": mode, "type": object_type, "sha": sha}


def _lookup(monkeypatch, responses):
    responses = iter(responses)
    seen = []

    def _fake_urlopen(request, timeout=None):
        seen.append(request.full_url)
        response = next(responses)
        if isinstance(response, Exception):
            raise response
        return response

    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen)
    result = gate.fetch_git_tree_entry_at_exact_ref(
        repo="owner/repo", path=SETTINGS_PATH, ref_sha=HEAD_SHA, token="tok"
    )
    return result, seen


def test_tree_lookup_uses_exact_immutable_commit_and_tree_refs(monkeypatch):
    result, seen = _lookup(
        monkeypatch,
        [_FakeResponse(_commit_body()), _FakeResponse(_tree_body([_settings_entry()]))],
    )
    assert result == _found()
    assert f"/git/commits/{HEAD_SHA}" in seen[0]
    assert f"/git/trees/{TREE_SHA}?recursive=1" in seen[1]
    assert not any("/pulls/" in url for url in seen)


def test_tree_lookup_missing_path_is_missing(monkeypatch):
    result, _ = _lookup(
        monkeypatch,
        [_FakeResponse(_commit_body()), _FakeResponse(_tree_body([]))],
    )
    assert result.state == gate._LOOKUP_MISSING


@pytest.mark.parametrize(
    "responses",
    [
        [OSError("network")],
        [urllib.error.HTTPError("https://api.github.com", 404, "missing", {}, None)],
        [_FakeResponse({"tree": {"sha": TREE_SHA}})],
        [_FakeResponse(_commit_body(commit_sha=BASE_SHA))],
        [_FakeResponse(_commit_body(tree_sha="short"))],
        [_FakeResponse(_commit_body()), _FakeResponse({"truncated": False, "tree": []})],
        [_FakeResponse(_commit_body()), _FakeResponse(_tree_body([], truncated=True))],
        [_FakeResponse(_commit_body()), _FakeResponse({"sha": TREE_SHA, "tree": []})],
        [_FakeResponse(_commit_body()), _FakeResponse({"sha": TREE_SHA, "truncated": "false", "tree": []})],
        [_FakeResponse(_commit_body()), _FakeResponse({"sha": HEAD_SHA, "truncated": False, "tree": []})],
        [_FakeResponse(_commit_body()), _FakeResponse(_tree_body(None))],
        [_FakeResponse(_commit_body()), _FakeResponse(_tree_body(["bad"]))],
        [_FakeResponse(_commit_body()), _FakeResponse(_tree_body([{"path": 123}]))],
        [_FakeResponse(_commit_body()), _FakeResponse(_tree_body([_settings_entry(sha="short")]))],
        [
            _FakeResponse(_commit_body()),
            _FakeResponse(_tree_body([_settings_entry(), _settings_entry()])),
        ],
        [
            _FakeResponse(_commit_body()),
            _FakeResponse(_tree_body([_settings_entry(mode="not-a-git-mode")])),
        ],
    ],
)
def test_tree_lookup_uncertain_or_malformed_evidence_is_unknown(monkeypatch, responses):
    result, _ = _lookup(monkeypatch, responses)
    assert result.state == gate._LOOKUP_UNKNOWN


@pytest.mark.parametrize("mode", sorted(gate._KNOWN_GIT_TREE_MODES))
def test_tree_lookup_accepts_every_known_git_mode_with_its_coherent_type(monkeypatch, mode):
    """Codex P2 regression: each mode in the allowlist (normal file,

    executable, symlink, submodule, subtree), paired with the one Git
    object type it is actually defined to point at, is accepted.
    """
    coherent_type = gate._GIT_TREE_MODE_TO_TYPE[mode]
    result, _ = _lookup(
        monkeypatch,
        [
            _FakeResponse(_commit_body()),
            _FakeResponse(
                _tree_body([_settings_entry(mode=mode, object_type=coherent_type)])
            ),
        ],
    )
    assert result.state == gate._LOOKUP_FOUND
    assert result.mode == mode
    assert result.object_type == coherent_type


@pytest.mark.parametrize(
    ("mode", "object_type"),
    [
        ("040000", "blob"),
        ("160000", "blob"),
        ("100644", "tree"),
        ("100755", "commit"),
        ("120000", "tree"),
    ],
)
def test_tree_lookup_rejects_incompatible_mode_type_pairs(monkeypatch, mode, object_type):
    """Codex P2 regression: an individually allowlisted mode paired with an

    incoherent Git object type (e.g. mode="040000" subtree with
    type="blob", or mode="160000" submodule with type="blob") must resolve
    to UNKNOWN, never FOUND -- the mode/type combination is validated as a
    pair, not mode and type independently.
    """
    result, _ = _lookup(
        monkeypatch,
        [
            _FakeResponse(_commit_body()),
            _FakeResponse(
                _tree_body([_settings_entry(mode=mode, object_type=object_type)])
            ),
        ],
    )
    assert result.state == gate._LOOKUP_UNKNOWN


def test_matching_incompatible_mode_type_pair_never_passes_identity_check(monkeypatch):
    """Codex P2 regression: base and head both reporting the *same*

    individually-allowlisted-but-incoherent mode/type pair (e.g.
    mode="040000" with type="blob" on both sides) must never be treated as
    a legitimate match. The fetch layer rejects the incoherent pair
    outright (UNKNOWN, not FOUND) on both sides, so the identity
    comparison can never see it as "PASS because base == head".
    """
    bad_pair_entry = _settings_entry(mode="040000", object_type="blob")

    base_result, _ = _lookup(
        monkeypatch,
        [_FakeResponse(_commit_body()), _FakeResponse(_tree_body([bad_pair_entry]))],
    )
    assert base_result.state == gate._LOOKUP_UNKNOWN

    head_result, _ = _lookup(
        monkeypatch,
        [_FakeResponse(_commit_body()), _FakeResponse(_tree_body([bad_pair_entry]))],
    )
    assert head_result.state == gate._LOOKUP_UNKNOWN

    status, _ = gate.check_settings_file_unchanged_between_exact_refs(
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        base_lookup=base_result,
        head_lookup=head_result,
    )
    assert status != gate.PASS
    assert status == gate.UNKNOWN


@pytest.mark.parametrize(
    "mode", ["not-a-git-mode", "", "100644 ", " 100644", "100644\n", "0100644", "644"]
)
def test_tree_lookup_rejects_non_allowlisted_mode_strings(monkeypatch, mode):
    """Codex P2 regression: a mode string that is not one of the known,

    meaningful Git tree modes must resolve to UNKNOWN -- never FOUND, no
    matter how plausible it looks.
    """
    result, _ = _lookup(
        monkeypatch,
        [_FakeResponse(_commit_body()), _FakeResponse(_tree_body([_settings_entry(mode=mode)]))],
    )
    assert result.state == gate._LOOKUP_UNKNOWN


def test_matching_but_non_allowlisted_mode_never_passes_identity_check(monkeypatch):
    """Codex P2 regression: base and head reporting the *same* non-allowlisted

    mode string must never be treated as a legitimate match. The fetch layer
    rejects the bad mode outright (UNKNOWN, not FOUND) on both sides, so the
    identity comparison can never see it as "PASS because base == head".
    """
    bad_mode_entry = _settings_entry(mode="not-a-git-mode")

    base_result, _ = _lookup(
        monkeypatch,
        [_FakeResponse(_commit_body()), _FakeResponse(_tree_body([bad_mode_entry]))],
    )
    assert base_result.state == gate._LOOKUP_UNKNOWN

    head_result, _ = _lookup(
        monkeypatch,
        [_FakeResponse(_commit_body()), _FakeResponse(_tree_body([bad_mode_entry]))],
    )
    assert head_result.state == gate._LOOKUP_UNKNOWN

    status, _ = gate.check_settings_file_unchanged_between_exact_refs(
        base_sha=BASE_SHA,
        head_sha=HEAD_SHA,
        base_lookup=base_result,
        head_lookup=head_result,
    )
    assert status != gate.PASS
    assert status == gate.UNKNOWN


@pytest.mark.parametrize(
    "responses",
    [
        # Git commit API's own "sha" field: well-formed 40-hex only after
        # stripping whitespace / lowercasing -- must be rejected outright,
        # never normalized then accepted.
        [_FakeResponse(_commit_body(commit_sha=f" {HEAD_SHA}"))],
        [_FakeResponse(_commit_body(commit_sha=f"{HEAD_SHA} "))],
        [_FakeResponse(_commit_body(commit_sha=HEAD_SHA.upper()))],
        # Commit body's own "tree.sha" field, same non-canonical variants.
        [_FakeResponse(_commit_body(tree_sha=f" {TREE_SHA}"))],
        [_FakeResponse(_commit_body(tree_sha=TREE_SHA.upper()))],
        # Git tree API's own "sha" field, same non-canonical variants.
        [
            _FakeResponse(_commit_body()),
            _FakeResponse({"sha": f"{TREE_SHA} ", "truncated": False, "tree": []}),
        ],
        [
            _FakeResponse(_commit_body()),
            _FakeResponse({"sha": TREE_SHA.upper(), "truncated": False, "tree": []}),
        ],
        # Matched tree entry's blob "sha" field, same non-canonical variants.
        [
            _FakeResponse(_commit_body()),
            _FakeResponse(_tree_body([_settings_entry(sha=f"{BLOB_SHA} ")])),
        ],
        [
            _FakeResponse(_commit_body()),
            _FakeResponse(_tree_body([_settings_entry(sha=BLOB_SHA.upper())])),
        ],
    ],
)
def test_tree_lookup_rejects_non_canonical_returned_shas(monkeypatch, responses):
    """Codex P2 regression: a SHA returned by the Git commit/tree API must

    already be canonical (lowercase, no surrounding whitespace) 40-hex.
    Before this fix, such returned values were ``.strip().lower()``'d
    before being validated/compared, so a non-canonical value from the API
    would be silently normalized and accepted instead of failing closed.
    """
    result, _ = _lookup(monkeypatch, responses)
    assert result.state == gate._LOOKUP_UNKNOWN


@pytest.mark.parametrize(
    ("repo", "path", "ref_sha", "token"),
    [
        ("", SETTINGS_PATH, HEAD_SHA, "tok"),
        ("owner/repo", "", HEAD_SHA, "tok"),
        ("owner/repo", SETTINGS_PATH, HEAD_SHA, None),
        ("owner/repo", SETTINGS_PATH, "a" * 39, "tok"),
        ("owner/repo", SETTINGS_PATH, "g" * 40, "tok"),
        ("owner/repo", SETTINGS_PATH, HEAD_SHA.upper(), "tok"),
        ("owner/repo", SETTINGS_PATH, f" {HEAD_SHA}", "tok"),
        ("owner/repo", SETTINGS_PATH, f"{HEAD_SHA} ", "tok"),
        ("owner/repo", SETTINGS_PATH, None, "tok"),
    ],
)
def test_tree_lookup_requires_complete_valid_inputs(repo, path, ref_sha, token):
    result = gate.fetch_git_tree_entry_at_exact_ref(
        repo=repo, path=path, ref_sha=ref_sha, token=token
    )
    assert result.state == gate._LOOKUP_UNKNOWN


@pytest.mark.parametrize(
    "ref_sha", [HEAD_SHA.upper(), f" {HEAD_SHA}", f"{HEAD_SHA} ", f"{HEAD_SHA}\n"]
)
def test_tree_lookup_rejects_non_canonical_event_ref_sha_without_any_api_call(
    monkeypatch, ref_sha
):
    """Codex P2 regression: ``ref_sha`` is event-payload input (the PR's

    base or head sha) and must already be raw canonical. A non-canonical
    ``ref_sha`` must resolve to UNKNOWN without ever calling the GitHub
    API -- never normalized and then used to make a request.
    """

    def _fail_if_called(*args, **kwargs):
        raise AssertionError("must not call the GitHub API for a non-canonical ref_sha")

    monkeypatch.setattr(gate.urllib.request, "urlopen", _fail_if_called)
    result = gate.fetch_git_tree_entry_at_exact_ref(
        repo="owner/repo", path=SETTINGS_PATH, ref_sha=ref_sha, token="tok"
    )
    assert result.state == gate._LOOKUP_UNKNOWN


def test_tree_lookup_accepts_canonical_lowercase_ref_sha(monkeypatch):
    """A raw, already-canonical lowercase ref_sha still works as before."""
    result, seen = _lookup(
        monkeypatch,
        [_FakeResponse(_commit_body()), _FakeResponse(_tree_body([_settings_entry()]))],
    )
    assert result == _found()
    assert f"/git/commits/{HEAD_SHA}" in seen[0]


def test_fetch_helpers_return_none_on_network_failure(monkeypatch):
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        lambda *a, **k: (_ for _ in ()).throw(OSError("network")),
    )
    assert (
        gate.fetch_unresolved_review_thread_count(
            repo="owner/repo", pr_number=283, token="tok"
        )
        is None
    )
    assert gate.fetch_issue_state(repo="owner/repo", issue_number=255, token="tok") is None


def _configure_main(
    monkeypatch,
    *,
    settings_head_lookup=None,
    package_init_head_lookup=None,
    forbidden_path_head_lookup=None,
    settings_loader=_default_settings,
):
    """Route the mocked ``fetch_git_tree_entry_at_exact_ref`` by ``path`` and

    ``ref_sha`` (base vs. head), since ``main()`` now makes several distinct
    lookups (settings.py, two package __init__.py paths, and every path in
    ``_FORBIDDEN_HEAD_ONLY_PATHS``) instead of just two. Base-side lookups
    for real (non-forbidden) paths default to a clean ``_found()``;
    head-side lookups default to a clean ``_found()`` for
    settings.py/__init__.py paths and a clean ``_missing()`` (absent, safe)
    for every forbidden path, unless overridden.
    """
    monkeypatch.setattr(
        gate,
        "_load_event_payload",
        lambda: {
            "pull_request": {
                "number": 283,
                "head": {"sha": HEAD_SHA},
                "base": {"ref": "main", "sha": BASE_SHA},
            }
        },
    )
    monkeypatch.setattr(gate, "_git_head_sha", lambda: BASE_SHA)
    monkeypatch.setattr(gate, "fetch_unresolved_review_thread_count", lambda **kwargs: 0)
    monkeypatch.setattr(gate, "fetch_issue_state", lambda **kwargs: "open")

    def _tree_lookup(*, repo, path, ref_sha, token):
        if path in gate._FORBIDDEN_HEAD_ONLY_PATHS:
            return (
                forbidden_path_head_lookup
                if forbidden_path_head_lookup is not None
                else _missing()
            )
        if ref_sha == BASE_SHA:
            return _found()
        if path == gate._LIVE_SAFETY_SETTINGS_PATH:
            return settings_head_lookup if settings_head_lookup is not None else _found()
        return package_init_head_lookup if package_init_head_lookup is not None else _found()

    monkeypatch.setattr(gate, "fetch_git_tree_entry_at_exact_ref", _tree_lookup)
    monkeypatch.setattr(gate, "_load_platform_settings", settings_loader)
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")


def test_main_clean_path_prints_pass_and_fixed_no_go(monkeypatch, capsys):
    _configure_main(monkeypatch)
    assert gate.main() == 0
    output = capsys.readouterr().out
    assert "RELEASE_INTEGRITY_GATE=PASS" in output
    assert "LIVE_EXECUTION=NO-GO" in output


def test_main_rename_away_prints_fail_and_fixed_no_go(monkeypatch, capsys):
    _configure_main(monkeypatch, settings_head_lookup=_missing())
    assert gate.main() != 0
    output = capsys.readouterr().out
    assert "RELEASE_INTEGRITY_GATE=FAIL" in output
    assert "delete or rename-away" in output
    assert "LIVE_EXECUTION=NO-GO" in output


def test_main_settings_import_failure_is_unknown_not_crash(monkeypatch, capsys):
    def _raise():
        raise ModuleNotFoundError("ai_asset_platform")

    _configure_main(monkeypatch, settings_loader=_raise)
    assert gate.main() != 0
    output = capsys.readouterr().out
    assert "RELEASE_INTEGRITY_GATE=UNKNOWN" in output
    assert "LIVE_EXECUTION=NO-GO" in output


def test_main_core_init_change_prints_fail_and_fixed_no_go(monkeypatch, capsys):
    """Codex P2 (package init context) regression, exercised through main():

    settings.py is unchanged, but ``ai_asset_platform/core/__init__.py`` (or
    the top-level ``ai_asset_platform/__init__.py``) changed at head -- the
    package initialization/import context that runs before settings.py's
    own module body -- so the gate must not PASS.
    """
    _configure_main(monkeypatch, package_init_head_lookup=_found(object_sha=OTHER_BLOB_SHA))
    assert gate.main() != 0
    output = capsys.readouterr().out
    assert "RELEASE_INTEGRITY_GATE=FAIL" in output
    assert "package-init-context-unchanged" in output
    assert "LIVE_EXECUTION=NO-GO" in output


def test_main_new_dataclasses_shadow_at_head_prints_fail_and_fixed_no_go(monkeypatch, capsys):
    """Codex P2 (stdlib shadow) regression, exercised through main(): a new

    repo-controlled ``src/dataclasses.py``/``src/dataclasses/__init__.py``
    appearing at head -- reachable on this project's actual sys.path ahead
    of the real stdlib module -- must not PASS.
    """
    _configure_main(monkeypatch, forbidden_path_head_lookup=_found())
    assert gate.main() != 0
    output = capsys.readouterr().out
    assert "RELEASE_INTEGRITY_GATE=FAIL" in output
    assert "no-forbidden-path-at-head" in output
    assert "LIVE_EXECUTION=NO-GO" in output


def test_main_new_startup_hook_at_head_prints_fail_and_fixed_no_go(monkeypatch, capsys):
    """Codex P2-1 regression, exercised through main(): a new repo-controlled

    ``src/sitecustomize.py``/``src/usercustomize.py`` (or package form)
    appearing at head -- imported automatically by CPython's own site
    initialization before this project's own code runs -- must not PASS.
    """
    _configure_main(monkeypatch, forbidden_path_head_lookup=_found())
    assert gate.main() != 0
    output = capsys.readouterr().out
    assert "RELEASE_INTEGRITY_GATE=FAIL" in output
    assert any(
        f"no-forbidden-path-at-head[{path}]" in output
        for path in gate._FORBIDDEN_STARTUP_HOOK_PATHS
    )
    assert "LIVE_EXECUTION=NO-GO" in output


def test_main_new_settings_package_shadow_at_head_prints_fail_and_fixed_no_go(
    monkeypatch, capsys
):
    """Codex P2-2 regression, exercised through main(): a new repo-controlled

    ``src/ai_asset_platform/core/settings/__init__.py`` appearing at head --
    Python resolves this package ahead of the sibling settings.py module --
    must not PASS, even though settings.py itself is unchanged.
    """
    _configure_main(monkeypatch, forbidden_path_head_lookup=_found())
    assert gate.main() != 0
    output = capsys.readouterr().out
    assert "RELEASE_INTEGRITY_GATE=FAIL" in output
    assert (
        "no-forbidden-path-at-head[src/ai_asset_platform/core/settings/__init__.py]" in output
    )
    assert "LIVE_EXECUTION=NO-GO" in output
