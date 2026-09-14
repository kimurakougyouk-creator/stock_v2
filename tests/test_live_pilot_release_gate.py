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


def _evaluate(**overrides):
    params = {
        "checked_out_sha": BASE_SHA,
        "pr_head_sha": HEAD_SHA,
        "base_ref": "main",
        "expected_base_sha": BASE_SHA,
        "get_default_settings": _default_settings,
        "settings_base_lookup": _found(),
        "settings_head_lookup": _found(),
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


def test_uppercase_pr_head_sha_is_accepted():
    assert _evaluate(pr_head_sha=HEAD_SHA.upper()).status == gate.PASS


def test_checked_out_sha_mismatch_fails():
    assert _evaluate(checked_out_sha="f" * 40).status == gate.FAIL


@pytest.mark.parametrize("value", [None, "a" * 39, "g" * 40])
def test_missing_or_malformed_expected_base_sha_is_unknown(value):
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
    [("a" * 39, HEAD_SHA), (BASE_SHA, "g" * 40), (None, HEAD_SHA)],
)
def test_identity_check_malformed_ref_is_unknown(base_sha, head_sha):
    result = _identity_check(_found(), _found(), base_sha=base_sha, head_sha=head_sha)
    assert result[0] == gate.UNKNOWN


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
    ],
)
def test_tree_lookup_uncertain_or_malformed_evidence_is_unknown(monkeypatch, responses):
    result, _ = _lookup(monkeypatch, responses)
    assert result.state == gate._LOOKUP_UNKNOWN


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
    ],
)
def test_tree_lookup_requires_complete_valid_inputs(repo, path, ref_sha, token):
    result = gate.fetch_git_tree_entry_at_exact_ref(
        repo=repo, path=path, ref_sha=ref_sha, token=token
    )
    assert result.state == gate._LOOKUP_UNKNOWN


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


def _configure_main(monkeypatch, *, head_lookup=None, settings_loader=_default_settings):
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
    calls = {"n": 0}

    def _tree_lookup(**kwargs):
        calls["n"] += 1
        return _found() if calls["n"] == 1 else (head_lookup or _found())

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
    _configure_main(monkeypatch, head_lookup=_missing())
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
