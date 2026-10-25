from pathlib import Path


SCRIPT = Path("backup_restore_env_secrets_windows.ps1")


def _text() -> str:
    assert SCRIPT.exists(), f"missing required file: {SCRIPT}"
    return SCRIPT.read_text(encoding="utf-8")


def test_backup_rejects_overwriting_an_unrelated_existing_file_without_force():
    # Work independent audit, PR #365 comment 6395349716 (P2): an
    # earlier revision let Backup-EnvSecrets silently replace ANY
    # pre-existing file at BackupPath via Move-Item -Force -- no check
    # at all on what that file actually was. A mis-specified BackupPath
    # could destroy an unrelated important file. Backup-EnvSecrets must
    # now validate that an existing BackupPath is itself a previous
    # backup this tool produced (via Test-IsOwnPriorBackup) before
    # refreshing it without -Force; anything else requires -Force.
    script = _text()
    assert "function Test-IsOwnPriorBackup" in script
    backup_start = script.index("function Backup-EnvSecrets")
    backup_body = script[backup_start:script.index("function Restore-EnvSecrets")]
    assert "[switch]$Force" in backup_body
    assert "Test-IsOwnPriorBackup -Path $BackupPath" in backup_body
    assert "does not look like a previous backup" in backup_body


def test_backup_revalidates_immediately_before_the_move_to_close_toctou_window():
    # Work independent audit, PR #365 comment 6395349716 follow-up: the
    # up-front Test-IsOwnPriorBackup check (at function entry, before
    # SourcePath is even read) left a window -- everything from reading
    # SourcePath through encrypting and writing the temp file -- during
    # which a competing process could replace BackupPath with something
    # else. The default (non -Force) path must re-validate immediately
    # before the final move, and only pass -Force on that move when
    # BackupPath still exists and still validates; otherwise the move
    # itself must go through unforced, so a file that appeared in the
    # last instant is rejected natively instead of silently replaced.
    script = _text()
    backup_start = script.index("function Backup-EnvSecrets")
    backup_body = script[backup_start:script.index("function Restore-EnvSecrets")]
    assert "if ($Force) {" in backup_body
    assert backup_body.count("Test-IsOwnPriorBackup -Path $BackupPath") == 2
    move_lines = [
        line.strip() for line in backup_body.splitlines()
        if "Move-Item -LiteralPath $temp -Destination $BackupPath" in line
    ]
    assert "Move-Item -LiteralPath $temp -Destination $BackupPath -Force" in move_lines
    assert "Move-Item -LiteralPath $temp -Destination $BackupPath" in move_lines


def test_is_own_prior_backup_never_logs_or_returns_the_decrypted_value():
    script = _text()
    fn_start = script.index("function Test-IsOwnPriorBackup")
    fn_body = script[fn_start:script.index("function Backup-EnvSecrets")]
    assert "ConvertTo-SecureString -String $existingCipherText" in fn_body
    for line in fn_body.splitlines():
        stripped = line.strip()
        if stripped.startswith("Write-Host") or stripped.startswith("return "):
            assert "PtrToStringUni" not in stripped
            assert "bstr" not in stripped.lower() or "void" in stripped.lower()


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
    # Codex-connector follow-up suggestion (comment 6395064684), adopted
    # after independent review: protects even a zero-byte pre-existing
    # destination, not just a non-empty one -- an operator's own
    # placeholder file deserves the same protection.
    script = _text()
    restore_start = script.index("function Restore-EnvSecrets")
    restore_body = script[restore_start:]
    assert "already exists" in restore_body
    assert ".Length -gt 0" not in restore_body
    assert "[switch]$Force" in script


def test_backup_restore_env_secrets_applies_owner_only_acl():
    script = _text()
    assert "function Set-PrivateFileAcl" in script
    assert "FileSystemRights]::FullControl" in script
    backup_body = script[script.index("function Backup-EnvSecrets"):script.index("function Restore-EnvSecrets")]
    restore_body = script[script.index("function Restore-EnvSecrets"):]
    assert "Set-PrivateFileAcl -Path $temp" in backup_body
    assert "Set-PrivateFileAcl -Path $temp" in restore_body


def test_backup_env_secrets_applies_acl_before_writing_ciphertext():
    # Codex-connector follow-up suggestion (comment 6395064684), adopted
    # after independent review: Backup-EnvSecrets' temp file should be
    # ACL-locked before the DPAPI ciphertext is written into it, the
    # same ordering already used by Restore-EnvSecrets for the
    # plaintext secret.
    script = _text()
    backup_start = script.index("function Backup-EnvSecrets")
    backup_body = script[backup_start:script.index("function Restore-EnvSecrets")]
    create_at = backup_body.index('$temp = New-ExclusiveTempFilePath -Directory $parent')
    acl_at = backup_body.index('Set-PrivateFileAcl -Path $temp')
    write_at = backup_body.index('[System.IO.File]::WriteAllText(')
    move_at = backup_body.index('if ($Force) {')
    assert create_at < acl_at < write_at < move_at
    # Backup-EnvSecrets' move is allowed to replace an existing
    # BackupPath (taking a fresh backup is expected to refresh whatever
    # backup already sits there, unlike Restore-EnvSecrets' destination
    # which may be a live .env) -- but only after re-validating it is
    # still one of this tool's own prior backups immediately beforehand
    # (see test_backup_revalidates_immediately_before_the_move_to_close_toctou_window).


def test_restore_env_secrets_default_move_is_not_forced_toctou_guard():
    # Codex-connector follow-up suggestion (comment 6395064684), adopted
    # after independent review: the up-front existing-destination check
    # only catches a collision that already existed at check time. A
    # competing process could still create DestinationPath between that
    # check and the final move. The default (non -Force) path must omit
    # -Force on the final Move-Item too, so PowerShell itself refuses to
    # overwrite a file that appeared in that window, instead of the
    # script silently winning the race.
    script = _text()
    restore_start = script.index("function Restore-EnvSecrets")
    restore_body = script[restore_start:]
    assert "if ($Force) {" in restore_body
    move_lines = [
        line.strip() for line in restore_body.splitlines()
        if "Move-Item -LiteralPath $temp -Destination $DestinationPath" in line
    ]
    assert "Move-Item -LiteralPath $temp -Destination $DestinationPath -Force" in move_lines
    assert "Move-Item -LiteralPath $temp -Destination $DestinationPath" in move_lines


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
    create_at = restore_body.index('$temp = New-ExclusiveTempFilePath -Directory $parent')
    acl_at = restore_body.index('Set-PrivateFileAcl -Path $temp')
    write_at = restore_body.index('[System.IO.File]::WriteAllBytes($temp, $plainBytes)')
    move_at = restore_body.index('Move-Item -LiteralPath $temp -Destination $DestinationPath -Force')
    assert create_at < acl_at < write_at < move_at


def test_temp_files_are_allocated_exclusively_not_at_a_fixed_name():
    # Work independent-audit finding (PR #365 comment 6394617380, P1): an
    # earlier revision used a FIXED-NAME temp file ("$BackupPath.tmp" /
    # "$DestinationPath.tmp") created with -Force, so an unrelated,
    # important pre-existing file at that exact path would be silently
    # truncated/replaced -- even when the real destination did not exist
    # or was empty. Every temp file must now come from
    # New-ExclusiveTempFilePath, which uses FileMode.CreateNew (fails
    # instead of overwriting anything that already exists) under a fresh
    # random name, and the old fixed-name pattern must not reappear.
    script = _text()
    assert "function New-ExclusiveTempFilePath" in script
    assert "[System.IO.FileMode]::CreateNew" in script
    code_lines = [
        line for line in script.splitlines()
        if not line.strip().startswith("#")
    ]
    code_only = "\n".join(code_lines)
    assert '"$BackupPath.tmp"' not in code_only
    assert '"$DestinationPath.tmp"' not in code_only
    assert 'New-Item -ItemType File -Path $temp -Force' not in code_only
    backup_start = script.index("function Backup-EnvSecrets")
    backup_body = script[backup_start:script.index("function Restore-EnvSecrets")]
    assert "$temp = New-ExclusiveTempFilePath -Directory $parent" in backup_body
    restore_start = script.index("function Restore-EnvSecrets")
    restore_body = script[restore_start:]
    assert "$temp = New-ExclusiveTempFilePath -Directory $parent" in restore_body


def test_backup_rejects_source_and_backup_path_collision():
    # Work independent-audit finding (P1): without this check,
    # Backup-EnvSecrets -SourcePath X -BackupPath X would read X, then
    # Move-Item -Force the resulting ciphertext onto X itself, replacing
    # the original plaintext .env with its own encrypted backup.
    script = _text()
    backup_start = script.index("function Backup-EnvSecrets")
    backup_body = script[backup_start:script.index("function Restore-EnvSecrets")]
    assert "Test-SamePath -PathA $SourcePath -PathB $BackupPath" in backup_body
    assert "SourcePath and BackupPath must not be the same file" in backup_body


def test_restore_rejects_backup_and_destination_path_collision():
    script = _text()
    restore_start = script.index("function Restore-EnvSecrets")
    restore_body = script[restore_start:]
    assert "Test-SamePath -PathA $BackupPath -PathB $DestinationPath" in restore_body
    assert "BackupPath and DestinationPath must not be the same file" in restore_body


def test_assert_not_reparse_point_walks_the_full_ancestor_chain():
    # Codex (PR #365 comment 4370003131): checking only the leaf and its
    # immediate parent directory misses a junction higher up the chain
    # (e.g. C:\alias is a junction and the real path is
    # C:\alias\sub\file -- the leaf's own attributes never reveal that
    # ancestor junction). The walk must continue past non-existent
    # levels up to the filesystem root, not stop at the first missing
    # or first-checked level.
    script = _text()
    acl_start = script.index("function Assert-NotReparsePoint")
    body = script[acl_start:script.index("function New-ExclusiveTempFilePath")]
    assert "while ($current)" in body
    assert "Split-Path -Parent $current" in body
    # Must not return/stop immediately just because the leaf itself does
    # not exist yet -- it has to keep walking upward regardless.
    assert "if (-not (Test-Path -LiteralPath $Path)) { return }" not in body


def test_same_path_detection_also_covers_hardlink_and_reparse_point_aliases():
    # Work independent-audit finding (P1): a path-string comparison alone
    # misses a hardlink, or a symlink/junction, that makes two different-
    # looking paths refer to the same underlying file.
    # GetFileInformationByHandle's (VolumeSerialNumber, FileIndex) pair
    # identifies the actual file regardless of which path or link was
    # used to open it, and Assert-NotReparsePoint additionally refuses to
    # operate on any path (or parent directory) that is itself a
    # symlink/junction.
    script = _text()
    assert "function Get-FileIdentityKey" in script
    assert "GetFileInformationByHandle" in script
    assert "function Assert-NotReparsePoint" in script
    assert "ReparsePoint" in script
    for fn in ("Backup-EnvSecrets", "Restore-EnvSecrets"):
        start = script.index(f"function {fn}")
        end_markers = [m for m in ("function Backup-EnvSecrets", "function Restore-EnvSecrets", "if ($MyInvocation") if m != f"function {fn}"]
        end = min(script.index(m, start + 1) for m in end_markers if script.find(m, start + 1) != -1)
        body = script[start:end]
        assert "Assert-NotReparsePoint" in body


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
