#requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$RepoDir = if ($env:IBKR_REPO_DIR) {
    [System.IO.Path]::GetFullPath($env:IBKR_REPO_DIR)
} else {
    Join-Path $HOME "stock_v2_latest"
}
$TaskName = "IBKR Readonly Autopilot"
$PinFile = if ($env:IBKR_AUTOPILOT_PIN_FILE) {
    [System.IO.Path]::GetFullPath($env:IBKR_AUTOPILOT_PIN_FILE)
} else {
    Join-Path $HOME ".config\ai-asset-platform\ibkr-readonly-autopilot-pinned-head"
}
$AutopilotScript = Join-Path $RepoDir "ibkr_readonly_autopilot_windows.ps1"
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
    throw "BLOCKED: repository directory not found. No order was sent."
}
if (-not (Test-Path -LiteralPath $PythonExe -PathType Leaf)) {
    throw "BLOCKED: .venv\Scripts\python.exe not found. No order was sent."
}
if (-not (Test-Path -LiteralPath $AutopilotScript -PathType Leaf)) {
    throw "BLOCKED: Windows read-only autopilot script not found. No order was sent."
}

Set-Location -LiteralPath $RepoDir
$branch = Get-GitSingleLine -Arguments @("branch", "--show-current")
$PinnedHead = Get-GitSingleLine -Arguments @("rev-parse", "HEAD")
if ($branch -ne "main") {
    throw "BLOCKED: installer must run from local main. No order was sent."
}
if ($PinnedHead -notmatch '^[0-9a-f]{40}$') {
    throw "BLOCKED: current main revision is invalid. No order was sent."
}
if (-not (Test-TrackedSourceClean)) {
    throw "BLOCKED: tracked source differs from current main outside runtime outputs. No order was sent."
}

Write-Host "===== WINDOWS READ-ONLY AUTOPILOT TESTS ====="
& $PythonExe -m pytest -q `
    tests/test_ibkr_windows_readonly_autopilot.py `
    tests/test_ibkr_account_snapshot.py `
    tests/test_ibkr_all_open_orders_snapshot.py `
    tests/test_ibkr_paper_operations_monitor.py `
    tests/test_ibkr_paper_operations_monitor_strict.py
if ($LASTEXITCODE -ne 0) {
    throw "BLOCKED: Windows read-only autopilot tests failed. No order was sent."
}

# Parse both PowerShell files with the same Windows PowerShell parser used by
# the scheduled task. Syntax errors block installation before any task changes.
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

$PowerShellExe = Join-Path $env:SystemRoot "System32\WindowsPowerShell\v1.0\powershell.exe"
if (-not (Test-Path -LiteralPath $PowerShellExe -PathType Leaf)) {
    throw "BLOCKED: Windows PowerShell executable not found. No task was installed."
}

$currentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$action = New-ScheduledTaskAction `
    -Execute $PowerShellExe `
    -Argument "-NoProfile -NonInteractive -ExecutionPolicy Bypass -File `"$AutopilotScript`"" `
    -WorkingDirectory $RepoDir
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $currentUser
$principal = New-ScheduledTaskPrincipal `
    -UserId $currentUser `
    -LogonType Interactive `
    -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet `
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
    -Description "Pinned, fail-closed IBKR Paper read-only operations monitor. Never places, changes, cancels, closes, or retries orders."

Register-ScheduledTask -TaskName $TaskName -InputObject $task -Force | Out-Null
try {
    Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
} catch {
    # An inactive task needs no stop action.
}
Start-ScheduledTask -TaskName $TaskName

Write-Host "IBKR Windows read-only autopilot installed and started."
Write-Host "TASK NAME: $TaskName"
Write-Host "PINNED AUDITED HEAD: $PinnedHead"
Write-Host "INTERVAL: 300 seconds by default"
Write-Host "AUTO START: current-user logon"
Write-Host "AUTO RESTART: enabled after process failure"
Write-Host "EXECUTION TIME LIMIT: disabled"
Write-Host "ORDER API REQUEST SENT: False"
Write-Host "REAL ORDER SENT: False"
Write-Host "LIVE ORDER SENT: False"
