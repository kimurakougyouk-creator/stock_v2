import subprocess

from signal_runner import _capture_process_start_strategy_source_sha_windows

_SHA = "d" * 40


def _ok(stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["git"], 0, stdout=stdout, stderr="")


def _fail() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess(["git"], 1, stdout="", stderr="error")


def _clean_sequence_responses(**overrides):
    """Five calls in order: rev-parse, status, ls-files(top *.py), ls-files -v, ls-files --others --ignored."""
    responses = {
        "rev-parse": _ok(_SHA + "\n"),
        "status": _ok(""),
        "top_py": _ok(""),
        "index": _ok(""),
        "ignored": _ok(""),
    }
    responses.update(overrides)
    return [responses["rev-parse"], responses["status"], responses["top_py"], responses["index"], responses["ignored"]]


def _install_sequence(monkeypatch, responses):
    calls = []

    def fake_run(command, **kwargs):
        calls.append(list(command))
        return responses[len(calls) - 1]

    monkeypatch.setattr("signal_runner.subprocess.run", fake_run)
    return calls


def test_windows_bootstrap_returns_sha_on_clean_repository(monkeypatch, tmp_path):
    responses = _clean_sequence_responses()
    calls = _install_sequence(monkeypatch, responses)

    result = _capture_process_start_strategy_source_sha_windows(tmp_path)

    assert result == _SHA
    assert calls[0] == ["git", "rev-parse", "HEAD"]
    assert calls[1][:3] == ["git", "status", "--porcelain=v1"]


def test_windows_bootstrap_rejects_malformed_sha(monkeypatch, tmp_path):
    responses = _clean_sequence_responses(**{"rev-parse": _ok("not-a-sha\n")})
    _install_sequence(monkeypatch, responses)

    assert _capture_process_start_strategy_source_sha_windows(tmp_path) is None


def test_windows_bootstrap_fails_closed_on_rev_parse_error(monkeypatch, tmp_path):
    responses = _clean_sequence_responses(**{"rev-parse": _fail()})
    _install_sequence(monkeypatch, responses)

    assert _capture_process_start_strategy_source_sha_windows(tmp_path) is None


def test_windows_bootstrap_rejects_dirty_tracked_or_untracked_source(monkeypatch, tmp_path):
    responses = _clean_sequence_responses(**{"status": _ok(" M signal_runner.py\n")})
    _install_sequence(monkeypatch, responses)

    assert _capture_process_start_strategy_source_sha_windows(tmp_path) is None


def test_windows_bootstrap_rejects_root_module_symlink_shadow(monkeypatch, tmp_path):
    (tmp_path / "evil.py").write_text("x = 1\n", encoding="utf-8")
    shadow_target = tmp_path / "shadow_target"
    shadow_target.mkdir()
    try:
        (tmp_path / "evil").symlink_to(shadow_target, target_is_directory=True)
    except (OSError, NotImplementedError):
        import pytest

        pytest.skip("symlinks are not permitted in this environment")

    responses = _clean_sequence_responses(**{"top_py": _ok("evil.py\n")})
    _install_sequence(monkeypatch, responses)

    assert _capture_process_start_strategy_source_sha_windows(tmp_path) is None


def test_windows_bootstrap_rejects_root_level_symlink(monkeypatch, tmp_path):
    target = tmp_path / "real_dir"
    target.mkdir()
    try:
        (tmp_path / "link").symlink_to(target, target_is_directory=True)
    except (OSError, NotImplementedError):
        import pytest

        pytest.skip("symlinks are not permitted in this environment")

    responses = _clean_sequence_responses()
    _install_sequence(monkeypatch, responses)

    assert _capture_process_start_strategy_source_sha_windows(tmp_path) is None


def test_windows_bootstrap_rejects_assume_unchanged_index_entry(monkeypatch, tmp_path):
    responses = _clean_sequence_responses(**{"index": _ok("h signal_runner.py\n")})
    _install_sequence(monkeypatch, responses)

    assert _capture_process_start_strategy_source_sha_windows(tmp_path) is None


def test_windows_bootstrap_rejects_skip_worktree_index_entry(monkeypatch, tmp_path):
    responses = _clean_sequence_responses(**{"index": _ok("S signal_runner.py\n")})
    _install_sequence(monkeypatch, responses)

    assert _capture_process_start_strategy_source_sha_windows(tmp_path) is None


def test_windows_bootstrap_rejects_ignored_importable_python_file(monkeypatch, tmp_path):
    responses = _clean_sequence_responses(**{"ignored": _ok("shadow_module.py\n")})
    _install_sequence(monkeypatch, responses)

    assert _capture_process_start_strategy_source_sha_windows(tmp_path) is None


def test_windows_bootstrap_rejects_ignored_importable_package_directory(monkeypatch, tmp_path):
    package_dir = tmp_path / "shadow_pkg"
    package_dir.mkdir()
    (package_dir / "__init__.py").write_text("", encoding="utf-8")

    responses = _clean_sequence_responses(**{"ignored": _ok("shadow_pkg\n")})
    _install_sequence(monkeypatch, responses)

    assert _capture_process_start_strategy_source_sha_windows(tmp_path) is None


def test_windows_bootstrap_allows_ignored_non_importable_artifact(monkeypatch, tmp_path):
    (tmp_path / "scratch.log").write_text("noise\n", encoding="utf-8")

    responses = _clean_sequence_responses(**{"ignored": _ok("scratch.log\n")})
    _install_sequence(monkeypatch, responses)

    assert _capture_process_start_strategy_source_sha_windows(tmp_path) == _SHA


def test_capture_process_start_strategy_source_sha_dispatches_to_windows_branch(monkeypatch, tmp_path):
    import signal_runner

    monkeypatch.setattr(signal_runner.os, "name", "nt")
    monkeypatch.setattr(
        signal_runner,
        "_capture_process_start_strategy_source_sha_windows",
        lambda: "windows-branch-result",
    )

    assert signal_runner._capture_process_start_strategy_source_sha() == "windows-branch-result"


def test_capture_process_start_strategy_source_sha_keeps_posix_branch_unchanged(monkeypatch, tmp_path):
    import signal_runner

    monkeypatch.setattr(signal_runner.os, "name", "posix")

    def fake_run(command, **kwargs):
        assert command == [
            "/bin/bash",
            "--noprofile",
            "--norc",
            "scripts/verify_strategy_source_clean.sh",
        ]
        return subprocess.CompletedProcess(
            command, 0, stdout="STRATEGY_SOURCE_SHA=" + ("e" * 40) + "\n", stderr=""
        )

    monkeypatch.setattr(signal_runner.subprocess, "run", fake_run)

    assert signal_runner._capture_process_start_strategy_source_sha() == "e" * 40
