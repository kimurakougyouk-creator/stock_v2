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
# group/world-writable -- i.e. a system interpreter that the account
# running this script cannot itself overwrite.
#
# Windows venvs do not use a symlink here (.venv\Scripts\python.exe is a
# real file), and a common per-user Python install (under
# %LOCALAPPDATA%\Programs\Python) is fully writable by that same account,
# so a filesystem-ownership check would not provide the same assurance it
# does on POSIX. Verified empirically on this machine: the per-user
# python.exe grants the operator account Full Control. Filesystem
# ownership is therefore not a usable trust boundary here.
#
# Windows equivalent used instead: resolve the pinned Python version
# through the official `py` launcher (itself a well-known, independently
# installed system component, not something inside this repository or
# venv), then require a valid Authenticode signature on that resolved
# executable from the Python Software Foundation. This is a stronger
# property than the POSIX ownership check in one respect (it verifies the
# exact published binary, not merely "whoever currently owns this file"),
# and it does not depend on whether this particular machine's Python
# install happens to be per-user or per-machine.
$PinnedPythonVersion = "3.13"
try {
    $TrustedPythonReal = & py "-$PinnedPythonVersion" -c "import sys; print(sys.executable)" 2>$null
} catch {
    $TrustedPythonReal = $null
}
if (-not $TrustedPythonReal -or -not (Test-Path -LiteralPath $TrustedPythonReal -PathType Leaf)) {
    Block "trusted Python $PinnedPythonVersion could not be resolved via the py launcher."
}
$TrustedPythonReal = (Resolve-Path -LiteralPath $TrustedPythonReal).Path
$VenvRootFull = (Resolve-Path -LiteralPath (Join-Path $Root ".venv")).Path
if ($TrustedPythonReal.StartsWith($VenvRootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
    Block "resolved trusted Python must not be inside this repository's .venv."
}
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
$ActualSha = (& git rev-parse HEAD).Trim()
if ($ActualSha -ne $env:LIVE_PILOT_EXPECTED_COMMIT_SHA) {
    Block "checkout SHA does not match the explicitly approved SHA."
}

# --- Working-tree cleanliness (fail closed before any Python launch) -------
$AuditedPaths = @(
    "src", "tests", "scripts", "requirements.txt", "pyproject.toml",
    "pytest.ini", ".github/workflows/pytest.yml",
    "live_pilot_operational_once.sh", "live_pilot_operational_once.ps1"
)
$SourceDirty = & git status --porcelain=v1 --untracked-files=all -- $AuditedPaths
if ($SourceDirty) {
    Block "tracked or untracked audited source changes are present before Python launch."
}

# --- Hidden index state (assume-unchanged / skip-worktree) ------------------
$IndexHidden = & git ls-files -v -- $AuditedPaths | Where-Object {
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
$IgnoredImportable = & git ls-files --others --ignored --exclude-standard -- src tests scripts
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
# Point PYTHONTZPATH directly at the already-pinned (requirements.txt)
# tzdata package's raw zoneinfo/ directory -- the same TZif file format
# POSIX's /usr/share/zoneinfo uses -- after verifying its exact file
# hashes, so no unverified site-packages import is ever trusted.
$TzdataManifest = Join-Path $Root "scripts\live_tzdata_manifest.json"
$TzdataVerifier = Join-Path $Root "scripts\verify_live_tzdata_runtime.py"
$TzdataZoneinfoDir = Join-Path $VenvSitePackages "tzdata\zoneinfo"
& $TrustedPythonReal -I -P -S $TzdataVerifier --zoneinfo-dir $TzdataZoneinfoDir --manifest $TzdataManifest
if ($LASTEXITCODE -ne 0) {
    Block "venv tzdata dependency does not match the pinned runtime manifest."
}
$env:PYTHONTZPATH = $TzdataZoneinfoDir

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
