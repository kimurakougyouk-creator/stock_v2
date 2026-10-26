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

function Remove-StalePycacheArtifacts {
    # Mirrors ibkr_paper_signal_runner_autopilot_windows.ps1's function of
    # the same name (see its own comment for the full 2026-10-25 incident
    # rationale): deletes only bytecode-cache artifacts that git reports
    # as ignored-and-present under the exact same fixed, narrow path set
    # the Windows source-SHA attestation audits (src/, tests/, and the
    # repository's own top-level files) -- never a repo-root-rooted
    # recursive filesystem scan. .venv, .env, and results/ are never named
    # in this pathspec, so they cannot appear in its output.
    # --directory makes git report an ignored __pycache__ directory as a
    # single collapsed entry (e.g. "src/__pycache__/") instead of expanding
    # its individual files -- needed because once the files inside such a
    # directory are gone, the directory itself is empty, and git never
    # tracks or reports empty directories at all, ignored or not.
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
        # Ignore every non-cache entry even when git marks it ignored.
        $isBytecode = $normalized.EndsWith('.pyc') -or $normalized.EndsWith('.pyo')
        $isCacheDir = ($normalized -match '(^|/)__pycache__$')
        if (-not ($isBytecode -or $isCacheDir)) { continue }
        $full = Join-Path $RepoDir $normalized
        $item = Get-Item -LiteralPath $full -ErrorAction SilentlyContinue
        if (-not $item) {
            continue
        }
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
            continue
        }
        try {
            if ($item.PSIsContainer) {
                # Never recursively remove a cache directory unless every
                # single thing anywhere inside it is an actual bytecode
                # cache file (.pyc/.pyo) and nothing inside it is a reparse
                # point. This directory was already independently confirmed
                # above to be literally named "__pycache__" and to live
                # under the git-restricted allowlist, so this recursive
                # Get-ChildItem/Remove-Item never leaves that single,
                # already-narrowed directory -- it cannot reintroduce the
                # repo-root-rooted scan that caused the 2026-10-25 incident.
                # A directory with any unexpected content (a secret, an
                # image, a backup, a symlink) is left untouched instead,
                # consistent with this project's fail-closed philosophy.
                if (-not $isCacheDir) { continue }
                $onlyCacheContents = $true
                $descendants = @(Get-ChildItem -LiteralPath $full -Recurse -Force -ErrorAction Stop)
                foreach ($descendant in $descendants) {
                    if ($descendant.Attributes -band [System.IO.FileAttributes]::ReparsePoint) {
                        $onlyCacheContents = $false
                        break
                    }
                    if ($descendant.PSIsContainer) {
                        continue
                    }
                    if ($descendant.Extension -ne ".pyc" -and $descendant.Extension -ne ".pyo") {
                        $onlyCacheContents = $false
                        break
                    }
                }
                if (-not $onlyCacheContents) {
                    continue
                }
                Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction Stop
            } else {
                Remove-Item -LiteralPath $full -Force -ErrorAction Stop
            }
        } catch {
            continue
        }
    }
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
Remove-StalePycacheArtifacts

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
Remove-StalePycacheArtifacts

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
