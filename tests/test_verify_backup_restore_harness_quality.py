from pathlib import Path


SCRIPT = Path("scripts/verify_backup_restore_env_secrets_windows.ps1")


def _text() -> str:
    assert SCRIPT.exists(), f"missing required file: {SCRIPT}"
    return SCRIPT.read_text(encoding="utf-8")


def test_invoke_check_treats_skip_as_a_distinct_status_not_a_pass():
    # Work independent audit V3 (PR #365 comment 6397370183, point 3):
    # an earlier revision's skip path returned $true, so Invoke-Check
    # counted a genuinely-skipped check as a PASS in the summary --
    # indistinguishable from a real pass. SKIP must be its own status,
    # counted separately, and the skip path in this harness must use it.
    script = _text()
    assert '$outcome -eq "SKIP"' in script
    assert 'Status = "SKIP"' in script
    assert "$skipCount" in script
    assert '"SKIP"\n            }' in script or '"SKIP"\n                }' in script


def test_new_verified_junction_checks_exit_code_and_reparse_point_before_trusting_it():
    # Work independent audit V3 (PR #365 comment 6397370183, point 2):
    # an earlier revision called mklink directly inside the same
    # try/catch that was also supposed to catch Backup-EnvSecrets'
    # expected safety rejection, so a failed mklink and a genuine
    # rejection were indistinguishable. New-VerifiedJunction must check
    # mklink's own exit code and that the result is really a reparse
    # point, and must be called OUTSIDE each check's inner try/catch.
    script = _text()
    fn_start = script.index("function New-VerifiedJunction")
    fn_body = script[fn_start:script.index("function Test-IsPrivateOwnerOnlyAcl")]
    assert "$LASTEXITCODE -ne 0" in fn_body
    assert "ReparsePoint" in fn_body
    for check_name in (
        "backup_rejects_junction_as_immediate_parent",
        "backup_rejects_junction_one_level_above_immediate_parent",
    ):
        check_start = script.index(f'Invoke-Check "{check_name}"')
        check_end = script.index("\n    }\n", check_start)
        check_body = script[check_start:check_end]
        junction_at = check_body.index("New-VerifiedJunction")
        try_at = check_body.index("try {")
        assert junction_at < try_at, (
            f"{check_name}: New-VerifiedJunction must run before (outside) the "
            "inner try/catch that is meant to catch the expected safety rejection"
        )


def test_owner_only_acl_check_verifies_sid_rights_and_inheritance_not_just_count():
    # Work independent audit V3 (PR #365 comment 6397370183, point 2):
    # an earlier revision asserted only `Access.Count -eq 1`, true for
    # exactly one rule of ANY kind. This must check the rule is
    # specifically Allow, FullControl, not inherited, and for the
    # current Windows identity.
    script = _text()
    fn_start = script.index("function Test-IsPrivateOwnerOnlyAcl")
    fn_body = script[fn_start:script.index("function Add-DenyWriteAcl")]
    assert "IsInherited" in fn_body
    assert "AccessControlType]::Allow" in fn_body
    assert "FileSystemRights]::FullControl" in fn_body
    assert "SecurityIdentifier" in fn_body
    assert "restored_file_has_owner_only_full_control_acl" in script
    check_start = script.index('Invoke-Check "restored_file_has_owner_only_full_control_acl"')
    check_end = script.index("\n    }\n", check_start)
    check_body = script[check_start:check_end]
    assert "Access.Count -eq 1" not in check_body
    assert "Test-IsPrivateOwnerOnlyAcl -Path $Restored" in check_body


def test_gemini_check_is_isolated_into_a_dummy_repo_not_the_real_checkout():
    # Work independent audit V3 (PR #365 comment 6397370183, point 4):
    # an earlier revision invoked verify_gemini_env_key_windows.ps1
    # against the REAL repository checkout, requiring a real .env
    # there and reading it through the real settings loader --
    # contradicting this harness's own "never touches a real secret"
    # claim. This must run against an isolated dummy repo under
    # $TestRoot instead, with its own placeholder .env.
    script = _text()
    assert "dummy_gemini_repo" in script
    assert "IBKR_REPO_DIR" in script
    assert "dummy-harness-placeholder" in script
    gemini_check_start = script.index("verify_gemini_env_key_isolated_dummy_repo")
    gemini_check_body = script[gemini_check_start:gemini_check_start + 2500]
    assert "New-VerifiedJunction" in gemini_check_body


def test_backup_and_restore_failure_injection_checks_exercise_real_functions():
    # Work independent audit V3 (PR #365 comment 6397370183, point 1):
    # no prior check exercised a genuine ACL/move failure through the
    # real Backup-EnvSecrets/Restore-EnvSecrets functions -- only the
    # bare Move-Item primitive was checked, in isolation. These checks
    # must inject a real OS-enforced Deny rule and call the actual
    # production functions, verifying they fail closed.
    script = _text()
    assert "function Add-DenyWriteAcl" in script
    assert "function Remove-DenyWriteAcl" in script
    assert "backup_fails_closed_when_the_backup_directory_denies_write" in script
    assert "restore_fails_closed_when_the_destination_directory_denies_write" in script
    for check_name in (
        "backup_fails_closed_when_the_backup_directory_denies_write",
        "restore_fails_closed_when_the_destination_directory_denies_write",
    ):
        check_start = script.index(f'Invoke-Check "{check_name}"')
        check_end = script.index("\n    }\n", check_start)
        check_body = script[check_start:check_end]
        assert "Add-DenyWriteAcl" in check_body
        assert "Remove-DenyWriteAcl" in check_body


def test_results_counts_use_array_subexpression_to_avoid_single_item_unwrap():
    # PowerShell's Where-Object unwraps a single matching result to a
    # bare object instead of a one-element array, so `.Count` throws
    # PropertyNotFoundStrict when exactly one item matches. Every count
    # here must be wrapped in @(...) to stay an array regardless of
    # how many results match.
    script = _text()
    for status in ("PASS", "FAIL", "SKIP"):
        assert f'@($results | Where-Object {{ $_.Status -eq "{status}" }}).Count' in script
