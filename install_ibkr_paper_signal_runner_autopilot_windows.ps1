#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoDir = if ($env:IBKR_REPO_DIR) {
    [System.IO.Path]::GetFullPath($env:IBKR_REPO_DIR)
} else {
    Join-Path $HOME "stock_v2_latest"
}
$TaskName = "stock_v2 Paper Signal Runner Autopilot"
$PinFile = if ($env:IBKR_PAPER_SIGNAL_AUTOPILOT_PIN_FILE) {
    [System.IO.Path]::GetFullPath($env:IBKR_PAPER_SIGNAL_AUTOPILOT_PIN_FILE)
} else {
    Join-Path $HOME ".config\ai-asset-platform\ibkr-paper-signal-runner-autopilot-pinned-head"
}
$DeadlineFile = if ($env:IBKR_PAPER_SIGNAL_AUTOPILOT_DEADLINE_FILE) {
    [System.IO.Path]::GetFullPath($env:IBKR_PAPER_SIGNAL_AUTOPILOT_DEADLINE_FILE)
} else {
    Join-Path $HOME ".config\ai-asset-platform\ibkr-paper-signal-runner-autopilot-approval-deadline"
}
# 24-hour bounded trial window, per the user's explicit 2026-10-24 chat
# instruction ("15分間隔・24時間の試験設定にしてください。14日間は承認しません。").
# A longer window requires a fresh explicit approval and a different value
# here, re-running this installer.
$MaxRuntimeHours = if ($env:IBKR_PAPER_SIGNAL_AUTOPILOT_MAX_RUNTIME_HOURS) {
    [double]$env:IBKR_PAPER_SIGNAL_AUTOPILOT_MAX_RUNTIME_HOURS
} else {
    24
}
if ($MaxRuntimeHours -lt 1 -or $MaxRuntimeHours -gt 8760) {
    throw "BLOCKED: IBKR_PAPER_SIGNAL_AUTOPILOT_MAX_RUNTIME_HOURS must be from 1 to 8760. No Paper or Live order was sent."
}
$AutopilotScript = Join-Path $RepoDir "ibkr_paper_signal_runner_autopilot_windows.ps1"
$PythonExe = Join-Path $RepoDir ".venv\Scripts\python.exe"

function Get-GitSingleLine {
    param([Parameter(Mandatory = $true)][string[]]$Arguments)
    $output = & git @Arguments 2>$null
    if ($LASTEXITCODE -ne 0) {
        return ""
    }
    return (($output | Select-Object -First 1) -as [string]).Trim()
}

function Test-TrackedSourceClean {
    & git diff --quiet HEAD -- . ':(exclude)results/**' ':(exclude)data/**'
    $unstaged = $LASTEXITCODE
    & git diff --cached --quiet HEAD -- . ':(exclude)results/**' ':(exclude)data/**'
    $staged = $LASTEXITCODE
    return ($unstaged -eq 0 -and $staged -eq 0)
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

if (-not (Test-Path -LiteralPath $RepoDir -PathType Container)) {
    throw "BLOCKED: repository directory not found. No Paper or Live order was sent."
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "BLOCKED: .venv\Scripts\python.exe not found. No Paper or Live order was sent."
}
if (-not (Test-Path -LiteralPath $AutopilotScript -PathType Leaf)) {
    throw "BLOCKED: Windows Paper signal runner autopilot script not found. No Paper or Live order was sent."
}

Set-Location -LiteralPath $RepoDir
$branch = Get-GitSingleLine -Arguments @("branch", "--show-current")
$PinnedHead = Get-GitSingleLine -Arguments @("rev-parse", "HEAD")
if ($branch -ne "main") {
    throw "BLOCKED: installer must run from local main. No Paper or Live order was sent."
}
if ($PinnedHead -notmatch '^[0-9a-f]{40}$') {
    throw "BLOCKED: current main revision is invalid. No Paper or Live order was sent."
}
if (-not (Test-TrackedSourceClean)) {
    throw "BLOCKED: tracked source differs from current main outside runtime outputs. No Paper or Live order was sent."
}

# PYTHONDONTWRITEBYTECODE prevents this test run itself from writing .pyc
# caches that the autopilot's Windows source-SHA attestation would then
# (correctly) fail closed on as ignored-but-importable artifacts. Clean any
# pre-existing caches from earlier, unrelated python/pytest runs against
# this checkout first, so the tree is genuinely clean before the autopilot
# ever starts.
$env:PYTHONDONTWRITEBYTECODE = "1"
Get-ChildItem -LiteralPath $RepoDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $RepoDir -Recurse -Include "*.pyc", "*.pyo" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

Write-Host "===== WINDOWS PAPER SIGNAL RUNNER AUTOPILOT TESTS ====="
& $PythonExe -m pytest -q `
    tests/test_ibkr_windows_paper_signal_runner_autopilot.py `
    tests/test_verified_market_session.py `
    tests/test_signal_runner.py `
    tests/test_signal_runner_windows_source_sha.py `
    tests/test_ibkr_signal_runtime_endpoint.py `
    tests/test_ibkr_signal_runtime_fill_evidence.py `
    tests/test_ibkr_signal_runtime_fx_evidence.py `
    tests/test_ibkr_signal_runtime_source_sha.py `
    tests/test_paper_trading_runner.py `
    tests/test_verified_paper_scan.py
if ($LASTEXITCODE -ne 0) {
    throw "BLOCKED: Windows Paper signal runner autopilot tests failed. No Paper or Live order was sent."
}

# Clean again after the test run itself, belt-and-suspenders: the autopilot
# script performs this same cleanup every cycle regardless, but leaving the
# tree clean here too means its very first cycle does not depend on that.
Get-ChildItem -LiteralPath $RepoDir -Recurse -Directory -Filter "__pycache__" -ErrorAction SilentlyContinue |
    Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath $RepoDir -Recurse -Include "*.pyc", "*.pyo" -ErrorAction SilentlyContinue |
    Remove-Item -Force -ErrorAction SilentlyContinue

# Parse both PowerShell files with the same Windows PowerShell parser used by
# the scheduled task. Syntax errors block staging before any task changes.
foreach ($scriptPath in @($AutopilotScript, $PSCommandPath)) {
    $tokens = $null
    $errors = $null
    [System.Management.Automation.Language.Parser]::ParseFile(
        $scriptPath,
        [ref]$tokens,
        [ref]$errors
    ) | Out-Null
    if ($errors.Count -ne 0) {
        $details = ($errors | ForEach-Object { $_.Message }) -join "; "
        throw "BLOCKED: PowerShell syntax validation failed for $scriptPath : $details"
    }
}

Set-PrivatePinFile -Path $PinFile -Value $PinnedHead

# Compute the absolute approval deadline once, now, at explicit install time.
# The autopilot script only ever reads this file; it never writes or renews
# it, so a crash restart, AtLogOn retrigger, or RestartOnFailure cannot
# silently extend the approved window -- extending requires re-running this
# installer, which re-validates main/clean-source/tests first.
$ApprovalDeadlineUtc = (Get-Date).ToUniversalTime().AddHours($MaxRuntimeHours)
Set-PrivatePinFile -Path $DeadlineFile -Value $ApprovalDeadlineUtc.ToString("o")

$PowerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path -LiteralPath $PowerShellExe -PathType Leaf)) {
    throw "BLOCKED: Windows PowerShell executable not found. No task was staged."
}

# Same -WindowStyle Hidden rationale as the existing read-only autopilot
# installer: keeps a real PowerShell exit code as LastTaskResult instead of
# a wrapper that always reports 0, and avoids a console handoff that an
# external terminal closing could kill with 0xC000013A.
$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction `
    -Execute $PowerShellExe `
    -Argument "-WindowStyle Hidden -NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$AutopilotScript`"" `
    -WorkingDirectory $RepoDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
    -Disable `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -MultipleInstances IgnoreNew `
    -RestartCount 999 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit ([TimeSpan]::Zero)
$task = New-ScheduledTask `
    -Action $action `
    -Trigger $trigger `
    -Principal $principal `
    -Settings $settings `
    -Description "Pinned, fail-closed, self-expiring natural-strategy IBKR Paper signal runner. Paper only; never places a Live order."

# Migration safety: the task definition itself is disabled before
# registration, mirroring install_ibkr_readonly_autopilot_windows.ps1. There
# is no registration-to-disable window. A separate, explicit enable step
# (Enable-ScheduledTask + Start-ScheduledTask) is required after this
# installer runs, so staging alone never starts live Paper order placement.
Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
Disable-ScheduledTask -TaskName $TaskName | Out-Null

$staged = Get-ScheduledTask -TaskName $TaskName
if ($staged.State -ne "Disabled") {
    throw "BLOCKED: Windows Paper signal runner autopilot task did not remain disabled after staging."
}

Write-Host "IBKR Paper signal runner autopilot staged DISABLED."
Write-Host "TASK NAME: $TaskName"
Write-Host "TASK STATE: Disabled"
Write-Host "PINNED AUDITED HEAD: $PinnedHead"
Write-Host "INTERVAL: 900 seconds by default"
Write-Host "APPROVAL DEADLINE (UTC): $($ApprovalDeadlineUtc.ToString('o'))"
Write-Host "MAX RUNTIME: $MaxRuntimeHours hours; persisted on disk, read-only to the autopilot process, self-expires and self-disables the task; requires re-running this installer for a fresh approval to resume"
Write-Host "AUTO START AFTER ENABLE: current-user logon"
Write-Host "AUTO RESTART AFTER ENABLE: enabled after process failure"
Write-Host "ORDER API REQUEST SENT: False"
Write-Host "REAL ORDER SENT: False"
Write-Host "LIVE ORDER SENT: False"
