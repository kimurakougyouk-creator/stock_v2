#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoDir = if ($env:IBKR_REPO_DIR) {
    [System.IO.Path]::GetFullPath($env:IBKR_REPO_DIR)
} else {
    Join-Path $HOME "stock_v2_latest"
}
$IntervalSeconds = if ($env:IBKR_AUTOPILOT_INTERVAL_SECONDS) {
    [int]$env:IBKR_AUTOPILOT_INTERVAL_SECONDS
} else {
    300
}
$MaxLogBytes = if ($env:IBKR_AUTOPILOT_MAX_LOG_BYTES) {
    [long]$env:IBKR_AUTOPILOT_MAX_LOG_BYTES
} else {
    5242880
}
$PinFile = if ($env:IBKR_AUTOPILOT_PIN_FILE) {
    [System.IO.Path]::GetFullPath($env:IBKR_AUTOPILOT_PIN_FILE)
} else {
    Join-Path $HOME ".config\ai-asset-platform\ibkr-readonly-autopilot-pinned-head"
}
$LogDir = Join-Path $RepoDir "results"
$LogFile = Join-Path $LogDir "ibkr_readonly_autopilot.log"
$RotatedLogFile = "$LogFile.1"
$MonitorLog = Join-Path $LogDir "ibkr_paper_operations_monitor_latest.log"
$PythonExe = Join-Path $RepoDir ".venv\Scripts\python.exe"

if ($IntervalSeconds -lt 30 -or $IntervalSeconds -gt 86400) {
    throw "BLOCKED: IBKR_AUTOPILOT_INTERVAL_SECONDS must be from 30 to 86400. No order was sent."
}
if ($MaxLogBytes -lt 1048576 -or $MaxLogBytes -gt 104857600) {
    throw "BLOCKED: IBKR_AUTOPILOT_MAX_LOG_BYTES must be from 1048576 to 104857600. No order was sent."
}
if (-not (Test-Path -LiteralPath $RepoDir -PathType Container)) {
    throw "BLOCKED: repository directory not found. No order was sent."
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "BLOCKED: .venv\Scripts\python.exe not found. No order was sent."
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

    # Restrict the revision pin to the current Windows identity. This mirrors
    # the mode-0600 intent of the Linux installer without requiring elevation.
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
    throw "BLOCKED: unattended monitor must start from a valid local main commit. No order was sent."
}

if ($env:IBKR_AUTOPILOT_PINNED_HEAD) {
    $PinnedHead = $env:IBKR_AUTOPILOT_PINNED_HEAD.Trim()
} elseif (Test-Path -LiteralPath $PinFile -PathType Leaf) {
    $PinnedHead = (Get-Content -LiteralPath $PinFile -Raw).Trim()
} else {
    $PinnedHead = $initialHead
    Set-PrivatePinFile -Path $PinFile -Value $PinnedHead
    Write-Output "AUTOPILOT MIGRATION PIN: $PinnedHead"
}
if ($PinnedHead -notmatch '^[0-9a-f]{40}$') {
    throw "BLOCKED: unattended monitor pinned revision is invalid. No order was sent."
}

# Match the existing monitored-Paper policy. These defaults affect only the
# read-only monitor; they do not unlock Paper order transmission or Live Trading.
if (-not $env:IBKR_PAPER_MONITOR_MAX_RUNTIME_AGE_HOURS) {
    $env:IBKR_PAPER_MONITOR_MAX_RUNTIME_AGE_HOURS = "96"
}
if (-not $env:IBKR_PAPER_MONITOR_MAX_HISTORY_BYTES) {
    $env:IBKR_PAPER_MONITOR_MAX_HISTORY_BYTES = "10485760"
}
if (-not $env:IBKR_PAPER_MONITOR_EMAIL_ALERTS) {
    $env:IBKR_PAPER_MONITOR_EMAIL_ALERTS = "auto"
}
if (-not $env:IBKR_PAPER_MONITOR_EMAIL_COOLDOWN_HOURS) {
    $env:IBKR_PAPER_MONITOR_EMAIL_COOLDOWN_HOURS = "12"
}
$env:PYTHONPATH = (Join-Path $RepoDir "src") + ";" + $RepoDir

while ($true) {
    try {
        Rotate-AutopilotLogIfNeeded
        $header = "===== $([DateTimeOffset]::Now.ToString('o')) IBKR READ-ONLY AUTOPILOT (WINDOWS) ====="
        Add-AutopilotLog -Lines @($header)

        $currentBranch = Get-GitSingleLine -Arguments @("branch", "--show-current")
        $currentHead = Get-GitSingleLine -Arguments @("rev-parse", "HEAD")

        if ($currentBranch -ne "main") {
            Add-AutopilotLog -Lines @("AUTOPILOT SOURCE BLOCKED: local branch is '$currentBranch', expected 'main'. Monitoring code was not executed.")
        } elseif ($currentHead -ne $PinnedHead) {
            Add-AutopilotLog -Lines @("AUTOPILOT SOURCE BLOCKED: local HEAD $currentHead differs from pinned audited HEAD $PinnedHead. Rerun the tested installer after review.")
        } elseif (-not (Test-TrackedSourceClean)) {
            Add-AutopilotLog -Lines @("AUTOPILOT SOURCE BLOCKED: tracked source differs from pinned HEAD outside runtime output directories. Monitoring code was not executed.")
        } elseif (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
            Add-AutopilotLog -Lines @("SKIP: .venv\Scripts\python.exe not found. No order was sent.")
        } else {
            $monitorOutput = & $PythonExe -m ai_asset_platform.brokers.ibkr_paper_operations_monitor_strict 2>&1
            $monitorStatus = $LASTEXITCODE
            $monitorLines = @($monitorOutput | ForEach-Object { $_.ToString() })
            $monitorLines | Set-Content -LiteralPath $MonitorLog -Encoding UTF8
            if ($monitorLines.Count -gt 0) {
                Add-AutopilotLog -Lines $monitorLines
            }
            if ($monitorStatus -eq 2) {
                Add-AutopilotLog -Lines @("PAPER OPERATIONS CRITICAL: manual review is required; no order was changed, cancelled, or retried.")
            } elseif ($monitorStatus -eq 1) {
                Add-AutopilotLog -Lines @("PAPER OPERATIONS WARNING: monitoring continues; no order was changed, cancelled, or retried.")
            } elseif ($monitorStatus -ne 0) {
                Add-AutopilotLog -Lines @("PAPER OPERATIONS WARNING: monitor exited with status $monitorStatus; monitoring continues; no order was changed, cancelled, or retried.")
            }
            Add-AutopilotLog -Lines @("PAPER OPERATIONS MONITOR LOG: $MonitorLog")
        }

        Add-AutopilotLog -Lines @(
            "PINNED AUDITED HEAD: $PinnedHead",
            "ORDER API REQUEST SENT: False",
            "REAL ORDER SENT: False",
            "LIVE ORDER SENT: False"
        )
    } catch {
        try {
            Add-AutopilotLog -Lines @(
                "AUTOPILOT WARNING: $($_.Exception.Message)",
                "ORDER API REQUEST SENT: False",
                "REAL ORDER SENT: False",
                "LIVE ORDER SENT: False"
            )
        } catch {
            # If even local logging fails, keep the process alive and retry on
            # the next bounded interval. Never compensate by issuing an order.
        }
    }

    Start-Sleep -Seconds $IntervalSeconds
}
