from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

_SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "live_pilot_release_gate.py"
_SPEC = importlib.util.spec_from_file_location("live_pilot_release_gate", _SCRIPT_PATH)
gate = importlib.util.module_from_spec(_SPEC)
assert _SPEC.loader is not None
sys.modules[_SPEC.name] = gate
_SPEC.loader.exec_module(gate)


HEAD_SHA = "a" * 40


def _default_settings() -> SimpleNamespace:
    return SimpleNamespace(
        enable_live_trading=False,
        run_mode="DEVELOPMENT",
        live_trading_unlocked=False,
    )


def _evaluate(**overrides):
    params = {
        "checked_out_sha": HEAD_SHA,
        "pr_head_sha": HEAD_SHA,
        "base_ref": "main",
        "expected_base_sha": HEAD_SHA,
        "get_default_settings": _default_settings,
        "changed_file_paths": [],
        "unresolved_review_thread_count": 0,
        "issue_255_state": "open",
    }
    params.update(overrides)
    return gate.evaluate_release_gate(**params)


def test_clean_evidence_passes():
    result = _evaluate()
    assert result.status == gate.PASS


def test_valid_hex_pr_head_sha_passes():
    result = _evaluate(pr_head_sha="b" * 40)
    assert result.status == gate.PASS


def test_uppercase_hex_pr_head_sha_passes():
    result = _evaluate(pr_head_sha=("b" * 40).upper())
    assert result.status == gate.PASS


def test_missing_pr_head_sha_fails():
    result = _evaluate(pr_head_sha=None)
    assert result.status == gate.FAIL
    assert any(
        "pr-head-sha-present" in reason and "missing" in reason for reason in result.reasons
    )


def test_wrong_length_pr_head_sha_fails():
    result = _evaluate(pr_head_sha="a" * 39)
    assert result.status == gate.FAIL
    assert any("pr-head-sha-present" in reason for reason in result.reasons)


def test_non_hex_pr_head_sha_fails():
    result = _evaluate(pr_head_sha="g" * 40)
    assert result.status == gate.FAIL
    assert any("pr-head-sha-present" in reason for reason in result.reasons)


def test_checked_out_sha_matches_expected_base_passes():
    result = _evaluate(checked_out_sha=HEAD_SHA, expected_base_sha=HEAD_SHA)
    assert result.status == gate.PASS


def test_checked_out_sha_mismatched_with_expected_base_fails():
    result = _evaluate(checked_out_sha=HEAD_SHA, expected_base_sha="b" * 40)
    assert result.status == gate.FAIL
    assert any(
        "checked-out-matches-base" in reason and "does not match" in reason
        for reason in result.reasons
    )


def test_missing_checked_out_sha_fails_against_a_known_expected_base():
    result = _evaluate(checked_out_sha="", expected_base_sha=HEAD_SHA)
    assert result.status == gate.FAIL
    assert any("checked-out-matches-base" in reason for reason in result.reasons)


def test_expected_base_sha_missing_is_unknown_not_ignored():
    result = _evaluate(expected_base_sha=None)
    assert result.status == gate.UNKNOWN
    assert any(
        "checked-out-matches-base" in reason and "expected base sha" in reason
        for reason in result.reasons
    )


def test_base_branch_other_than_main_fails():
    for bad_base in ("develop", "release/1.0", "", None):
        result = _evaluate(base_ref=bad_base)
        assert result.status == gate.FAIL, bad_base


def test_live_trading_unlocked_by_default_fails_closed():
    unsafe = SimpleNamespace(
        enable_live_trading=True,
        run_mode="DEVELOPMENT",
        live_trading_unlocked=False,
    )
    result = _evaluate(get_default_settings=lambda: unsafe)
    assert result.status == gate.FAIL
    assert any("live-disabled-by-default" in reason for reason in result.reasons)

    unsafe_live_mode = SimpleNamespace(
        enable_live_trading=False,
        run_mode="LIVE",
        live_trading_unlocked=False,
    )
    result = _evaluate(get_default_settings=lambda: unsafe_live_mode)
    assert result.status == gate.FAIL


def test_settings_lookup_failure_is_unknown_not_pass():
    def _raise():
        raise ImportError("settings module moved")

    result = _evaluate(get_default_settings=_raise)
    assert result.status == gate.UNKNOWN


def test_settings_with_unexpected_shape_is_unknown():
    malformed = SimpleNamespace(
        enable_live_trading="false",  # wrong type, not a bool
        run_mode="DEVELOPMENT",
        live_trading_unlocked=False,
    )
    result = _evaluate(get_default_settings=lambda: malformed)
    assert result.status == gate.UNKNOWN


def test_pr_modifying_settings_file_fails_closed():
    result = _evaluate(
        changed_file_paths=[
            "README.md",
            "src/ai_asset_platform/core/settings.py",
        ]
    )
    assert result.status == gate.FAIL
    assert any(
        "settings-file-not-modified" in reason and "settings.py" in reason
        for reason in result.reasons
    )


def test_pr_not_modifying_settings_file_passes():
    result = _evaluate(changed_file_paths=["README.md", "tests/test_foo.py"])
    assert result.status == gate.PASS


def test_missing_changed_file_paths_is_unknown_not_ignored():
    result = _evaluate(changed_file_paths=None)
    assert result.status == gate.UNKNOWN
    assert any(
        "settings-file-not-modified" in reason and "could not be retrieved" in reason
        for reason in result.reasons
    )


def test_check_settings_file_not_modified_by_pr_directly():
    status, _ = gate.check_settings_file_not_modified_by_pr(changed_file_paths=None)
    assert status == gate.UNKNOWN

    status, _ = gate.check_settings_file_not_modified_by_pr(
        changed_file_paths=["src/ai_asset_platform/core/settings.py"]
    )
    assert status == gate.FAIL

    status, _ = gate.check_settings_file_not_modified_by_pr(changed_file_paths=["README.md"])
    assert status == gate.PASS


def test_review_thread_fetch_failure_is_unknown_not_ignored():
    result = _evaluate(unresolved_review_thread_count=None)
    assert result.status == gate.UNKNOWN
    assert any(
        "unresolved-review-threads" in reason and "UNKNOWN" in reason
        for reason in result.reasons
    )


def test_review_thread_count_never_changes_pass_fail_verdict():
    """The count is display-only: 0, a large number, all yield the same

    overall verdict as long as every other check is clean.
    """
    baseline = _evaluate(unresolved_review_thread_count=0).status
    for count in (1, 7, 500):
        result = _evaluate(unresolved_review_thread_count=count)
        assert result.status == baseline == gate.PASS


def test_issue_255_fetch_failure_is_unknown_not_ignored():
    result = _evaluate(issue_255_state=None)
    assert result.status == gate.UNKNOWN
    assert any(
        "issue-255-state" in reason and "UNKNOWN" in reason for reason in result.reasons
    )


def test_issue_255_state_never_changes_pass_fail_verdict():
    """The state is display-only: neither "open" nor "closed" (nor any other

    string) should ever flip PASS/FAIL on its own.
    """
    for state in ("open", "closed", "unexpected-value"):
        result = _evaluate(issue_255_state=state)
        assert result.status == gate.PASS


def test_fail_takes_precedence_over_unknown():
    result = _evaluate(
        pr_head_sha=None,  # FAIL
        unresolved_review_thread_count=None,  # would be UNKNOWN alone
    )
    assert result.status == gate.FAIL


def test_live_execution_constant_is_always_the_fixed_no_go_literal():
    assert gate.LIVE_EXECUTION_VALUE == "NO-GO"


def test_main_always_prints_fixed_no_go_regardless_of_gate_outcome(monkeypatch, capsys):
    monkeypatch.setattr(gate, "_load_event_payload", lambda: {
        "pull_request": {
            "number": 281,
            "head": {"sha": HEAD_SHA},
            "base": {"ref": "main", "sha": HEAD_SHA},
        }
    })
    monkeypatch.setattr(gate, "_git_head_sha", lambda: HEAD_SHA)
    monkeypatch.setattr(
        gate, "fetch_unresolved_review_thread_count", lambda **kwargs: 3
    )
    monkeypatch.setattr(gate, "fetch_issue_state", lambda **kwargs: "open")
    monkeypatch.setattr(gate, "fetch_pr_changed_file_paths", lambda **kwargs: ["README.md"])
    monkeypatch.setenv("GITHUB_TOKEN", "test-token")
    monkeypatch.setenv("GITHUB_REPOSITORY", "kimurakougyouk-creator/stock_v2")

    exit_code = gate.main()
    output = capsys.readouterr().out
    assert "LIVE_EXECUTION=NO-GO" in output
    assert exit_code == 0
    assert "RELEASE_INTEGRITY_GATE=PASS" in output

    # Now force a FAIL and confirm LIVE_EXECUTION is still the same fixed literal.
    monkeypatch.setattr(gate, "_git_head_sha", lambda: "b" * 40)
    exit_code = gate.main()
    output = capsys.readouterr().out
    assert "LIVE_EXECUTION=NO-GO" in output
    assert exit_code != 0
    assert "RELEASE_INTEGRITY_GATE=FAIL" in output


def test_main_survives_settings_import_failure_as_unknown_not_a_crash(monkeypatch, capsys):
    """If ``ai_asset_platform.core.settings`` cannot be imported at all (e.g.

    PYTHONPATH is wrong, or the module was moved/renamed), main() must still
    print both required lines and exit non-zero as UNKNOWN -- never crash
    with an unhandled traceback, and never silently treat the failure as
    PASS.
    """
    monkeypatch.setattr(
        gate,
        "_load_event_payload",
        lambda: {
            "pull_request": {
                "number": 281,
                "head": {"sha": HEAD_SHA},
                "base": {"ref": "main", "sha": HEAD_SHA},
            }
        },
    )
    monkeypatch.setattr(gate, "_git_head_sha", lambda: HEAD_SHA)
    monkeypatch.setattr(gate, "fetch_unresolved_review_thread_count", lambda **kwargs: 0)
    monkeypatch.setattr(gate, "fetch_issue_state", lambda **kwargs: "open")
    monkeypatch.setattr(gate, "fetch_pr_changed_file_paths", lambda **kwargs: ["README.md"])

    def _raise_module_not_found():
        raise ModuleNotFoundError("No module named 'ai_asset_platform'")

    monkeypatch.setattr(gate, "_load_platform_settings", _raise_module_not_found)

    exit_code = gate.main()  # must not raise

    output = capsys.readouterr().out
    assert "RELEASE_INTEGRITY_GATE=UNKNOWN" in output
    assert "LIVE_EXECUTION=NO-GO" in output
    assert exit_code != 0


def test_check_pr_head_sha_present_accepts_upper_or_lower_case_hex():
    status, _ = gate.check_pr_head_sha_present(HEAD_SHA.upper())
    assert status == gate.PASS

    status, _ = gate.check_pr_head_sha_present(HEAD_SHA)
    assert status == gate.PASS


def test_check_pr_head_sha_present_rejects_malformed_values():
    status, _ = gate.check_pr_head_sha_present(None)
    assert status == gate.FAIL

    status, _ = gate.check_pr_head_sha_present("a" * 39)
    assert status == gate.FAIL

    status, _ = gate.check_pr_head_sha_present("g" * 40)
    assert status == gate.FAIL


def test_check_checked_out_matches_expected_base_is_case_insensitive_but_exact():
    status, _ = gate.check_checked_out_matches_expected_base(HEAD_SHA.upper(), HEAD_SHA)
    assert status == gate.PASS

    status, _ = gate.check_checked_out_matches_expected_base(HEAD_SHA[:-1] + "0", HEAD_SHA)
    assert status == gate.FAIL

    status, _ = gate.check_checked_out_matches_expected_base(HEAD_SHA, None)
    assert status == gate.UNKNOWN


def test_fetch_helpers_return_none_on_network_failure(monkeypatch):
    def _raise_urlopen(*args, **kwargs):
        raise OSError("simulated network failure")

    monkeypatch.setattr(gate.urllib.request, "urlopen", _raise_urlopen)

    assert (
        gate.fetch_unresolved_review_thread_count(
            repo="kimurakougyouk-creator/stock_v2", pr_number=281, token="tok"
        )
        is None
    )
    assert (
        gate.fetch_issue_state(
            repo="kimurakougyouk-creator/stock_v2", issue_number=255, token="tok"
        )
        is None
    )


def test_fetch_helpers_return_none_without_token_or_repo():
    assert (
        gate.fetch_unresolved_review_thread_count(repo="", pr_number=281, token="tok") is None
    )
    assert (
        gate.fetch_unresolved_review_thread_count(
            repo="kimurakougyouk-creator/stock_v2", pr_number=281, token=None
        )
        is None
    )
    assert gate.fetch_issue_state(repo="", issue_number=255, token="tok") is None


def test_fetch_pr_changed_file_paths_returns_none_on_network_failure(monkeypatch):
    def _raise_urlopen(*args, **kwargs):
        raise OSError("simulated network failure")

    monkeypatch.setattr(gate.urllib.request, "urlopen", _raise_urlopen)

    assert (
        gate.fetch_pr_changed_file_paths(
            repo="kimurakougyouk-creator/stock_v2", pr_number=281, token="tok"
        )
        is None
    )


def test_fetch_pr_changed_file_paths_returns_none_without_token_or_repo():
    assert gate.fetch_pr_changed_file_paths(repo="", pr_number=281, token="tok") is None
    assert (
        gate.fetch_pr_changed_file_paths(
            repo="kimurakougyouk-creator/stock_v2", pr_number=281, token=None
        )
        is None
    )


class _FakeResponse:
    def __init__(self, body, link_header=None):
        self._body = json.dumps(body).encode("utf-8")
        self.headers = {"Link": link_header} if link_header else {}

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc_info):
        return False


def _dispatching_urlopen(*, metadata_body, file_pages):
    """Route by URL: the bare .../pulls/{n} metadata call vs. .../files pages.

    ``file_pages`` is consumed in order on every call to the ``.../files``
    URL (the first page's URL, then whatever ``Link: rel="next"`` URLs it
    yields) -- one response per call, regardless of the URL's query string.
    """
    remaining_pages = list(file_pages)

    def _fake_urlopen(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else request
        if isinstance(url, str) and url.rstrip("/").endswith("/pulls/281"):
            return _FakeResponse(metadata_body)
        return remaining_pages.pop(0)

    return _fake_urlopen


def test_fetch_pr_changed_file_paths_follows_pagination_when_count_matches(monkeypatch):
    page_1 = [{"filename": "a.py"}, {"filename": "b.py"}]
    page_2 = [{"filename": "c.py"}]
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        _dispatching_urlopen(
            metadata_body={"changed_files": 3},
            file_pages=[
                _FakeResponse(page_1, link_header='<https://api.github.com/next-page>; rel="next"'),
                _FakeResponse(page_2),
            ],
        ),
    )

    result = gate.fetch_pr_changed_file_paths(
        repo="kimurakougyouk-creator/stock_v2", pr_number=281, token="tok"
    )
    assert result == ["a.py", "b.py", "c.py"]


def test_fetch_pr_changed_file_paths_none_when_actual_count_is_less_than_reported(monkeypatch):
    page_1 = [{"filename": "a.py"}, {"filename": "b.py"}, {"filename": "c.py"}]
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        _dispatching_urlopen(
            metadata_body={"changed_files": 4},
            file_pages=[_FakeResponse(page_1)],
        ),
    )

    result = gate.fetch_pr_changed_file_paths(
        repo="kimurakougyouk-creator/stock_v2", pr_number=281, token="tok"
    )
    assert result is None


def test_fetch_pr_changed_file_paths_none_when_changed_files_exceeds_3000(monkeypatch):
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        _dispatching_urlopen(metadata_body={"changed_files": 3001}, file_pages=[]),
    )

    result = gate.fetch_pr_changed_file_paths(
        repo="kimurakougyouk-creator/stock_v2", pr_number=281, token="tok"
    )
    assert result is None


def test_fetch_pr_changed_file_paths_none_when_changed_files_is_bool(monkeypatch):
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        _dispatching_urlopen(metadata_body={"changed_files": True}, file_pages=[]),
    )

    result = gate.fetch_pr_changed_file_paths(
        repo="kimurakougyouk-creator/stock_v2", pr_number=281, token="tok"
    )
    assert result is None


def test_fetch_pr_changed_file_paths_none_when_changed_files_is_negative(monkeypatch):
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        _dispatching_urlopen(metadata_body={"changed_files": -1}, file_pages=[]),
    )

    result = gate.fetch_pr_changed_file_paths(
        repo="kimurakougyouk-creator/stock_v2", pr_number=281, token="tok"
    )
    assert result is None


def test_fetch_pr_changed_file_paths_none_when_changed_files_is_missing_or_wrong_type(monkeypatch):
    for malformed_metadata in ({}, {"changed_files": "3"}, {"changed_files": 3.0}, {"changed_files": None}):
        monkeypatch.setattr(
            gate.urllib.request,
            "urlopen",
            _dispatching_urlopen(metadata_body=malformed_metadata, file_pages=[]),
        )
        result = gate.fetch_pr_changed_file_paths(
            repo="kimurakougyouk-creator/stock_v2", pr_number=281, token="tok"
        )
        assert result is None, malformed_metadata


def test_fetch_pr_changed_file_paths_none_when_an_entry_is_missing_filename(monkeypatch):
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        _dispatching_urlopen(
            metadata_body={"changed_files": 2},
            file_pages=[_FakeResponse([{"filename": "a.py"}, {"status": "modified"}])],
        ),
    )

    result = gate.fetch_pr_changed_file_paths(
        repo="kimurakougyouk-creator/stock_v2", pr_number=281, token="tok"
    )
    assert result is None


def test_fetch_pr_changed_file_paths_none_when_an_entry_filename_is_empty(monkeypatch):
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        _dispatching_urlopen(
            metadata_body={"changed_files": 2},
            file_pages=[_FakeResponse([{"filename": "a.py"}, {"filename": ""}])],
        ),
    )

    result = gate.fetch_pr_changed_file_paths(
        repo="kimurakougyouk-creator/stock_v2", pr_number=281, token="tok"
    )
    assert result is None


def test_fetch_pr_changed_file_paths_none_when_an_entry_filename_has_wrong_type(monkeypatch):
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        _dispatching_urlopen(
            metadata_body={"changed_files": 2},
            file_pages=[_FakeResponse([{"filename": "a.py"}, {"filename": 123}])],
        ),
    )

    result = gate.fetch_pr_changed_file_paths(
        repo="kimurakougyouk-creator/stock_v2", pr_number=281, token="tok"
    )
    assert result is None


def test_fetch_pr_changed_file_paths_none_when_an_entry_is_not_a_dict(monkeypatch):
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        _dispatching_urlopen(
            metadata_body={"changed_files": 2},
            file_pages=[_FakeResponse([{"filename": "a.py"}, "not-a-dict"])],
        ),
    )

    result = gate.fetch_pr_changed_file_paths(
        repo="kimurakougyouk-creator/stock_v2", pr_number=281, token="tok"
    )
    assert result is None


def test_fetch_pr_changed_file_paths_none_on_duplicate_filenames(monkeypatch):
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        _dispatching_urlopen(
            metadata_body={"changed_files": 2},
            file_pages=[_FakeResponse([{"filename": "a.py"}, {"filename": "a.py"}])],
        ),
    )

    result = gate.fetch_pr_changed_file_paths(
        repo="kimurakougyouk-creator/stock_v2", pr_number=281, token="tok"
    )
    assert result is None


def test_fetch_pr_changed_file_paths_includes_settings_py_when_present(monkeypatch):
    monkeypatch.setattr(
        gate.urllib.request,
        "urlopen",
        _dispatching_urlopen(
            metadata_body={"changed_files": 2},
            file_pages=[
                _FakeResponse(
                    [
                        {"filename": "README.md"},
                        {"filename": "src/ai_asset_platform/core/settings.py"},
                    ]
                )
            ],
        ),
    )

    result = gate.fetch_pr_changed_file_paths(
        repo="kimurakougyouk-creator/stock_v2", pr_number=281, token="tok"
    )
    assert result == ["README.md", "src/ai_asset_platform/core/settings.py"]

    status, _ = gate.check_settings_file_not_modified_by_pr(changed_file_paths=result)
    assert status == gate.FAIL


def test_fetch_pr_changed_file_paths_gives_up_as_none_if_pages_exceed_cap(monkeypatch):
    def _fake_urlopen(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else request
        if isinstance(url, str) and url.rstrip("/").endswith("/pulls/281"):
            return _FakeResponse({"changed_files": gate._MAX_FILES_PER_PR})
        return _FakeResponse(
            [{"filename": "a.py"}],
            link_header='<https://api.github.com/next-page>; rel="next"',
        )

    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen)

    result = gate.fetch_pr_changed_file_paths(
        repo="kimurakougyouk-creator/stock_v2", pr_number=281, token="tok"
    )
    assert result is None


def test_fetch_pr_changed_file_paths_none_when_files_page_fetch_fails_after_metadata_ok(
    monkeypatch,
):
    def _fake_urlopen(request, timeout=None):
        url = request.full_url if hasattr(request, "full_url") else request
        if isinstance(url, str) and url.rstrip("/").endswith("/pulls/281"):
            return _FakeResponse({"changed_files": 1})
        raise OSError("simulated network failure fetching files page")

    monkeypatch.setattr(gate.urllib.request, "urlopen", _fake_urlopen)

    result = gate.fetch_pr_changed_file_paths(
        repo="kimurakougyouk-creator/stock_v2", pr_number=281, token="tok"
    )
    assert result is None


def test_fetch_pr_changed_files_count_returns_none_on_network_failure(monkeypatch):
    def _raise_urlopen(*args, **kwargs):
        raise OSError("simulated network failure")

    monkeypatch.setattr(gate.urllib.request, "urlopen", _raise_urlopen)

    assert (
        gate._fetch_pr_changed_files_count(
            repo="kimurakougyouk-creator/stock_v2", pr_number=281, token="tok"
        )
        is None
    )
