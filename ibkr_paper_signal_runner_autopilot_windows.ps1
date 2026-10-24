#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Fail-closed, time-boxed, Paper-only natural-strategy signal runner for
# Windows. Mirrors ibkr_readonly_autopilot_windows.ps1's safety pattern
# (pinned/clean main HEAD, bounded log, fail-closed on any ambiguity) but
# runs the existing signal_runner module instead of the read-only monitor,
# so natural Paper fills can actually start accumulating (Issue #255 /
# COMPLETION_ROADMAP.md Phase 5 blocker: NO_NATURAL_STRATEGY_FILLS).
#
# This script can place IBKR Paper orders. It can NEVER place a Live order:
# execute_approved_signal_via_ibkr_paper() only ever connects to the IBKR
# Paper ports (4002/7497, ai_asset_platform.brokers.ibkr_config) and both
# SETTINGS.enable_live_trading and SETTINGS.live_trading_unlocked default
# False and are never set by this script. A defensive check below also
# refuses to run at all if either Live flag is already present in the
# ambient environment.

$RepoDir = if ($env:IBKR_REPO_DIR) {
    [System.IO.Path]::GetFullPath($env:IBKR_REPO_DIR)
} else {
    Join-Path $HOME "stock_v2_latest"
}
$IntervalSeconds = if ($env:IBKR_PAPER_SIGNAL_AUTOPILOT_INTERVAL_SECONDS) {
    [int]$env:IBKR_PAPER_SIGNAL_AUTOPILOT_INTERVAL_SECONDS
} else {
    900
}
$MaxLogBytes = if ($env:IBKR_PAPER_SIGNAL_AUTOPILOT_MAX_LOG_BYTES) {
    [long]$env:IBKR_PAPER_SIGNAL_AUTOPILOT_MAX_LOG_BYTES
} else {
    5242880
}
$MaxRuntimeHours = if ($env:IBKR_PAPER_SIGNAL_AUTOPILOT_MAX_RUNTIME_HOURS) {
    [double]$env:IBKR_PAPER_SIGNAL_AUTOPILOT_MAX_RUNTIME_HOURS
} else {
    336
}
$PinFile = if ($env:IBKR_PAPER_SIGNAL_AUTOPILOT_PIN_FILE) {
    [System.IO.Path]::GetFullPath($env:IBKR_PAPER_SIGNAL_AUTOPILOT_PIN_FILE)
} else {
    Join-Path $HOME ".config\ai-asset-platform\ibkr-paper-signal-runner-autopilot-pinned-head"
}
$LogDir = Join-Path $RepoDir "results"
$LogFile = Join-Path $LogDir "ibkr_paper_signal_runner_autopilot.log"
$RotatedLogFile = "$LogFile.1"
$PythonExe = Join-Path $RepoDir ".venv\Scripts\python.exe"

if ($IntervalSeconds -lt 30 -or $IntervalSeconds -gt 86400) {
    throw "BLOCKED: IBKR_PAPER_SIGNAL_AUTOPILOT_INTERVAL_SECONDS must be from 30 to 86400. No Paper or Live order was sent."
}
if ($MaxLogBytes -lt 1048576 -or $MaxLogBytes -gt 104857600) {
    throw "BLOCKED: IBKR_PAPER_SIGNAL_AUTOPILOT_MAX_LOG_BYTES must be from 1048576 to 104857600. No Paper or Live order was sent."
}
if ($MaxRuntimeHours -lt 1 -or $MaxRuntimeHours -gt 8760) {
    throw "BLOCKED: IBKR_PAPER_SIGNAL_AUTOPILOT_MAX_RUNTIME_HOURS must be from 1 to 8760. No Paper or Live order was sent."
}
if (-not (Test-Path -LiteralPath $RepoDir -PathType Container)) {
    throw "BLOCKED: repository directory not found. No Paper or Live order was sent."
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "BLOCKED: .venv\Scripts\python.exe not found. No Paper or Live order was sent."
}
if ($env:AI_ASSET_ENABLE_LIVE_TRADING -or $env:AI_ASSET_LIVE_TRADING_UNLOCKED) {
    throw "BLOCKED: a Live trading flag is already present in the environment. No Paper or Live order was sent."
}

Set-Location -LiteralPath $RepoDir
New-Item -ItemType Directory -Path $LogDir -Force | Out-Null

function Get-GitSingleLine {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $output = & git @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        return ""
    }
    return (($output | Select-Object -First 1) -as [string]).Trim()
}

function Set-PrivatePinFile {
    param(
        [Parameter(Mandatory = $true)][string]$Path,
        [Parameter(Mandatory = $true)][string]$Value
    )
    $parent = Split-Path -Parent $Path
    New-Item -ItemType Directory -Path $parent -Force | Out-Null
    $temp = "$Path.tmp"
    [System.IO.File]::WriteAllText(
        $temp,
        $Value + [Environment]::NewLine,
        (New-Object System.Text.UTF8Encoding($false))
    )
    Move-Item -LiteralPath $temp -Destination $Path -Force

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

function Test-TrackedSourceClean {
    & git diff --quiet HEAD -- . ':(exclude)results/**' ':(exclude)data/**'
    $unstaged = $LASTEXITCODE
    & git diff --cached --quiet HEAD -- . ':(exclude)results/**' ':(exclude)data/**'
    $staged = $LASTEXITCODE
    return ($unstaged -eq 0 -and $staged -eq 0)
}

function Rotate-AutopilotLogIfNeeded {
    if (-not (Test-Path -LiteralPath $LogFile -PathType Leaf)) {
        return
    }
    $size = (Get-Item -LiteralPath $LogFile).Length
    if ($size -lt $MaxLogBytes) {
        return
    }
    if (Test-Path -LiteralPath $RotatedLogFile -PathType Leaf) {
        Remove-Item -LiteralPath $RotatedLogFile -Force
    }
    Move-Item -LiteralPath $LogFile -Destination $RotatedLogFile -Force
}

function Add-AutopilotLog {
    param([Parameter(Mandatory = $true)][string[]]$Lines)
    $Lines | Add-Content -LiteralPath $LogFile -Encoding UTF8
}

$initialBranch = Get-GitSingleLine -Arguments @("branch", "--show-current")
$initialHead = Get-GitSingleLine -Arguments @("rev-parse", "HEAD")
if ($initialBranch -ne "main" -or $initialHead -notmatch '^[0-9a-f]{40}$') {
    throw "BLOCKED: unattended signal runner must start from a valid local main commit. No Paper or Live order was sent."
}

if ($env:IBKR_PAPER_SIGNAL_AUTOPILOT_PINNED_HEAD) {
    $PinnedHead = $env:IBKR_PAPER_SIGNAL_AUTOPILOT_PINNED_HEAD.Trim()
} elseif (Test-Path -LiteralPath $PinFile -PathType Leaf) {
    $PinnedHead = (Get-Content -LiteralPath $PinFile -Raw).Trim()
} else {
    $PinnedHead = $initialHead
    Set-PrivatePinFile -Path $PinFile -Value $PinnedHead
    Write-Output "AUTOPILOT MIGRATION PIN: $PinnedHead"
}
if ($PinnedHead -notmatch '^[0-9a-f]{40}$') {
    throw "BLOCKED: unattended signal runner pinned revision is invalid. No Paper or Live order was sent."
}

# Explicit, deliberate Paper opt-in. Live is never set here, and the guard at
# the top of this script refuses to run at all if either Live flag is
# already present in the ambient environment.
$env:AI_ASSET_ENABLE_IBKR_PAPER = "1"
$env:PYTHONPATH = (Join-Path $RepoDir "src") + ";" + $RepoDir

$MarketSessionCheck = @"
from ai_asset_platform.execution.verified_market_session import evaluate_verified_market_session
tickers = ["AAPL", "SPY", "9432.T"]
results = [evaluate_verified_market_session(t) for t in tickers]
for ticker, result in zip(tickers, results):
    print(f"{ticker}: {result.session} ({result.reason})")
print("OPEN" if any(r.allowed for r in results) else "CLOSED")
"@

$StartTime = Get-Date

while ($true) {
    try {
        Rotate-AutopilotLogIfNeeded
        $header = "===== $([DateTimeOffset]::Now.ToString('o')) IBKR PAPER SIGNAL RUNNER AUTOPILOT (WINDOWS) ====="
        Add-AutopilotLog -Lines @($header)

        $elapsedHours = ((Get-Date) - $StartTime).TotalHours
        if ($elapsedHours -ge $MaxRuntimeHours) {
            Add-AutopilotLog -Lines @(
                "AUTOPILOT EXPIRED: max runtime of $MaxRuntimeHours hours reached. Exiting. Re-enabling requires a fresh explicit approval and re-running the installer.",
                "ORDER API REQUEST SENT: False",
                "REAL ORDER SENT: False",
                "LIVE ORDER SENT: False"
            )
            break
        }

        $currentBranch = Get-GitSingleLine -Arguments @("branch", "--show-current")
        $currentHead = Get-GitSingleLine -Arguments @("rev-parse", "HEAD")

        if ($currentBranch -ne "main") {
            Add-AutopilotLog -Lines @("AUTOPILOT SOURCE BLOCKED: local branch is '$currentBranch', expected 'main'. Signal runner was not executed.")
        } elseif ($currentHead -ne $PinnedHead) {
            Add-AutopilotLog -Lines @("AUTOPILOT SOURCE BLOCKED: local HEAD $currentHead differs from pinned audited HEAD $PinnedHead. Rerun the tested installer after review.")
        } elseif (-not (Test-TrackedSourceClean)) {
            Add-AutopilotLog -Lines @("AUTOPILOT SOURCE BLOCKED: tracked source differs from pinned HEAD outside runtime output directories. Signal runner was not executed.")
        } elseif (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
            Add-AutopilotLog -Lines @("SKIP: .venv\Scripts\python.exe not found. No Paper or Live order was sent.")
        } else {
            $sessionOutput = & $PythonExe -c $MarketSessionCheck 2>&1
            $sessionLines = @($sessionOutput | ForEach-Object { $_.ToString() })
            Add-AutopilotLog -Lines $sessionLines
            $marketOpen = ($sessionLines -contains "OPEN")

            if (-not $marketOpen) {
                Add-AutopilotLog -Lines @("VERIFIED TICKER MARKET SESSION CLOSED: skip cycle. Signal runner was not executed.")
            } else {
                $runnerOutput = & $PythonExe -m signal_runner 2>&1
                $runnerStatus = $LASTEXITCODE
                $runnerLines = @($runnerOutput | ForEach-Object { $_.ToString() })
                if ($runnerLines.Count -gt 0) {
                    Add-AutopilotLog -Lines $runnerLines
                }
                Add-AutopilotLog -Lines @("SIGNAL RUNNER EXIT CODE: $runnerStatus")
            }
        }

        Add-AutopilotLog -Lines @(
            "PINNED AUDITED HEAD: $PinnedHead",
            "LIVE ORDER SENT: False"
        )
    } catch {
        try {
            Add-AutopilotLog -Lines @(
                "AUTOPILOT WARNING: $($_.Exception.Message)",
                "LIVE ORDER SENT: False"
            )
        } catch {
            # If even local logging fails, keep the process alive and retry on
            # the next bounded interval. Never compensate by issuing an order.
        }
    }

    Start-Sleep -Seconds $IntervalSeconds
}
