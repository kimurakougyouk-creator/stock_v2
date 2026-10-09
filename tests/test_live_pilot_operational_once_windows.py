"""Structural checks for live_pilot_operational_once.ps1.

This mirrors the static-assertion style already used for
ibkr_readonly_autopilot_windows.ps1 (see test_ibkr_windows_readonly_autopilot.py)
rather than the subprocess-fixture style used for the bash wrapper's own
tests: PowerShell execution policy and the interpreter-trust checks here
(the `py` launcher, Get-AuthenticodeSignature) are not easily faked in a
hermetic unit test, so this file instead asserts the script's actual
tracked text never regresses on the specific safety properties the
companion manual Windows-machine verification exercised at runtime (see
the fix/live-pilot-windows-operational-entrypoint-script PR description
for that empirical evidence: every BLOCKED branch was actually triggered
and actually fails closed with exit code 2, and the happy path reaches
the real production entrypoint's own BLOCKED_AUTHORIZATION_BINDING gate
with ORDER TRANSPORT CALLED: False).
"""
from pathlib import Path


SCRIPT = Path("live_pilot_operational_once.ps1")


def _text() -> str:
    assert SCRIPT.exists(), f"missing required file: {SCRIPT}"
    return SCRIPT.read_text(encoding="utf-8")


def test_windows_entrypoint_never_sends_or_mutates_broker_state():
    script = _text()
    assert "placeOrder(" not in script
    assert "cancelOrder(" not in script
    assert "reqGlobalCancel(" not in script
    assert "git pull" not in script.lower()
    assert "git fetch" not in script.lower()
    assert "git push" not in script.lower()


def test_windows_entrypoint_blocks_before_required_env_vars_checked():
    script = _text()
    required = [
        "LIVE_PILOT_INTENT_ID", "LIVE_PILOT_TICKER", "LIVE_PILOT_SIDE",
        "LIVE_PILOT_QUANTITY", "LIVE_PILOT_LIMIT_PRICE",
        "LIVE_PILOT_NOTIONAL_JPY", "LIVE_PILOT_NONCE",
        "LIVE_PILOT_ACCOUNT_FINGERPRINT", "LIVE_PILOT_EXPECTED_COMMIT_SHA",
    ]
    for name in required:
        assert name in script, f"{name} is no longer checked"
    interpreter_check_at = script.index("Get-AuthenticodeSignature")
    required_vars_at = script.index("$RequiredVars")
    sha_check_at = script.index("$ActualSha = (& $TrustedGit @GitSafeArgs rev-parse HEAD)")
    assert interpreter_check_at < required_vars_at, (
        "trusted-interpreter attestation must run before required-value checks, "
        "matching the bash wrapper's own ordering"
    )
    assert required_vars_at < sha_check_at


def test_windows_entrypoint_checks_dirty_tree_and_hidden_index_before_launch():
    script = _text()
    dirty_at = script.index("$SourceDirty")
    hidden_at = script.index("$IndexHidden")
    ignored_at = script.index("$IgnoredImportable")
    ibapi_at = script.index("verify_live_ibapi_runtime.py")
    tzdata_at = script.index("verify_live_tzdata_runtime.py")
    bootstrap_at = script.index("live_pilot_operational_entrypoint")
    assert dirty_at < hidden_at < ignored_at < ibapi_at < tzdata_at < bootstrap_at


def test_windows_entrypoint_index_hidden_regex_is_case_sensitive():
    # Regression guard for the bug caught during manual verification:
    # PowerShell's default -match is case-insensitive, which made the normal
    # "H" (tracked, no special state) git ls-files flag falsely match the
    # lowercase a-z class meant to catch only assume-unchanged/skip-worktree
    # entries, blocking every ordinary clean checkout. -cmatch is required.
    script = _text()
    assert "-cmatch '^[Sa-z] '" in script
    assert "-match '^[Sa-z] '" not in script


def test_windows_entrypoint_uses_flag_equals_value_for_python_args():
    # Regression guard for the bug caught during manual verification:
    # PowerShell drops an empty string entirely when passed as a separate
    # argument to a native executable, silently shifting every later
    # argument by one position and corrupting argparse's view of argv.
    # --flag=value keeps a (possibly empty) value attached to its flag.
    script = _text()
    assert '"--final-confirmation=$FinalConfirmation"' in script
    assert "--final-confirmation $FinalConfirmation" not in script


def test_windows_entrypoint_defaults_final_confirmation_empty():
    script = _text()
    default_at = script.index('if (-not $FinalConfirmation) { $FinalConfirmation = "" }')
    use_at = script.index('"--final-confirmation=$FinalConfirmation"')
    assert default_at < use_at


def test_windows_entrypoint_pins_live_readonly_confirmation():
    script = _text()
    assert '"--live-readonly-confirmation=READ_LIVE_ACCOUNT_ONLY"' in script


def test_windows_entrypoint_rejects_interpreter_inside_venv():
    script = _text()
    assert "$VenvRootFull" in script
    assert "StartsWith($VenvRootFull" in script


def test_windows_entrypoint_requires_python_software_foundation_signer():
    script = _text()
    assert 'SignerSubject -notmatch "O=Python Software Foundation"' in script


def test_windows_entrypoint_sets_pythontzpath_only_after_verification():
    script = _text()
    verify_at = script.index("verify_live_tzdata_runtime.py")
    block_at = script.index('Block "venv tzdata dependency does not match the pinned runtime manifest."')
    set_at = script.index("$env:PYTHONTZPATH = $TzdataVerifiedCopy")
    assert verify_at < block_at < set_at


def test_windows_entrypoint_verifies_a_copy_not_the_writable_venv_directory():
    # Regression guard for the Codex-caught TOCTOU finding: a hostile write
    # to the still-writable venv tzdata directory after verification but
    # before use must not be able to change the bytes PYTHONTZPATH serves.
    # Verification and PYTHONTZPATH must both target the same immutable
    # process-local copy, not the original source directory.
    script = _text()
    copy_at = script.index("Copy-Item -LiteralPath $TzdataSourceDir -Destination $TzdataVerifiedCopy")
    verify_at = script.index('$TzdataVerifier --zoneinfo-dir $TzdataVerifiedCopy')
    set_at = script.index("$env:PYTHONTZPATH = $TzdataVerifiedCopy")
    assert copy_at < verify_at < set_at


def test_windows_entrypoint_rejects_tzdata_reparse_points_before_verification():
    # Regression guard: Python's Path.is_symlink() is not guaranteed to
    # recognize an NTFS junction, so the PowerShell layer must reject any
    # reparse point (symlink or junction) before the Python verifier runs.
    script = _text()
    reparse_at = script.index("$TzdataReparsePoints")
    copy_at = script.index("Copy-Item -LiteralPath $TzdataSourceDir")
    assert reparse_at < copy_at


def test_windows_entrypoint_resolves_python_from_hklm_registry_only():
    # Regression guard for the Codex-caught findings that (a) executing a
    # bare `py` before attestation lets a hijacked PATH run arbitrary code
    # first, and (b) an Authenticode signature on python.exe alone does not
    # attest python313.dll or the standard library on a writable per-user
    # install. HKLM-only registry resolution plus an admin-only-root
    # directory check closes both without executing anything first.
    script = _text()
    assert "HKLM:\\SOFTWARE\\Python\\PythonCore\\$PinnedPythonVersion\\InstallPath" in script
    assert "HKCU:\\SOFTWARE\\Python" not in script
    assert 'py "-$PinnedPythonVersion"' not in script


def test_windows_entrypoint_resolves_git_from_admin_only_root_not_path():
    script = _text()
    assert "$TrustedGit" in script
    assert "GitCandidateSuffixes" in script
    assert "& git rev-parse" not in script
    assert "& git status" not in script
    assert "& git ls-files" not in script


def test_windows_entrypoint_clears_git_discovery_env_vars():
    script = _text()
    for name in (
        "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_CEILING_DIRECTORIES",
        "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES",
    ):
        assert name in script


def test_tzdata_manifest_matches_pinned_version():
    import subprocess
    import sys as _sys

    result = subprocess.run(
        [
            _sys.executable, "-I",
            "scripts/emit_live_tzdata_manifest.py",
            "--check", "scripts/live_tzdata_manifest.json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_requirements_pins_exact_tzdata_version_matching_manifest():
    import json

    requirements = Path("requirements.txt").read_text(encoding="utf-8")
    manifest = json.loads(Path("scripts/live_tzdata_manifest.json").read_text(encoding="utf-8"))
    pinned_version = manifest["version"]
    assert f"tzdata=={pinned_version}" in requirements
