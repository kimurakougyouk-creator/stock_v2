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
    assert "Set-PrivateFileAcl -Path $DestinationPath" in script


def test_backup_restore_env_secrets_is_not_wired_into_any_scheduled_task():
    # This is a manually-invoked recovery tool, not a new standing
    # automation layer: it must not appear in either autopilot script's
    # Scheduled Task registration.
    for other in (
        Path("ibkr_paper_signal_runner_autopilot_windows.ps1"),
        Path("install_ibkr_paper_signal_runner_autopilot_windows.ps1"),
    ):
        assert "backup_restore_env_secrets_windows.ps1" not in other.read_text(encoding="utf-8")
