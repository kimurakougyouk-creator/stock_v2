#requires -Version 5.1
# Re-executable, head-tied verification harness for
# backup_restore_env_secrets_windows.ps1 and
# verify_gemini_env_key_windows.ps1.
#
# Independent audit follow-up (PR #365, Work comment 6395349716): prior
# rounds of verification were reported as narration (PM claims of what
# was run and what happened) rather than as a committed, re-executable
# script anyone could run against the exact HEAD and get raw PASS/FAIL
# output from. This script is that artifact: every adversarial
# scenario checked by hand during PR #365's review rounds is captured
# here as a real, repeatable assertion against the actual production
# scripts in this repository (dot-sourced directly, never
# reimplemented). It touches only disposable dummy files under a
# fresh, randomly-named directory in $env:TEMP, and removes that
# directory when it finishes. It never touches the repository's own
# .env or any real secret.
#
# Usage: powershell.exe -File scripts\verify_backup_restore_env_secrets_windows.ps1
# Exit code 0 = every check passed. Non-zero = at least one failed;
# the failing check names are printed to stderr as well as stdout.

Set-StrictMode -Off
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackupRestoreScript = Join-Path $RepoRoot "backup_restore_env_secrets_windows.ps1"
$VerifyGeminiScript = Join-Path $RepoRoot "verify_gemini_env_key_windows.ps1"

if (-not (Test-Path -LiteralPath $BackupRestoreScript -PathType Leaf)) {
    throw "BLOCKED: $BackupRestoreScript not found."
}

. $BackupRestoreScript

$results = New-Object System.Collections.Generic.List[object]

function Invoke-Check {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Body
    )
    try {
        $outcome = & $Body
        if ($outcome -eq $false) {
            $results.Add([pscustomobject]@{ Name = $Name; Pass = $false; Detail = "assertion returned false" })
        } else {
            $results.Add([pscustomobject]@{ Name = $Name; Pass = $true; Detail = "" })
        }
    } catch {
        $results.Add([pscustomobject]@{ Name = $Name; Pass = $false; Detail = $_.Exception.Message })
    }
}

$TestRoot = Join-Path $env:TEMP ("stock_v2_backup_restore_verify_" + [System.IO.Path]::GetRandomFileName())
New-Item -ItemType Directory -Path $TestRoot -Force | Out-Null

try {
    $Source = Join-Path $TestRoot "dummy.env"
    "DUMMY_PLACEHOLDER_API_KEY=harness-verification" | Set-Content -LiteralPath $Source -Encoding utf8 -NoNewline
    $Backup = Join-Path $TestRoot "dummy.env.backup"
    $Restored = Join-Path $TestRoot "restored.env"

    Invoke-Check "round_trip_hash_matches" {
        Backup-EnvSecrets -SourcePath $Source -BackupPath $Backup
        Restore-EnvSecrets -BackupPath $Backup -DestinationPath $Restored
        (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash -eq (Get-FileHash -LiteralPath $Restored -Algorithm SHA256).Hash
    }

    Invoke-Check "ciphertext_never_contains_plaintext" {
        -not (Get-Content -LiteralPath $Backup -Raw).Contains("harness-verification")
    }

    Invoke-Check "restored_file_acl_has_exactly_one_rule" {
        (Get-Acl -LiteralPath $Restored).Access.Count -eq 1
    }

    Invoke-Check "backup_rejects_source_equals_backup_path" {
        try { Backup-EnvSecrets -SourcePath $Source -BackupPath $Source; $false } catch { $true }
    }

    Invoke-Check "restore_rejects_backup_equals_destination_path" {
        try { Restore-EnvSecrets -BackupPath $Backup -DestinationPath $Backup -Force; $false } catch { $true }
    }

    Invoke-Check "backup_rejects_hardlink_alias_of_source" {
        $alias = Join-Path $TestRoot "dummy_alias.env"
        if (Test-Path -LiteralPath $alias) { Remove-Item -LiteralPath $alias -Force }
        New-Item -ItemType HardLink -Path $alias -Value $Source | Out-Null
        try { Backup-EnvSecrets -SourcePath $Source -BackupPath $alias; $false } catch { $true }
    }

    Invoke-Check "backup_rejects_junction_as_immediate_parent" {
        $realDir = Join-Path $TestRoot "realtarget1"
        New-Item -ItemType Directory -Path $realDir -Force | Out-Null
        $junction = Join-Path $TestRoot "junction1"
        if (Test-Path -LiteralPath $junction) { cmd /c rmdir "$junction" | Out-Null }
        cmd /c mklink /J "$junction" "$realDir" | Out-Null
        $target = Join-Path $junction "via-junction.backup"
        try { Backup-EnvSecrets -SourcePath $Source -BackupPath $target; $false } catch { $true }
    }

    Invoke-Check "backup_rejects_junction_one_level_above_immediate_parent" {
        $realDir = Join-Path $TestRoot "realtarget2"
        New-Item -ItemType Directory -Path $realDir -Force | Out-Null
        $junction = Join-Path $TestRoot "junction2"
        if (Test-Path -LiteralPath $junction) { cmd /c rmdir "$junction" | Out-Null }
        cmd /c mklink /J "$junction" "$realDir" | Out-Null
        $target = Join-Path $junction "sub\env.backup"
        try { Backup-EnvSecrets -SourcePath $Source -BackupPath $target; $false } catch { $true }
    }

    Invoke-Check "backup_leaves_unrelated_file_at_old_fixed_temp_name_untouched" {
        $oldStyleTemp = "$Backup.tmp"
        "UNRELATED_BACKUP_SIDE" | Set-Content -LiteralPath $oldStyleTemp -Encoding utf8 -NoNewline
        $before = (Get-FileHash -LiteralPath $oldStyleTemp -Algorithm SHA256).Hash
        Backup-EnvSecrets -SourcePath $Source -BackupPath $Backup -Force
        $after = (Get-FileHash -LiteralPath $oldStyleTemp -Algorithm SHA256).Hash
        $before -eq $after
    }

    Invoke-Check "restore_leaves_unrelated_file_at_old_fixed_temp_name_untouched" {
        $oldStyleRestoreTemp = "$Restored.tmp"
        "UNRELATED_RESTORE_SIDE" | Set-Content -LiteralPath $oldStyleRestoreTemp -Encoding utf8 -NoNewline
        $before = (Get-FileHash -LiteralPath $oldStyleRestoreTemp -Algorithm SHA256).Hash
        Remove-Item -LiteralPath $Restored -Force -ErrorAction SilentlyContinue
        Restore-EnvSecrets -BackupPath $Backup -DestinationPath $Restored
        $after = (Get-FileHash -LiteralPath $oldStyleRestoreTemp -Algorithm SHA256).Hash
        $before -eq $after
    }

    Invoke-Check "restore_rejects_existing_zero_byte_destination_without_force" {
        $emptyDest = Join-Path $TestRoot "empty_placeholder.env"
        New-Item -ItemType File -Path $emptyDest -Force | Out-Null
        $rejected = $false
        try { Restore-EnvSecrets -BackupPath $Backup -DestinationPath $emptyDest } catch { $rejected = $true }
        $stillEmpty = (Get-Item -LiteralPath $emptyDest).Length -eq 0
        $rejected -and $stillEmpty
    }

    Invoke-Check "restore_force_overwrites_existing_zero_byte_destination" {
        $emptyDest = Join-Path $TestRoot "empty_placeholder.env"
        Restore-EnvSecrets -BackupPath $Backup -DestinationPath $emptyDest -Force
        (Get-FileHash -LiteralPath $emptyDest -Algorithm SHA256).Hash -eq (Get-FileHash -LiteralPath $Source -Algorithm SHA256).Hash
    }

    Invoke-Check "native_move_item_without_force_refuses_existing_destination" {
        $src2 = Join-Path $TestRoot "moveitem_src.txt"
        $dst2 = Join-Path $TestRoot "moveitem_dst.txt"
        "source" | Set-Content -LiteralPath $src2 -Encoding utf8 -NoNewline
        "already-here" | Set-Content -LiteralPath $dst2 -Encoding utf8 -NoNewline
        $threw = $false
        try { Move-Item -LiteralPath $src2 -Destination $dst2 } catch { $threw = $true }
        $threw -and ((Get-Content -LiteralPath $dst2 -Raw) -eq "already-here")
    }

    Invoke-Check "backup_rejects_overwriting_an_unrelated_existing_file_without_force" {
        $unrelated = Join-Path $TestRoot "accidentally_specified_important_file.env"
        "IMPORTANT_UNRELATED_USER_DATA" | Set-Content -LiteralPath $unrelated -Encoding utf8 -NoNewline
        $rejected = $false
        try { Backup-EnvSecrets -SourcePath $Source -BackupPath $unrelated } catch { $rejected = $true }
        $intact = (Get-Content -LiteralPath $unrelated -Raw) -eq "IMPORTANT_UNRELATED_USER_DATA"
        $rejected -and $intact
    }

    Invoke-Check "backup_refresh_of_a_real_backup_slot_succeeds_without_force" {
        $slot = Join-Path $TestRoot "refresh_slot.backup"
        Backup-EnvSecrets -SourcePath $Source -BackupPath $slot
        Start-Sleep -Milliseconds 50
        Backup-EnvSecrets -SourcePath $Source -BackupPath $slot
        Test-Path -LiteralPath $slot
    }

    Invoke-Check "backup_force_overwrites_an_unrelated_existing_file_when_explicitly_requested" {
        $unrelated = Join-Path $TestRoot "force_overwrite_target.env"
        "IMPORTANT_UNRELATED_USER_DATA_2" | Set-Content -LiteralPath $unrelated -Encoding utf8 -NoNewline
        Backup-EnvSecrets -SourcePath $Source -BackupPath $unrelated -Force
        (Get-Content -LiteralPath $unrelated -Raw) -ne "IMPORTANT_UNRELATED_USER_DATA_2"
    }

    Invoke-Check "backup_rejects_a_real_backup_slot_swapped_for_an_unrelated_file_without_force" {
        # Work independent audit, PR #365 comment 6395349716 follow-up:
        # a validated real backup slot could, in principle, be replaced
        # by a competing process with an unrelated file before the
        # final move. Simulate that by swapping a real backup slot's
        # content for an unrelated file, then confirming
        # Backup-EnvSecrets still refuses to overwrite it without
        # -Force (the up-front and pre-move re-validation both see the
        # same swapped, non-own-backup content).
        $slot2 = Join-Path $TestRoot "swap_test_slot.backup"
        Backup-EnvSecrets -SourcePath $Source -BackupPath $slot2
        "SWAPPED_BY_SOMEONE_ELSE" | Set-Content -LiteralPath $slot2 -Encoding utf8 -NoNewline -Force
        $rejected = $false
        try { Backup-EnvSecrets -SourcePath $Source -BackupPath $slot2 } catch { $rejected = $true }
        $intact = (Get-Content -LiteralPath $slot2 -Raw) -eq "SWAPPED_BY_SOMEONE_ELSE"
        $rejected -and $intact
    }

    if (Test-Path -LiteralPath $VerifyGeminiScript -PathType Leaf) {
        Invoke-Check "verify_gemini_env_key_leaves_unrelated_file_at_old_fixed_temp_script_path_untouched" {
            # Codex (PR #365 comment 4370214392): this check plants its
            # sentinel directly in the real checkout (the old fixed
            # path verify_gemini_env_key_windows.ps1 used to use), not
            # under $TestRoot. An earlier version unconditionally
            # Set-Content'd and later deleted that fixed path -- which,
            # if the operator's real checkout already had an unrelated
            # file there, would reproduce exactly the fixed-name
            # overwrite/delete bug this whole PR exists to prevent. The
            # sentinel is now created exclusively (FileMode.CreateNew):
            # if that path already exists for any reason, this check is
            # skipped rather than touching it, and cleanup only ever
            # removes the file this run itself just created.
            $oldFixedTemp = Join-Path $RepoRoot "_verify_gemini_env_key_tmp.py"
            $sentinelFs = $null
            try {
                $sentinelFs = [System.IO.File]::Open($oldFixedTemp, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
            } catch [System.IO.IOException] {
                Write-Host "SKIP  verify_gemini_env_key_leaves_unrelated_file_at_old_fixed_temp_script_path_untouched -- $oldFixedTemp already exists in the real checkout; not touching it"
                return $true
            }
            $writer = New-Object System.IO.StreamWriter($sentinelFs, (New-Object System.Text.UTF8Encoding($false)))
            $writer.Write("IMPORTANT_UNRELATED_PY_CONTENT")
            $writer.Flush()
            $writer.Dispose()
            $before = (Get-FileHash -LiteralPath $oldFixedTemp -Algorithm SHA256).Hash
            Push-Location $RepoRoot
            try {
                & $VerifyGeminiScript 2>&1 | Out-Null
            } finally {
                Pop-Location
            }
            $after = (Get-FileHash -LiteralPath $oldFixedTemp -Algorithm SHA256).Hash
            $survived = $before -eq $after
            Remove-Item -LiteralPath $oldFixedTemp -Force -ErrorAction SilentlyContinue
            $survived
        }
    }
} finally {
    if (Test-Path -LiteralPath $TestRoot) {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "=== backup_restore_env_secrets_windows.ps1 verification harness ==="
$failCount = 0
foreach ($r in $results) {
    if ($r.Pass) {
        Write-Host ("PASS  " + $r.Name)
    } else {
        $failCount++
        Write-Host ("FAIL  " + $r.Name + "  -- " + $r.Detail) -ForegroundColor Red
    }
}
Write-Host ""
Write-Host ("Total: {0} passed, {1} failed (of {2})" -f ($results.Count - $failCount), $failCount, $results.Count)

if ($failCount -gt 0) {
    exit 1
}
exit 0
