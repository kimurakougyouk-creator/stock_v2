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
# Independent-audit follow-up (PR #365 comment 6394617380): an earlier
# revision used a FIXED-NAME temp file ("$BackupPath.tmp" /
# "$DestinationPath.tmp") created with -Force, and did not check whether
# SourcePath/BackupPath (or BackupPath/DestinationPath) resolved to the
# same underlying file. That meant: (a) calling Backup-EnvSecrets with
# SourcePath equal to BackupPath could replace the original plaintext
# .env with its own ciphertext via Move-Item -Force; (b) an unrelated,
# important file that happened to already sit at the fixed temp path
# was silently truncated/replaced, even when the real destination did
# not exist or was empty; (c) a symlink/junction/hardlink alias was not
# checked at all. This revision fixes all three: every temp file is
# allocated with FileMode.CreateNew (fails instead of overwriting if
# anything already exists at that name) under a fresh random suffix, so
# it can never alias a pre-existing file; SourcePath/BackupPath and
# BackupPath/DestinationPath are rejected outright when they name the
# same file (by normalized path OR by on-disk file identity, which also
# catches a hardlink or a symlink/junction pointing at the same target);
# and every path this script touches (including parent directories) is
# rejected if it is itself a reparse point, so a planted junction cannot
# silently redirect a write elsewhere.
#
# This script is not wired into any Scheduled Task and does not run on
# its own. Invoke it manually: for a precedent-aligned ACL-restricted
# private backup file, see Set-PrivatePinFile in
# install_ibkr_paper_signal_runner_autopilot_windows.ps1, whose owner-
# only-FullControl pattern this script mirrors.

if (-not ("EnvSecretsWin32.NativeMethods" -as [type])) {
    Add-Type -Namespace EnvSecretsWin32 -Name NativeMethods -UsingNamespace Microsoft.Win32.SafeHandles -MemberDefinition @'
[System.Runtime.InteropServices.StructLayout(System.Runtime.InteropServices.LayoutKind.Sequential)]
public struct BY_HANDLE_FILE_INFORMATION
{
    public uint FileAttributes;
    public System.Runtime.InteropServices.ComTypes.FILETIME CreationTime;
    public System.Runtime.InteropServices.ComTypes.FILETIME LastAccessTime;
    public System.Runtime.InteropServices.ComTypes.FILETIME LastWriteTime;
    public uint VolumeSerialNumber;
    public uint FileSizeHigh;
    public uint FileSizeLow;
    public uint NumberOfLinks;
    public uint FileIndexHigh;
    public uint FileIndexLow;
}

[System.Runtime.InteropServices.DllImport("kernel32.dll", SetLastError = true)]
public static extern bool GetFileInformationByHandle(SafeFileHandle hFile, out BY_HANDLE_FILE_INFORMATION lpFileInformation);
'@
}

function Get-FileIdentityKey {
    # Returns a string identifying the actual on-disk file (volume serial
    # + file index), not just its path string. Two different path
    # strings that are hardlinked to the same file, or a symlink/
    # junction whose target is the other path, resolve to the SAME
    # identity key here -- [System.IO.File]::Open follows reparse points
    # through to their target by default, so this also catches a
    # symlink-based alias without any extra code. Returns $null if the
    # path does not exist or identity cannot be read (fails closed: the
    # caller must not treat $null as "safe, definitely different").
    param([Parameter(Mandatory = $true)][string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    $fs = $null
    try {
        $fs = [System.IO.File]::Open($Path, [System.IO.FileMode]::Open, [System.IO.FileAccess]::Read, [System.IO.FileShare]::ReadWrite)
        $info = New-Object EnvSecretsWin32.NativeMethods+BY_HANDLE_FILE_INFORMATION
        $ok = [EnvSecretsWin32.NativeMethods]::GetFileInformationByHandle($fs.SafeFileHandle, [ref] $info)
        if (-not $ok) { return $null }
        return "{0}-{1}-{2}" -f $info.VolumeSerialNumber, $info.FileIndexHigh, $info.FileIndexLow
    } catch {
        return $null
    } finally {
        if ($fs) { $fs.Close() }
    }
}

function Test-SamePath {
    # True if PathA and PathB name the same underlying file: either the
    # same normalized path string, or (when both exist) the same on-disk
    # file identity, which also covers a hardlink or symlink/junction
    # alias between two different-looking paths.
    param(
        [Parameter(Mandatory = $true)][string]$PathA,
        [Parameter(Mandatory = $true)][string]$PathB
    )
    if ([string]::Equals($PathA, $PathB, [System.StringComparison]::OrdinalIgnoreCase)) {
        return $true
    }
    $idA = Get-FileIdentityKey -Path $PathA
    $idB = Get-FileIdentityKey -Path $PathB
    if ($null -ne $idA -and $null -ne $idB -and $idA -eq $idB) {
        return $true
    }
    return $false
}

function Assert-NotReparsePoint {
    # Refuses to operate through a path, OR ANY OF ITS EXISTING ANCESTOR
    # DIRECTORIES up to the filesystem root, that is a symlink/junction.
    # Codex (PR #365 comment 4370003131): checking only the leaf and its
    # immediate parent misses a junction higher up the chain -- e.g.
    # C:\alias is a junction and the real path is C:\alias\sub\file --
    # the leaf's own attributes never reveal that ancestor junction, so
    # a later Move-Item/Get-Content would still silently follow it to
    # wherever the junction points. This walks every existing level from
    # $Path itself up to the root, skipping any level that does not
    # exist yet (a destination not yet created is not a reparse point),
    # and still continues past it to check what, if anything, exists
    # further up.
    param([Parameter(Mandatory = $true)][string]$Path)
    $current = $Path
    while ($current) {
        if (Test-Path -LiteralPath $current) {
            $item = Get-Item -LiteralPath $current -Force
            if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                throw "BLOCKED: refusing to operate through a reparse point (symlink/junction): $current"
            }
        }
        $next = Split-Path -Parent $current
        if (-not $next -or $next -eq $current) { break }
        $current = $next
    }
}

function New-ExclusiveTempFilePath {
    # Allocates a brand-new, randomly-named file in $Directory using
    # FileMode.CreateNew, which throws instead of succeeding if anything
    # already exists at that path. This is the opposite of the earlier
    # fixed-name "$X.tmp" + -Force pattern: the returned path is
    # guaranteed, by construction, to have been empty and nonexistent
    # the instant before this call created it, so nothing pre-existing
    # can ever be silently overwritten through it.
    param([Parameter(Mandatory = $true)][string]$Directory)
    for ($attempt = 0; $attempt -lt 25; $attempt++) {
        $candidate = Join-Path $Directory (".envsecrets-" + [System.IO.Path]::GetRandomFileName())
        try {
            $fs = [System.IO.File]::Open($candidate, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
            $fs.Close()
            return $candidate
        } catch [System.IO.IOException] {
            continue
        }
    }
    throw "BLOCKED: could not allocate a unique temporary file in $Directory"
}

function Resolve-ToAbsolutePath {
    # [System.IO.File]/[System.IO.Path] .NET APIs resolve a relative path
    # against the process's current directory, which can silently differ
    # from PowerShell's own current location (Set-Location) depending on
    # host/invocation. Resolving explicitly against (Get-Location).Path
    # before any .NET file call removes that ambiguity for every path
    # this script touches.
    param([Parameter(Mandatory = $true)][string]$Path)
    if ([System.IO.Path]::IsPathRooted($Path)) {
        return [System.IO.Path]::GetFullPath($Path)
    }
    return [System.IO.Path]::GetFullPath((Join-Path (Get-Location).Path $Path))
}

function Get-ParentDirectoryPath {
    param([Parameter(Mandatory = $true)][string]$AbsolutePath)
    $parent = Split-Path -Parent $AbsolutePath
    if (-not $parent) {
        $parent = [System.IO.Path]::GetPathRoot($AbsolutePath)
    }
    return $parent
}

function Set-PrivateFileAcl {
    # Build the ACL object from Get-Acl (the file's own existing security
    # descriptor) rather than a blank `New-Object FileSecurity`. A blank
    # object does not know which ACL sections (owner/access/audit) are
    # already present, and .NET can then attempt to also write the audit
    # (SACL) section on Set-Acl, which throws
    # PrivilegeNotHeldException: SeSecurityPrivilege for a normal,
    # non-elevated account -- reproduced directly against a file created
    # moments earlier by New-Item in this same script. Starting from
    # Get-Acl avoids touching the audit section at all.
    param([Parameter(Mandatory = $true)][string]$Path)
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = Get-Acl -LiteralPath $Path
    $acl.SetAccessRuleProtection($true, $false)
    # SetAccessRuleProtection only drops INHERITED rules; it does nothing
    # to explicit rules Get-Acl already carried over from the file's
    # existing ACL. If a predictable temp-file path was pre-created (by a
    # leftover prior run, or a hostile local principal) with its own
    # explicit grant before this script touches it, that grant would
    # otherwise survive AddAccessRule unchanged. Purge every existing
    # explicit rule first so the only rule left is the one this function
    # adds below, regardless of what the file's ACL looked like before.
    foreach ($existingRule in @($acl.Access)) {
        $acl.RemoveAccessRule($existingRule) | Out-Null
    }
    $acl.SetOwner($identity)
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
    $SourcePath = Resolve-ToAbsolutePath -Path $SourcePath
    $BackupPath = Resolve-ToAbsolutePath -Path $BackupPath
    if (-not (Test-Path -LiteralPath $SourcePath -PathType Leaf)) {
        throw "BLOCKED: source file not found: $SourcePath"
    }
    Assert-NotReparsePoint -Path $SourcePath
    Assert-NotReparsePoint -Path $BackupPath
    if (Test-SamePath -PathA $SourcePath -PathB $BackupPath) {
        throw "BLOCKED: SourcePath and BackupPath must not be the same file: $SourcePath"
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
    $parent = Get-ParentDirectoryPath -AbsolutePath $BackupPath
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    Assert-NotReparsePoint -Path $parent
    $temp = New-ExclusiveTempFilePath -Directory $parent
    try {
        [System.IO.File]::WriteAllText(
            $temp,
            $cipherText,
            (New-Object System.Text.UTF8Encoding($false))
        )
        Move-Item -LiteralPath $temp -Destination $BackupPath -Force
    } finally {
        if (Test-Path -LiteralPath $temp) {
            Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        }
    }
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
    $BackupPath = Resolve-ToAbsolutePath -Path $BackupPath
    $DestinationPath = Resolve-ToAbsolutePath -Path $DestinationPath
    if (-not (Test-Path -LiteralPath $BackupPath -PathType Leaf)) {
        throw "BLOCKED: backup file not found: $BackupPath"
    }
    Assert-NotReparsePoint -Path $BackupPath
    Assert-NotReparsePoint -Path $DestinationPath
    if ((Test-Path -LiteralPath $DestinationPath -PathType Leaf) -and -not $Force) {
        $existing = Get-Item -LiteralPath $DestinationPath
        if ($existing.Length -gt 0) {
            throw "BLOCKED: $DestinationPath already exists and is non-empty. Pass -Force to overwrite."
        }
    }
    if (Test-SamePath -PathA $BackupPath -PathB $DestinationPath) {
        throw "BLOCKED: BackupPath and DestinationPath must not be the same file: $BackupPath"
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
    $parent = Get-ParentDirectoryPath -AbsolutePath $DestinationPath
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    Assert-NotReparsePoint -Path $parent
    # The temp file is allocated fresh by New-ExclusiveTempFilePath (see
    # its own comment) instead of a fixed "$DestinationPath.tmp" name, so
    # it can never alias an unrelated pre-existing file. Its ACL is
    # locked down to owner-only BEFORE any decrypted byte is written
    # into it, so there is no window where the plaintext secret sits in
    # a file with inherited (possibly broader) permissions. Move-Item
    # within the same volume is a rename, which never changes a file's
    # security descriptor, so the ACL already set on $temp carries over
    # to $DestinationPath unchanged -- applying Set-PrivateFileAcl a
    # second time on the same underlying file after the move is not just
    # redundant, it was reproduced to throw
    # PrivilegeNotHeldException: SeSecurityPrivilege on a plain
    # (non-elevated) account when re-protecting an already-protected ACL.
    $temp = New-ExclusiveTempFilePath -Directory $parent
    try {
        Set-PrivateFileAcl -Path $temp
        [System.IO.File]::WriteAllBytes($temp, $plainBytes)
        Move-Item -LiteralPath $temp -Destination $DestinationPath -Force
    } finally {
        if (Test-Path -LiteralPath $temp) {
            Remove-Item -LiteralPath $temp -Force -ErrorAction SilentlyContinue
        }
    }
    Write-Host "Restored to: $DestinationPath (content not displayed)"
}

if ($MyInvocation.InvocationName -ne '.' -and $MyInvocation.Line -notmatch '^\s*\.\s') {
    Write-Host "This script defines Backup-EnvSecrets / Restore-EnvSecrets."
    Write-Host "Dot-source it, e.g.:"
    Write-Host '  . .\backup_restore_env_secrets_windows.ps1'
    Write-Host '  Backup-EnvSecrets -SourcePath .env -BackupPath "$HOME\.config\ai-asset-platform\env.backup"'
    Write-Host '  Restore-EnvSecrets -BackupPath "$HOME\.config\ai-asset-platform\env.backup" -DestinationPath .env'
}
