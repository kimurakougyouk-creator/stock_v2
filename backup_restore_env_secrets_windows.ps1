#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Recurrence-prevention follow-up to the 2026-10-25 .env loss incident
# (PR #364 / PR #365): the repository had no backup for .env at all, so
# when it was deleted there was nothing to restore from except the
# user's own memory of its contents. This script never stores or prints
# any secret value in the clear: it encrypts .env with the Windows Data
# Protection API (DPAPI, via ConvertTo-SecureString/ConvertFrom-
# SecureString with no -Key), which binds the ciphertext to the current
# Windows user account and machine -- no new key management, no network
# call, no paid service, and nothing an attacker could use the backup
# file alone to decrypt on a different machine or account. Restoring
# writes to an explicit, caller-chosen destination path; it never
# silently overwrites the live .env.
#
# This script is not wired into any Scheduled Task and does not run on
# its own. Invoke it manually: for a precedent-aligned ACL-restricted
# private backup file, see Set-PrivatePinFile in
# install_ibkr_paper_signal_runner_autopilot_windows.ps1, whose owner-
# only-FullControl pattern this script mirrors.

function Set-PrivateFileAcl {
    param([Parameter(Mandatory = $true)][string]$Path)
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = New-Object System.Security.AccessControl.FileSecurity
    $acl.SetOwner($identity)
    $acl.SetAccessRuleProtection($true, $false)
    $rule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $identity,
        [System.Security.AccessControl.FileSystemRights]::FullControl,
        [System.Security.AccessControl.AccessControlType]::Allow
    )
    $acl.AddAccessRule($rule)
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Backup-EnvSecrets {
    <#
      Encrypts $SourcePath (default: .env) with DPAPI, bound to the
      current Windows user + machine, and writes the ciphertext to
      $BackupPath. Never writes or logs the plaintext anywhere except
      reading $SourcePath itself into memory.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$SourcePath,
        [Parameter(Mandatory = $true)][string]$BackupPath
    )
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        throw "BLOCKED: source file not found: $SourcePath"
    }
    $plainBytes = [System.IO.File]::ReadAllBytes($SourcePath)
    try {
        $plainBase64 = [Convert]::ToBase64String($plainBytes)
        $secure = ConvertTo-SecureString -String $plainBase64 -AsPlainText -Force
        $cipherText = ConvertFrom-SecureString -SecureString $secure
    } finally {
        # Best-effort: overwrite the in-memory base64 string reference;
        # PowerShell strings are immutable, so this only drops the
        # reference for GC, it does not scrub process memory. Acceptable
        # here because this script never persists plaintext to disk.
        $plainBase64 = $null
    }
    $parent = Split-Path -Parent $BackupPath
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $temp = "$BackupPath.tmp"
    [System.IO.File]::WriteAllText(
        $temp,
        $cipherText,
        (New-Object System.Text.UTF8Encoding($false))
    )
    Move-Item -LiteralPath $temp -Destination $BackupPath -Force
    Set-PrivateFileAcl -Path $BackupPath
    Write-Host "Backed up (DPAPI-encrypted, current user+machine only): $BackupPath"
}

function Restore-EnvSecrets {
    <#
      Decrypts $BackupPath and writes the recovered plaintext to
      $DestinationPath. Never prints the decrypted content. Refuses to
      overwrite an existing, non-empty $DestinationPath unless -Force is
      passed, so this can never silently clobber a live .env.
    #>
    param(
        [Parameter(Mandatory = $true)][string]$BackupPath,
        [Parameter(Mandatory = $true)][string]$DestinationPath,
        [switch]$Force
    )
    if (-not (Test-Path -LiteralPath $BackupPath -PathType Leaf)) {
        throw "BLOCKED: backup file not found: $BackupPath"
    }
    if ((Test-Path -LiteralPath $DestinationPath -PathType Leaf) -and -not $Force) {
        $existing = Get-Item -LiteralPath $DestinationPath
        if ($existing.Length -gt 0) {
            throw "BLOCKED: $DestinationPath already exists and is non-empty. Pass -Force to overwrite."
        }
    }
    $cipherText = Get-Content -LiteralPath $BackupPath -Raw
    $secure = ConvertTo-SecureString -String $cipherText
    $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
    try {
        $plainBase64 = [System.Runtime.InteropServices.Marshal]::PtrToStringUni($bstr)
    } finally {
        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
    }
    $plainBytes = [Convert]::FromBase64String($plainBase64)
    $plainBase64 = $null
    $parent = Split-Path -Parent $DestinationPath
    if ($parent) {
        New-Item -ItemType Directory -Path $parent -Force | Out-Null
    }
    $temp = "$DestinationPath.tmp"
    [System.IO.File]::WriteAllBytes($temp, $plainBytes)
    Move-Item -LiteralPath $temp -Destination $DestinationPath -Force
    Set-PrivateFileAcl -Path $DestinationPath
    Write-Host "Restored to: $DestinationPath (content not displayed)"
}

if ($MyInvocation.InvocationName -ne '.' -and $MyInvocation.Line -notmatch '^\s*\.\s') {
    Write-Host "This script defines Backup-EnvSecrets / Restore-EnvSecrets."
    Write-Host "Dot-source it, e.g.:"
    Write-Host '  . .\backup_restore_env_secrets_windows.ps1'
    Write-Host '  Backup-EnvSecrets -SourcePath .env -BackupPath "$HOME\.config\ai-asset-platform\env.backup"'
    Write-Host '  Restore-EnvSecrets -BackupPath "$HOME\.config\ai-asset-platform\env.backup" -DestinationPath .env'
}
