from pathlib import Path


SCRIPT = Path("backup_restore_env_secrets_windows.ps1")


def _text() -> str:
    assert SCRIPT.exists(), f"missing required file: {SCRIPT}"
    return SCRIPT.read_text(encoding="utf-8")


def test_backup_restore_env_secrets_uses_dpapi_not_a_hardcoded_key():
    # Recurrence-prevention follow-up to the 2026-10-25 .env loss incident:
    # the repo had no backup for .env at all. This script must encrypt with
    # the Windows Data Protection API (ConvertTo-SecureString with no -Key,
    # which binds ciphertext to the current user+machine) rather than any
    # fixed/hardcoded symmetric key that could itself leak or be reused
    # across machines.
    script = _text()
    assert "ConvertTo-SecureString -String $plainBase64 -AsPlainText -Force" in script
    assert "ConvertFrom-SecureString -SecureString $secure" in script
    assert "-Key " not in script
    assert "ConvertTo-SecureString -String $cipherText" in script


def test_backup_restore_env_secrets_never_echoes_plaintext():
    script = _text()
    assert "Write-Host" in script
    for line in script.splitlines():
        stripped = line.strip()
        if stripped.startswith("Write-Host"):
            assert "$plainBytes" not in stripped
            assert "$plainBase64" not in stripped
            assert "$cipherText" not in stripped


def test_restore_env_secrets_refuses_to_silently_overwrite_existing_destination():
    script = _text()
    assert "already exists and is non-empty" in script
    assert "[switch]$Force" in script


def test_backup_restore_env_secrets_applies_owner_only_acl():
    script = _text()
    assert "function Set-PrivateFileAcl" in script
    assert "FileSystemRights]::FullControl" in script
    assert "Set-PrivateFileAcl -Path $BackupPath" in script
    assert "Set-PrivateFileAcl -Path $temp" in script


def test_restore_env_secrets_does_not_double_apply_acl_after_move():
    # Reproduced directly: applying Set-PrivateFileAcl a second time on
    # $DestinationPath after Move-Item (on top of the already-applied
    # $temp ACL that Move-Item, a same-volume rename, carries over
    # unchanged) throws PrivilegeNotHeldException: SeSecurityPrivilege on
    # a plain non-elevated account. Only the single pre-write application
    # on $temp is correct and safe.
    script = _text()
    restore_start = script.index("function Restore-EnvSecrets")
    restore_body = script[restore_start:]
    assert "Set-PrivateFileAcl -Path $DestinationPath" not in restore_body


def test_backup_restore_env_secrets_resolves_paths_against_current_location():
    # Codex P2 (PR #365 review comment 4369875882): .NET file APIs resolve
    # a relative path against the PROCESS working directory, which can
    # differ from PowerShell's own current location (Set-Location) --
    # silently reading/writing the wrong file. Every caller-supplied path
    # must be resolved to an absolute path (anchored at PowerShell's own
    # current location) before any .NET file call.
    script = _text()
    assert "function Resolve-ToAbsolutePath" in script
    assert "$SourcePath = Resolve-ToAbsolutePath -Path $SourcePath" in script
    assert "$BackupPath = Resolve-ToAbsolutePath -Path $BackupPath" in script
    assert "$DestinationPath = Resolve-ToAbsolutePath -Path $DestinationPath" in script
    assert "(Get-Location).Path" in script


def test_restore_env_secrets_applies_acl_before_writing_plaintext():
    # Codex P2 (PR #365 review comment 4369875884): applying the
    # owner-only ACL only AFTER writing decrypted bytes (or only after
    # the move) leaves a window where the plaintext secret sits in a file
    # with inherited, potentially broader permissions. The temp file must
    # be created and ACL-restricted BEFORE any decrypted byte is written
    # into it.
    script = _text()
    restore_start = script.index("function Restore-EnvSecrets")
    restore_body = script[restore_start:]
    create_at = restore_body.index('New-Item -ItemType File -Path $temp -Force')
    acl_at = restore_body.index('Set-PrivateFileAcl -Path $temp')
    write_at = restore_body.index('[System.IO.File]::WriteAllBytes($temp, $plainBytes)')
    move_at = restore_body.index('Move-Item -LiteralPath $temp -Destination $DestinationPath -Force')
    assert create_at < acl_at < write_at < move_at


def test_set_private_file_acl_purges_existing_explicit_access_rules():
    # Codex P2 (PR #365 review comment 4369916153): SetAccessRuleProtection
    # only drops INHERITED rules; it leaves any explicit rule Get-Acl
    # already carried over from the file's existing ACL untouched, and
    # AddAccessRule only adds -- it never removes. If a predictable temp
    # file path was pre-created (leftover run, or a hostile local
    # principal) with its own explicit grant, that grant would otherwise
    # survive unchanged. Every existing rule must be purged before adding
    # the single owner-only rule.
    script = _text()
    acl_start = script.index("function Set-PrivateFileAcl")
    acl_body = script[acl_start:script.index("function Backup-EnvSecrets")]
    purge_at = acl_body.index("RemoveAccessRule($existingRule)")
    add_at = acl_body.index("$acl.AddAccessRule($rule)")
    assert purge_at < add_at
    assert "@($acl.Access)" in acl_body


def test_backup_restore_env_secrets_is_not_wired_into_any_scheduled_task():
    # This is a manually-invoked recovery tool, not a new standing
    # automation layer: it must not appear in either autopilot script's
    # Scheduled Task registration.
    for other in (
        Path("ibkr_paper_signal_runner_autopilot_windows.ps1"),
        Path("install_ibkr_paper_signal_runner_autopilot_windows.ps1"),
    ):
        assert "backup_restore_env_secrets_windows.ps1" not in other.read_text(encoding="utf-8")
