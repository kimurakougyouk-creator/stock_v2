#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# Fail-closed, time-boxed, Paper-only natural-strategy signal runner for
# Windows. Mirrors ibkr_readonly_autopilot_windows.ps1's safety pattern
# (pinned/clean main HEAD, bounded log, fail-closed on any ambiguity) but
# invokes the existing, already-guarded paper_trading_runner module instead
# of the read-only monitor, so natural Paper fills can actually start
# accumulating (Issue #255 / COMPLETION_ROADMAP.md Phase 5 blocker:
# NO_NATURAL_STRATEGY_FILLS).
#
# This script can place IBKR Paper orders. It can NEVER place a Live order:
# paper_trading_runner.run_paper_trading() itself refuses to run if either
# SETTINGS.enable_live_trading or SETTINGS.live_trading_unlocked is true
# (both default False), and execute_approved_signal_via_ibkr_paper() only
# ever connects to the IBKR Paper ports (4002/7497,
# ai_asset_platform.brokers.ibkr_config). Live is never set by this script,
# and a defensive check below also refuses to run at all if either Live
# flag is already present in the ambient environment.

$TaskName = "stock_v2 Paper Signal Runner Autopilot"
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
$PinFile = if ($env:IBKR_PAPER_SIGNAL_AUTOPILOT_PIN_FILE) {
    [System.IO.Path]::GetFullPath($env:IBKR_PAPER_SIGNAL_AUTOPILOT_PIN_FILE)
} else {
    Join-Path $HOME ".config\ai-asset-platform\ibkr-paper-signal-runner-autopilot-pinned-head"
}
# Deliberately NOT self-renewed here. Only the installer writes this file
# (computed once, at explicit human-approved install time, as an absolute
# UTC deadline). A process restart, scheduler AtLogOn retrigger, or crash
# loop re-reads the SAME stored deadline rather than resetting a fresh
# per-process clock, so no restart can silently extend the approved window.
$DeadlineFile = if ($env:IBKR_PAPER_SIGNAL_AUTOPILOT_DEADLINE_FILE) {
    [System.IO.Path]::GetFullPath($env:IBKR_PAPER_SIGNAL_AUTOPILOT_DEADLINE_FILE)
} else {
    Join-Path $HOME ".config\ai-asset-platform\ibkr-paper-signal-runner-autopilot-approval-deadline"
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
if (-not (Test-Path -LiteralPath $RepoDir -PathType Container)) {
    throw "BLOCKED: repository directory not found. No Paper or Live order was sent."
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "BLOCKED: .venv\Scripts\python.exe not found. No Paper or Live order was sent."
}
if ($env:AI_ASSET_ENABLE_LIVE_TRADING -or $env:AI_ASSET_LIVE_TRADING_UNLOCKED) {
    throw "BLOCKED: a Live trading flag is already present in the environment. No Paper or Live order was sent."
}
# Fail closed if the installer never staged an approval deadline. This
# script never creates or extends this file itself -- only a fresh,
# explicit installer run may.
if (-not (Test-Path -LiteralPath $DeadlineFile -PathType Leaf)) {
    throw "BLOCKED: no approval deadline file is staged. Re-run the installer to record a fresh explicit approval. No Paper or Live order was sent."
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

function Get-ApprovalDeadlineUtc {
    $raw = (Get-Content -LiteralPath $DeadlineFile -Raw).Trim()
    try {
        return [DateTime]::Parse($raw, $null, [System.Globalization.DateTimeStyles]::RoundtripKind).ToUniversalTime()
    } catch {
        return $null
    }
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
# Required for the Windows source-SHA attestation to ever pass: under normal
# Python defaults, simply importing modules (including the market-session
# check below, and paper_trading_runner's own import chain) writes .pyc
# bytecode under __pycache__/, which _WINDOWS_AUDITED_PATHS treats as an
# ignored-but-importable artifact and correctly fails closed on. Without
# this, the very act of running this script would permanently block its own
# next cycle's order dispatch.
$env:PYTHONDONTWRITEBYTECODE = "1"

function Remove-StalePycacheArtifacts {
    # One-time (and ongoing, self-healing) cleanup of bytecode caches that
    # predate PYTHONDONTWRITEBYTECODE being set here -- e.g. from the
    # installer's own test run, or any manual pytest/python invocation
    # against this checkout. These are always-regenerable build artifacts,
    # never tracked source, so deleting them cannot weaken the attestation;
    # it only removes the noise the attestation would otherwise (correctly)
    # fail closed on.
    #
    # 2026-10-25 incident: the prior implementation scanned the ENTIRE
    # repository root (Get-ChildItem -LiteralPath $RepoDir -Recurse ...),
    # including .venv/.env/results, relying only on a PowerShell filter
    # (-Include, then -File + an extension check after PR #364) to narrow
    # what Remove-Item actually received. The -Include form had a Windows
    # PowerShell 5.1 bug (silently ignored when combined with -LiteralPath)
    # that made it enumerate, and then delete, every file and directory
    # under $RepoDir -- deleting .env and most of .venv for real on this
    # machine. PR #364's -File fix closed that specific enumeration bug,
    # but the design still handed a repo-root-rooted recursive scan to
    # Remove-Item, so a different future filter mistake could reopen the
    # same class of damage. This version never passes $RepoDir itself to
    # anything recursive: it asks git -- not a PowerShell path filter --
    # which untracked files are ignored-and-present under the exact same
    # fixed, narrow path set the Windows source-SHA attestation itself
    # audits (src/, tests/, and the repository's own top-level files), and
    # deletes only those, one named path at a time, re-checked against the
    # same allowlist before every deletion, mirroring the explicit-
    # allowlist pattern already used by live_pilot_operational_once.ps1's
    # own pycache purge. .venv, .env, and results/ are never named in this
    # pathspec, so they cannot appear in its output regardless of any
    # filter bug, present or future.
    # --directory makes git report an ignored __pycache__ directory as a
    # single collapsed entry (e.g. "src/__pycache__/") instead of expanding
    # its individual files. This matters because once this function (or a
    # prior run of it) has already deleted the *files* inside such a
    # directory, the directory itself becomes empty -- and git never
    # tracks or reports empty directories at all, ignored or not, so a
    # files-only query would silently stop seeing it forever. --directory
    # closes that gap by letting git name the directory itself.
    $cacheCandidates = & git -C $RepoDir ls-files --others --ignored --exclude-standard --directory -- `
        src `
        tests `
        ":(top,glob)__pycache__" `
        ":(top,glob)*.pyc" `
        ":(top,glob)*.pyo" `
        2>$null
    if ($LASTEXITCODE -ne 0) {
        return
    }
    foreach ($relativePath in $cacheCandidates) {
        if (-not $relativePath) { continue }
        $normalized = ($relativePath -replace '\\', '/').TrimEnd('/')
        # Defense in depth: re-verify every path against the same fixed
        # allowlist implied by the git pathspec above, regardless of what
        # git actually returned, before this function ever touches disk.
        $isAllowed = (
            $normalized -like "src/*" -or
            $normalized -like "tests/*" -or
            $normalized -eq "__pycache__" -or
            $normalized -like "__pycache__/*" -or
            (
                $normalized -notmatch '/' -and (
                    $normalized.EndsWith(".pyc") -or
                    $normalized.EndsWith(".pyo")
                )
            )
        )
        if (-not $isAllowed) {
            continue
        }
        $full = Join-Path $RepoDir $normalized
        $item = Get-Item -LiteralPath $full -ErrorAction SilentlyContinue
        if (-not $item) {
            continue
        }
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            # Never follow or delete through a reparse point/symlink.
            continue
        }
        try {
            if ($item.PSIsContainer) {
                Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction Stop
            } else {
                Remove-Item -LiteralPath $full -Force -ErrorAction Stop
            }
        } catch {
            # Fail open on cleanup only: a stray cache file/dir that could
            # not be removed just means the next attestation correctly
            # fails closed on it, exactly as today -- never escalate a
            # cleanup failure into a wider deletion attempt.
            continue
        }
    }
}

$MarketSessionCheck = @"
from ai_asset_platform.execution.verified_market_session import evaluate_verified_market_session
tickers = ["AAPL", "SPY", "9432.T"]
results = [evaluate_verified_market_session(t) for t in tickers]
for ticker, result in zip(tickers, results):
    print(f"{ticker}: {result.session} ({result.reason})")
print("OPEN" if any(r.allowed for r in results) else "CLOSED")
"@

while ($true) {
    try {
        Rotate-AutopilotLogIfNeeded
        $header = "===== $([DateTimeOffset]::Now.ToString('o')) IBKR PAPER SIGNAL RUNNER AUTOPILOT (WINDOWS) ====="
        Add-AutopilotLog -Lines @($header)

        if (-not (Test-Path -LiteralPath $DeadlineFile -PathType Leaf)) {
            Add-AutopilotLog -Lines @(
                "AUTOPILOT EXPIRED: approval deadline file is missing. Exiting. Re-enabling requires a fresh explicit approval and re-running the installer.",
                "LIVE ORDER SENT: False"
            )
            try { Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null } catch {}
            break
        }
        $deadlineUtc = Get-ApprovalDeadlineUtc
        if ($null -eq $deadlineUtc) {
            Add-AutopilotLog -Lines @(
                "AUTOPILOT EXPIRED: approval deadline file is unreadable or malformed. Exiting. Re-enabling requires a fresh explicit approval and re-running the installer.",
                "LIVE ORDER SENT: False"
            )
            try { Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null } catch {}
            break
        }
        $nowUtc = (Get-Date).ToUniversalTime()
        if ($nowUtc -ge $deadlineUtc) {
            Add-AutopilotLog -Lines @(
                "AUTOPILOT EXPIRED: approval deadline $($deadlineUtc.ToString('o')) UTC reached. Exiting. Re-enabling requires a fresh explicit approval and re-running the installer.",
                "LIVE ORDER SENT: False"
            )
            try { Disable-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue | Out-Null } catch {}
            break
        }

        $currentBranch = Get-GitSingleLine -Arguments @("branch", "--show-current")
        $currentHead = Get-GitSingleLine -Arguments @("rev-parse", "HEAD")

        if ($currentBranch -ne "main") {
            Add-AutopilotLog -Lines @("AUTOPILOT SOURCE BLOCKED: local branch is '$currentBranch', expected 'main'. Paper trading runner was not executed.")
        } elseif ($currentHead -ne $PinnedHead) {
            Add-AutopilotLog -Lines @("AUTOPILOT SOURCE BLOCKED: local HEAD $currentHead differs from pinned audited HEAD $PinnedHead. Rerun the tested installer after review.")
        } elseif (-not (Test-TrackedSourceClean)) {
            Add-AutopilotLog -Lines @("AUTOPILOT SOURCE BLOCKED: tracked source differs from pinned HEAD outside runtime output directories. Paper trading runner was not executed.")
        } elseif (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
            Add-AutopilotLog -Lines @("SKIP: .venv\Scripts\python.exe not found. No Paper or Live order was sent.")
        } else {
            Remove-StalePycacheArtifacts
            $sessionOutput = & $PythonExe -c $MarketSessionCheck 2>&1
            $sessionLines = @($sessionOutput | ForEach-Object { $_.ToString() })
            Add-AutopilotLog -Lines $sessionLines
            $marketOpen = ($sessionLines -contains "OPEN")

            if (-not $marketOpen) {
                Add-AutopilotLog -Lines @("VERIFIED TICKER MARKET SESSION CLOSED: skip cycle. Paper trading runner was not executed.")
            } else {
                # paper_trading_runner.run_paper_trading() is the existing,
                # explicit, guarded Paper-order entry point: it refuses to run
                # if either Live flag is set, restricts dispatch to the
                # broker-verified ticker/quantity universe, and still passes
                # every order through the shared risk gate (including the
                # emergency-stop latch) and the verified market-session guard
                # before any broker call.
                $runnerOutput = & $PythonExe -m paper_trading_runner 2>&1
                $runnerStatus = $LASTEXITCODE
                $runnerLines = @($runnerOutput | ForEach-Object { $_.ToString() })
                if ($runnerLines.Count -gt 0) {
                    Add-AutopilotLog -Lines $runnerLines
                }
                Add-AutopilotLog -Lines @("PAPER TRADING RUNNER EXIT CODE: $runnerStatus")
            }
        }

        Add-AutopilotLog -Lines @(
            "PINNED AUDITED HEAD: $PinnedHead",
            "APPROVAL DEADLINE UTC: $($deadlineUtc.ToString('o'))",
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
