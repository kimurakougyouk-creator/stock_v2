#Requires -Version 5.1
<#
Human-facing single Windows entrypoint for Issue #255, mirroring
live_pilot_operational_once.sh. Every check in the POSIX script has a
direct counterpart here, using the equivalent Windows primitive -- not a
weaker substitute. See the comment above each check for the specific
POSIX behavior it replaces and why.

This wrapper never creates an authorization and never supplies the final
consequential confirmation by default. Those values must already exist in
the environment from the separately approved operator step.

Re-running this same entrypoint after the irreversible campaign marker
exists is recovery-only: the Python coordinator makes the sender
unreachable and performs read-only reconciliation only.
#>

$ErrorActionPreference = "Stop"

function Block([string]$Message) {
    Write-Host "BLOCKED: $Message No Live order was sent."
    exit 2
}

$Root = $env:AI_ASSET_PLATFORM_ROOT
if (-not $Root) { $Root = (Get-Location).Path }
Set-Location -LiteralPath $Root

# --- Trusted interpreter resolution and attestation -----------------------
#
# The POSIX script resolves .venv/bin/python's symlink target and requires
# that target to be /usr/bin/python3*, owned by root (uid 0) and not
# group/world-writable -- i.e. a system interpreter, and everything it
# loads (shared libraries, stdlib), that the account running this script
# cannot itself overwrite.
#
# An earlier revision of this check resolved Python by executing the `py`
# launcher and trusted only an Authenticode signature on the resulting
# python.exe. Codex's review of that revision correctly identified two
# gaps, both closed below:
#   1. Executing `py` (PATH/session-resolved, no -I/-P/-S) before any
#      attestation means an attacker-controlled PATH or shadowing
#      alias/function could run arbitrary code first and merely print a
#      genuine interpreter's path afterward to pass the remaining checks.
#   2. An Authenticode signature on python.exe authenticates only that one
#      file. The interpreter also loads python313.dll and the standard
#      library from the same install directory; on a per-user install
#      (verified empirically on this machine: %LOCALAPPDATA%\Programs\Python
#      grants the operator account Full Control), that same account can
#      replace either without invalidating python.exe's own signature.
#      This is not equivalent to POSIX's root-owned/non-writable runtime.
#
# Fix: resolve the interpreter from the Windows Registry's all-users
# PythonCore registration (HKLM only -- a per-user HKCU registration is
# deliberately never consulted, since it corresponds to exactly the
# writable-by-the-operator install this check exists to reject) without
# executing anything. Windows' own default ACLs make
# %ProgramFiles%/%ProgramFiles(x86)% -- where an all-users Python install
# always lives -- non-writable by a standard user account, so requiring
# the resolved install directory to be under one of those roots closes
# gap 2 for the whole install directory (DLLs and stdlib included), not
# only python.exe. Gap 1 is closed because registry lookup and the
# filesystem checks below execute no code at all; Get-AuthenticodeSignature
# is kept as an additional, non-primary defense-in-depth check.
$PinnedPythonVersion = "3.13"
$PythonCoreRegistryPaths = @(
    "HKLM:\SOFTWARE\Python\PythonCore\$PinnedPythonVersion\InstallPath",
    "HKLM:\SOFTWARE\WOW6432Node\Python\PythonCore\$PinnedPythonVersion\InstallPath"
)
$InstallPath = $null
foreach ($regPath in $PythonCoreRegistryPaths) {
    if (Test-Path -LiteralPath $regPath) {
        $value = (Get-Item -LiteralPath $regPath).GetValue("")
        if ($value) { $InstallPath = $value; break }
    }
}
if (-not $InstallPath) {
    Block "no all-users (HKLM) Python $PinnedPythonVersion registration found. Install Python $PinnedPythonVersion for all users (admin-only-writable), not a per-user install, before this entrypoint can run."
}
$TrustedPythonReal = Join-Path $InstallPath "python.exe"
if (-not (Test-Path -LiteralPath $TrustedPythonReal -PathType Leaf)) {
    Block "python.exe not found at the registered all-users install path: $TrustedPythonReal"
}
$InstallPathItem = Get-Item -LiteralPath $InstallPath -ErrorAction SilentlyContinue
if (-not $InstallPathItem -or ($InstallPathItem.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
    Block "registered Python install path is missing or is a symlink/junction."
}
$TrustedPythonReal = (Resolve-Path -LiteralPath $TrustedPythonReal).Path
if ((Get-Item -LiteralPath $TrustedPythonReal).Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
    Block "resolved python.exe is a symlink/junction."
}
# Codex P1 (exact HEAD 3825f0b): $env:ProgramFiles is an environment
# variable, not an OS-owned fact -- a hostile inherited environment could
# redefine it to point at any user-writable directory and this check
# would then trust whatever git.exe/python.exe lives there. Read the same
# value from its registry source of truth instead (HKLM, admin-only-
# writable, cannot be influenced by this process's environment).
$ProgramFilesRegistry = Get-ItemProperty -LiteralPath "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion" -ErrorAction SilentlyContinue
$AdminOnlyRoots = @($ProgramFilesRegistry.ProgramFilesDir, $ProgramFilesRegistry.'ProgramFilesDir (x86)') | Where-Object { $_ } | ForEach-Object { (Resolve-Path -LiteralPath $_).Path }
if ($AdminOnlyRoots.Count -eq 0) {
    Block "no Program Files root could be determined from the environment."
}
$UnderAdminOnlyRoot = $false
foreach ($candidateRoot in $AdminOnlyRoots) {
    # Deliberately not named $root: PowerShell variable names are
    # case-insensitive, so a loop variable named $root would silently
    # clobber $Root (this repository's root, used below for -C and the
    # Python bootstrap) once this loop runs -- caught only by actually
    # executing this script end-to-end, not by code review.
    if ($TrustedPythonReal.StartsWith(($candidateRoot.TrimEnd('\') + '\'), [System.StringComparison]::OrdinalIgnoreCase)) {
        $UnderAdminOnlyRoot = $true
        break
    }
}
if (-not $UnderAdminOnlyRoot) {
    Block "registered Python install is not under an admin-only-writable Program Files root: $TrustedPythonReal"
}
$VenvRootFull = (Resolve-Path -LiteralPath (Join-Path $Root ".venv")).Path
if ($TrustedPythonReal.StartsWith($VenvRootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    Block "resolved trusted Python must not be inside this repository's .venv."
}
# Defense-in-depth only (see rationale above): a valid PSF signature on
# python.exe specifically, in addition to -- never instead of -- the
# admin-only-root directory check above.
try {
    $Signature = Get-AuthenticodeSignature -LiteralPath $TrustedPythonReal
} catch {
    Block "resolved trusted Python's Authenticode signature could not be read."
}
if ($Signature.Status -ne [System.Management.Automation.SignatureStatus]::Valid) {
    Block "resolved trusted Python's Authenticode signature is not Valid (status: $($Signature.Status))."
}
$SignerSubject = $Signature.SignerCertificate.Subject
if ($SignerSubject -notmatch "O=Python Software Foundation") {
    Block "resolved trusted Python is not signed by the Python Software Foundation."
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
    Block ".venv\Scripts\python.exe must exist."
}

# --- Trusted Git resolution --------------------------------------------------
# A bare `git` command below would be resolved via PATH, which could be
# shadowed by an attacker-controlled executable earlier on PATH (the same
# concern as the interpreter resolution above). Resolve to one of Git for
# Windows' default install locations under an admin-only-writable Program
# Files root instead, mirroring live_pilot_source_cutover.py's
# _resolve_trusted_git_windows (kept in sync manually since this is a
# separate process from the Python it later launches).
$GitCandidateSuffixes = @("Git\cmd\git.exe", "Git\bin\git.exe", "Git\mingw64\bin\git.exe")
$TrustedGit = $null
foreach ($candidateRoot in $AdminOnlyRoots) {
    # Deliberately not named $root: see the identical note on the Python
    # admin-only-root check above -- it would silently clobber $Root.
    foreach ($suffix in $GitCandidateSuffixes) {
        $candidate = Join-Path $candidateRoot $suffix
        if (Test-Path -LiteralPath $candidate -PathType Leaf) {
            $item = Get-Item -LiteralPath $candidate
            if (-not ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
                $TrustedGit = (Resolve-Path -LiteralPath $candidate).Path
                break
            }
        }
    }
    if ($TrustedGit) { break }
}
if (-not $TrustedGit) {
    Block "no trusted admin-only-writable Git executable found under Program Files; install Git for Windows to its default location."
}
# Clear Git repository-discovery environment variables before any
# invocation below, so a hostile inherited GIT_DIR/GIT_WORK_TREE etc.
# cannot make these checks inspect a different repository than $Root.
foreach ($name in @(
    "GIT_DIR", "GIT_WORK_TREE", "GIT_COMMON_DIR", "GIT_CEILING_DIRECTORIES",
    "GIT_INDEX_FILE", "GIT_OBJECT_DIRECTORY", "GIT_ALTERNATE_OBJECT_DIRECTORIES"
)) {
    Remove-Item "Env:\$name" -ErrorAction SilentlyContinue
}
# Not wrapped in a PowerShell function: a user-defined function's @args
# binds an array argument (e.g. $AuditedPaths below) as one nested element
# rather than expanding it, unlike PowerShell's native-command argument
# binding used directly at each call site below, which does expand an
# array variable into separate arguments the same way the original bare
# `& git ... $AuditedPaths` calls relied on.
$GitSafeArgs = @("-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null", "-C", $Root)

# --- Required operator-supplied values -------------------------------------
# Same required-value contract as the POSIX script; same env var names, so
# a previously-prepared value set is portable across either entrypoint.
$RequiredVars = @(
    "LIVE_PILOT_INTENT_ID", "LIVE_PILOT_TICKER", "LIVE_PILOT_SIDE",
    "LIVE_PILOT_QUANTITY", "LIVE_PILOT_LIMIT_PRICE", "LIVE_PILOT_NOTIONAL_JPY",
    "LIVE_PILOT_NONCE", "LIVE_PILOT_ACCOUNT_FINGERPRINT",
    "LIVE_PILOT_EXPECTED_COMMIT_SHA"
)
foreach ($name in $RequiredVars) {
    $value = [System.Environment]::GetEnvironmentVariable($name)
    if (-not $value) {
        Block "$name is required."
    }
}

# --- Exact commit SHA pin ----------------------------------------------------
$ActualSha = (& $TrustedGit @GitSafeArgs rev-parse HEAD).Trim()
if ($ActualSha -ne $env:LIVE_PILOT_EXPECTED_COMMIT_SHA) {
    Block "checkout SHA does not match the explicitly approved SHA."
}

# --- Working-tree cleanliness (fail closed before any Python launch) -------
$AuditedPaths = @(
    "src", "tests", "scripts", "requirements.txt", "pyproject.toml",
    "pytest.ini", ".github/workflows/pytest.yml",
    "live_pilot_operational_once.sh", "live_pilot_operational_once.ps1"
)
$SourceDirty = & $TrustedGit @GitSafeArgs status --porcelain=v1 --untracked-files=all -- $AuditedPaths
if ($SourceDirty) {
    Block "tracked or untracked audited source changes are present before Python launch."
}

# --- Hidden index state (assume-unchanged / skip-worktree) ------------------
$IndexHidden = & $TrustedGit @GitSafeArgs ls-files -v -- $AuditedPaths | Where-Object {
    # -cmatch (case-sensitive): PowerShell's default -match is
    # case-insensitive, which would treat the normal "H" (tracked, no
    # special index state) flag as matching the lowercase a-z class below
    # and falsely block on every ordinary tracked file. git's own flags are
    # case-sensitive (uppercase = normal/stage states, lowercase = the
    # assume-unchanged variant of the same letter), exactly like the bash
    # version's `[[ $1 ~ /^[a-z]$/ ]]`.
    $_ -cmatch '^[Sa-z] '
}
if ($IndexHidden) {
    Block "audited source contains assume-unchanged or skip-worktree index entries."
}

# --- Ignored-but-importable artifacts under audited source paths -----------
# POSIX checks for a symlink, or a *.py/*.pyc/*.pyo/*.pyz/*.so/*.pyd/*.dylib
# file, or a directory with __init__.py/.pyc/*.so under it. The Windows
# native-extension suffix is .pyd (not .so); .dylib is macOS-only and kept
# here only for parity since it is harmless to also exclude.
$IgnoredImportable = & $TrustedGit @GitSafeArgs ls-files --others --ignored --exclude-standard -- src tests scripts
$IgnoredImportableHits = @()
foreach ($path in $IgnoredImportable) {
    if (-not $path) { continue }
    $full = Join-Path $Root $path
    $item = Get-Item -LiteralPath $full -ErrorAction SilentlyContinue
    if ($item -and ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        $IgnoredImportableHits += $path
        continue
    }
    if ($path -match '__pycache__/') { continue }
    if ($path -match '\.(py|pyc|pyo|pyz|so|pyd|dylib)$') {
        $IgnoredImportableHits += $path
        continue
    }
    if ($item -and $item.PSIsContainer) {
        $hasInit = (Test-Path -LiteralPath (Join-Path $full "__init__.py")) -or
                   (Test-Path -LiteralPath (Join-Path $full "__init__.pyc")) -or
                   (Get-ChildItem -LiteralPath $full -Filter "__init__*.pyd" -ErrorAction SilentlyContinue)
        if ($hasInit) { $IgnoredImportableHits += $path }
    }
}
if ($IgnoredImportableHits.Count -gt 0) {
    Block "ignored importable artifact, package, or symlink is present in an audited source path."
}

# --- ibapi dependency manifest verification ---------------------------------
Remove-Item Env:\PYTHONPATH -ErrorAction SilentlyContinue
Remove-Item Env:\PYTHONHOME -ErrorAction SilentlyContinue
$VenvSitePackages = Join-Path $Root ".venv\Lib\site-packages"
if (-not (Test-Path -LiteralPath $VenvSitePackages -PathType Container)) {
    Block "expected .venv\Lib\site-packages directory is missing."
}
$IbapiManifest = Join-Path $Root "scripts\live_ibapi_manifest.json"
$IbapiVerifier = Join-Path $Root "scripts\verify_live_ibapi_runtime.py"
$IbapiPackageDir = Join-Path $VenvSitePackages "ibapi"
& $TrustedPythonReal -I -P -S $IbapiVerifier --site-packages $VenvSitePackages --manifest $IbapiManifest
if ($LASTEXITCODE -ne 0) {
    Block "venv ibapi dependency does not match the pinned runtime manifest."
}

# --- tzdata dependency manifest verification --------------------------------
# Windows has no OS-provided IANA time zone database, unlike POSIX systems
# where zoneinfo falls back to /usr/share/zoneinfo; verified empirically
# on this machine (ModuleNotFoundError: tzdata under -S, since -S also
# hides this venv's tzdata pip package from the trusted interpreter).
# Point PYTHONTZPATH at a verified, immutable copy of the already-pinned
# (requirements.txt) tzdata package's raw zoneinfo/ directory -- the same
# TZif file format POSIX's /usr/share/zoneinfo uses.
#
# Reject any reparse point (symlink or NTFS junction) inside the source
# directory *before* verification: Python's Path.is_symlink(), used inside
# verify_live_tzdata_runtime.py, is not guaranteed to recognize an NTFS
# junction the same way it recognizes a symlink, so that check alone is not
# sufficient on Windows; the FileAttributes check below is.
$TzdataSourceDir = Join-Path $VenvSitePackages "tzdata\zoneinfo"
$TzdataReparsePoints = Get-ChildItem -LiteralPath $TzdataSourceDir -Recurse -Force -ErrorAction SilentlyContinue |
    Where-Object { $_.Attributes -band [System.IO.FileAttributes]::ReparsePoint }
if ($TzdataReparsePoints) {
    Block "venv tzdata zoneinfo directory contains a symlink or junction."
}

# Then copy to a fresh, process-local directory, mark every copied file
# read-only immediately (closes the window against accidental or
# normal-API writes; see the residual-risk note below), and verify *that*
# copy's hashes, so a TOCTOU write to the still-writable venv directory
# after this point cannot change the bytes PYTHONTZPATH actually serves.
#
# Residual risk (Codex P1, exact HEAD 3825f0b, acknowledged rather than
# hidden): a read-only file attribute does not withstand a fully capable
# concurrent process already running as this same OS user -- the owner of
# a file can always re-grant itself write access to its own object on
# Windows, the same way a Unix process running as the file's owner can
# chmod it back. No userspace trick closes that gap; it would require a
# genuine privilege boundary (a distinct, more restricted account than the
# interactive operator session) that this project does not currently have
# and that is out of scope for this Windows-compatibility PR. An attacker
# with that level of access already has far more direct options against
# this process (reading its memory, patching the TWS API DLL, etc.), so
# this mitigation targets the narrower, still-worthwhile threat of
# accidental or lower-privilege tampering, not a fully capable co-resident
# attacker.
$TzdataManifest = Join-Path $Root "scripts\live_tzdata_manifest.json"
$TzdataVerifier = Join-Path $Root "scripts\verify_live_tzdata_runtime.py"
$TzdataVerifiedCopy = Join-Path ([System.IO.Path]::GetTempPath()) ("live_pilot_tzdata_" + [System.Guid]::NewGuid().ToString("N"))
Copy-Item -LiteralPath $TzdataSourceDir -Destination $TzdataVerifiedCopy -Recurse -Force
Get-ChildItem -LiteralPath $TzdataVerifiedCopy -Recurse -File | ForEach-Object { $_.IsReadOnly = $true }
& $TrustedPythonReal -I -P -S $TzdataVerifier --zoneinfo-dir $TzdataVerifiedCopy --manifest $TzdataManifest
if ($LASTEXITCODE -ne 0) {
    Block "venv tzdata dependency does not match the pinned runtime manifest."
}
$env:PYTHONTZPATH = $TzdataVerifiedCopy

# --- Bootstrap into the operational entrypoint ------------------------------
$PythonBootstrap = @'
import runpy
import sys

repo_root = sys.argv[1]
ibapi_package_dir = sys.argv[2]
ibapi_manifest = sys.argv[3]
operational_args = sys.argv[4:]
sys.path.insert(0, repo_root + '/src')
from ai_asset_platform.execution.live_ibapi_runtime_guard import install_verified_ibapi_importer
install_verified_ibapi_importer(
    package_dir=ibapi_package_dir,
    manifest_path=ibapi_manifest,
)
sys.argv = ['ai_asset_platform.execution.live_pilot_operational_entrypoint', *operational_args]
runpy.run_module(
    'ai_asset_platform.execution.live_pilot_operational_entrypoint',
    run_name='__main__',
    alter_sys=True,
)
'@

$FinalConfirmation = $env:LIVE_PILOT_FINAL_CONFIRMATION
if (-not $FinalConfirmation) { $FinalConfirmation = "" }

# PowerShell drops an empty string entirely when passed as a separate
# argument to a native executable, which would silently shift every
# following argument by one position. Using --name=value form keeps the
# (possibly empty) value attached to its flag in a single token.
& $TrustedPythonReal -I -P -S -c $PythonBootstrap `
    $Root $IbapiPackageDir $IbapiManifest `
    "--intent-id=$($env:LIVE_PILOT_INTENT_ID)" `
    "--ticker=$($env:LIVE_PILOT_TICKER)" `
    "--side=$($env:LIVE_PILOT_SIDE)" `
    "--quantity=$($env:LIVE_PILOT_QUANTITY)" `
    "--limit-price=$($env:LIVE_PILOT_LIMIT_PRICE)" `
    "--estimated-notional-jpy=$($env:LIVE_PILOT_NOTIONAL_JPY)" `
    "--nonce=$($env:LIVE_PILOT_NONCE)" `
    "--account-fingerprint=$($env:LIVE_PILOT_ACCOUNT_FINGERPRINT)" `
    "--expected-commit-sha=$($env:LIVE_PILOT_EXPECTED_COMMIT_SHA)" `
    "--final-confirmation=$FinalConfirmation" `
    "--live-readonly-confirmation=READ_LIVE_ACCOUNT_ONLY" `
    "--repository-root=$Root"
exit $LASTEXITCODE
