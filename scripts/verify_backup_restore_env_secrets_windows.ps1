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
# directory when it finishes. It never writes to, or reads a real
# secret from, the repository's own .env file.
#
# Independent audit follow-up V3 (PR #365, Work comment 6397370183):
# an earlier revision of this harness had four real quality gaps this
# round fixes: (1) junction-creation checks trusted `cmd /c mklink`
# blindly, so a failed mklink and a genuinely-rejected BackupPath were
# indistinguishable -- both were just "an exception was thrown" to the
# same try/catch; (2) the owner-only-ACL check only counted access
# rules (`Access.Count -eq 1`), never verifying the one rule was
# actually Allow/FullControl/non-inherited/for the current identity;
# (3) a SKIP path returned $true, which Invoke-Check counted as a PASS
# -- indistinguishable in the summary from a real pass; (4) the Gemini
# check ran verify_gemini_env_key_windows.ps1 against the REAL
# repository checkout, which requires a real .env there and reads it
# through the real settings loader, directly contradicting this
# harness's own "never touches a real secret" claim and making the
# check's outcome depend on whatever .env happens to already be on the
# machine running it. All four are fixed below.
#
# Usage: powershell.exe -File scripts\verify_backup_restore_env_secrets_windows.ps1
# Exit code 0 = every check passed (or was explicitly skipped with a
# stated reason). Non-zero = at least one check failed; the failing
# check names are printed to stderr as well as stdout. SKIP is never
# counted toward "passed".

Set-StrictMode -Off
$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$BackupRestoreScript = Join-Path $RepoRoot "backup_restore_env_secrets_windows.ps1"
$VerifyGeminiScript = Join-Path $RepoRoot "verify_gemini_env_key_windows.ps1"

if (-not (Test-Path -LiteralPath $BackupRestoreScript -PathType Leaf)) {
    throw "BLOCKED: $BackupRestoreScript not found."
}

. $BackupRestoreScript

if (-not ("EnvSecretsVerifyHarness.MoveRaceHelper" -as [type])) {
    # Work's follow-up on PR #365 comment 6397370183 asked how to make
    # the concurrency race actually fire, rather than leave it a
    # best-effort probe that SKIPs whenever an out-of-process racer
    # (Start-Job, a whole new PowerShell host) is too slow to start
    # before the tiny operation it is racing against already finished
    # -- which is what happens every time on this machine (see the
    # Start-Job-based check below). A pure .NET race, run entirely
    # in-process via System.Threading.Tasks.Task (microsecond startup,
    # no new process or PowerShell runspace needed), reliably fires:
    # launching N truly concurrent attempts at the exact same
    # unforced File.Move proves, deterministically and repeatably,
    # the one OS-level guarantee Backup-EnvSecrets' and Restore-
    # EnvSecrets' default (non--Force) final move both depend on --
    # that the rename is a single atomic filesystem operation (Win32
    # MoveFileEx without MOVEFILE_REPLACE_EXISTING), never a separate
    # check-then-act two .NET could let two callers interleave.
    #
    # Codex follow-up (PR #365 comment 4370910725, P2): Task.Run alone
    # does not guarantee simultaneous start. On a cold/constrained
    # thread pool, the first task can finish its whole Move before a
    # second contender has even begun running, so every "loser" fails
    # sequentially against an already-existing destination -- the
    # assertions would still pass, but concurrent contention would
    # never actually have happened. RunRace now raises the thread
    # pool's minimum worker count to accommodate every contender
    # without the pool's gradual ramp-up delay, then uses a
    # CountdownEvent so every contender signals it has actually
    # started and is blocked immediately before the move, and a
    # ManualResetEventSlim that releases all of them in the same
    # instant only once every one of them has reached that point --
    # never fewer. AllContendersReady in the result reports whether
    # that readiness handshake itself completed (it must, for the
    # proof to mean anything); the PowerShell check below treats a
    # readiness failure as a hard FAIL, not a silent pass.
    Add-Type -Namespace EnvSecretsVerifyHarness -Name MoveRaceHelper -MemberDefinition @'
public class MoveRaceResult {
    public int SuccessCount;
    public bool DestExists;
    public string DestContent;
    public bool AllContendersReady;
}

public static System.Object RunRace(string[] sources, string destination) {
    int n = sources.Length;
    int workerThreads, completionThreads;
    System.Threading.ThreadPool.GetMinThreads(out workerThreads, out completionThreads);
    System.Threading.ThreadPool.SetMinThreads(System.Math.Max(workerThreads, n + 4), completionThreads);

    int successCount = 0;
    object lockObj = new object();
    System.Threading.CountdownEvent readyGate = new System.Threading.CountdownEvent(n);
    System.Threading.ManualResetEventSlim startGate = new System.Threading.ManualResetEventSlim(false);
    System.Threading.Tasks.Task[] tasks = new System.Threading.Tasks.Task[n];
    for (int i = 0; i < n; i++) {
        string src = sources[i];
        tasks[i] = System.Threading.Tasks.Task.Run(() => {
            readyGate.Signal();
            startGate.Wait();
            try {
                System.IO.File.Move(src, destination);
                lock (lockObj) { successCount++; }
            } catch {
                // Expected for every losing attempt.
            }
        });
    }
    bool allReady = readyGate.Wait(System.TimeSpan.FromSeconds(10));
    startGate.Set();
    System.Threading.Tasks.Task.WaitAll(tasks);

    var result = new MoveRaceResult();
    result.SuccessCount = successCount;
    result.DestExists = System.IO.File.Exists(destination);
    if (result.DestExists) {
        result.DestContent = System.IO.File.ReadAllText(destination);
    }
    result.AllContendersReady = allReady;
    return result;
}
'@
}

$results = New-Object System.Collections.Generic.List[object]

function Invoke-Check {
    # Status is one of PASS / FAIL / SKIP. A scriptblock that returns
    # the exact string "SKIP" is recorded as SKIP (never counted as a
    # pass); returning $false or throwing is FAIL; anything else is
    # PASS. Keeping SKIP a distinct status (independent audit V3,
    # Work comment 6397370183) is the point: an earlier revision had a
    # skip path return $true, making a genuinely-skipped check
    # indistinguishable from a real pass in the summary totals.
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][scriptblock]$Body
    )
    try {
        $outcome = & $Body
        if ($outcome -is [string] -and $outcome -eq "SKIP") {
            $results.Add([pscustomobject]@{ Name = $Name; Status = "SKIP"; Detail = "" })
        } elseif ($outcome -eq $false) {
            $results.Add([pscustomobject]@{ Name = $Name; Status = "FAIL"; Detail = "assertion returned false" })
        } else {
            $results.Add([pscustomobject]@{ Name = $Name; Status = "PASS"; Detail = "" })
        }
    } catch {
        $results.Add([pscustomobject]@{ Name = $Name; Status = "FAIL"; Detail = $_.Exception.Message })
    }
}

function New-VerifiedJunction {
    # Independent audit follow-up V3 (PR #365, Work comment
    # 6397370183): an earlier revision called `cmd /c mklink /J`
    # directly inside each check's own try/catch, so a FAILED mklink
    # (wrong privilege, bad path, anything) and Backup-EnvSecrets
    # correctly REJECTING the resulting path were both just "an
    # exception happened" to the same catch block -- indistinguishable
    # successes. This helper is called OUTSIDE that inner try/catch in
    # every check that needs a junction: it verifies mklink's own exit
    # code AND that the resulting item genuinely carries the
    # ReparsePoint attribute, and throws (a prerequisite failure,
    # reported by Invoke-Check as its own FAIL, never confused with an
    # expected safety rejection) if either check fails.
    param(
        [Parameter(Mandatory = $true)][string]$Junction,
        [Parameter(Mandatory = $true)][string]$Target
    )
    if (Test-Path -LiteralPath $Junction) {
        cmd /c rmdir "$Junction" | Out-Null
    }
    cmd /c mklink /J "$Junction" "$Target" | Out-Null
    if ($LASTEXITCODE -ne 0) {
        throw "PREREQUISITE FAILED: mklink /J exited $LASTEXITCODE creating junction '$Junction' -> '$Target'"
    }
    if (-not (Test-Path -LiteralPath $Junction)) {
        throw "PREREQUISITE FAILED: '$Junction' does not exist immediately after mklink reported success"
    }
    $item = Get-Item -LiteralPath $Junction -Force
    if (-not ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
        throw "PREREQUISITE FAILED: '$Junction' was created but is not a reparse point -- mklink /J did not actually produce a junction"
    }
}

function Test-IsPrivateOwnerOnlyAcl {
    # Independent audit follow-up V3 (PR #365, Work comment
    # 6397370183): an earlier revision only checked
    # `(Get-Acl ...).Access.Count -eq 1` -- true for exactly one rule
    # of ANY kind, including e.g. a stray Deny rule or a rule for the
    # wrong identity. This verifies the one rule actually is what
    # Set-PrivateFileAcl is supposed to produce: Allow, FullControl,
    # not inherited, and for the current Windows identity specifically.
    param([Parameter(Mandatory = $true)][string]$Path)
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $rules = @((Get-Acl -LiteralPath $Path).Access)
    if ($rules.Count -ne 1) { return $false }
    $rule = $rules[0]
    if ($rule.IsInherited) { return $false }
    if ($rule.AccessControlType -ne [System.Security.AccessControl.AccessControlType]::Allow) { return $false }
    if ($rule.FileSystemRights -ne [System.Security.AccessControl.FileSystemRights]::FullControl) { return $false }
    try {
        $ruleSid = $rule.IdentityReference.Translate([System.Security.Principal.SecurityIdentifier])
    } catch {
        return $false
    }
    return $ruleSid -eq $identity
}

function Add-DenyWriteAcl {
    # Injects a real, OS-enforced Deny rule for the current identity on
    # $Path (CreateFiles/Write/Delete/WriteData), used to force a
    # genuine failure inside the real Backup-EnvSecrets/Restore-
    # EnvSecrets functions (independent audit V3, Work comment
    # 6397370183, point 1: no existing check exercised an actual
    # ACL/move failure path through the real functions, only the bare
    # Move-Item primitive in isolation).
    param([Parameter(Mandatory = $true)][string]$Path)
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = Get-Acl -LiteralPath $Path
    $denyRule = New-Object System.Security.AccessControl.FileSystemAccessRule(
        $identity,
        ([System.Security.AccessControl.FileSystemRights]"CreateFiles,Write,Delete,WriteData"),
        [System.Security.AccessControl.AccessControlType]::Deny
    )
    $acl.AddAccessRule($denyRule)
    Set-Acl -LiteralPath $Path -AclObject $acl
}

function Remove-DenyWriteAcl {
    # Cleanup counterpart to Add-DenyWriteAcl. Must run before this
    # harness's own final recursive delete of $TestRoot, or that
    # delete would fail against the very Deny rule this function
    # removes.
    param([Parameter(Mandatory = $true)][string]$Path)
    $identity = [System.Security.Principal.WindowsIdentity]::GetCurrent().User
    $acl = Get-Acl -LiteralPath $Path
    foreach ($rule in @($acl.Access)) {
        if ($rule.AccessControlType -eq [System.Security.AccessControl.AccessControlType]::Deny) {
            $acl.RemoveAccessRule($rule) | Out-Null
        }
    }
    Set-Acl -LiteralPath $Path -AclObject $acl
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

    Invoke-Check "restored_file_has_owner_only_full_control_acl" {
        Test-IsPrivateOwnerOnlyAcl -Path $Restored
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
        New-VerifiedJunction -Junction $junction -Target $realDir
        $target = Join-Path $junction "via-junction.backup"
        $rejected = $false
        try { Backup-EnvSecrets -SourcePath $Source -BackupPath $target } catch { $rejected = $true }
        $rejected
    }

    Invoke-Check "backup_rejects_junction_one_level_above_immediate_parent" {
        $realDir = Join-Path $TestRoot "realtarget2"
        New-Item -ItemType Directory -Path $realDir -Force | Out-Null
        $junction = Join-Path $TestRoot "junction2"
        New-VerifiedJunction -Junction $junction -Target $realDir
        $target = Join-Path $junction "sub\env.backup"
        $rejected = $false
        try { Backup-EnvSecrets -SourcePath $Source -BackupPath $target } catch { $rejected = $true }
        $rejected
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

    Invoke-Check "backup_rejects_refreshing_an_existing_backup_slot_without_force" {
        # Work independent audit, PR #365 comment 6395349716, final
        # round: an earlier revision let a real backup slot (one this
        # tool itself had produced) be refreshed without -Force, based
        # on a heuristic that decrypted successfully for ANY DPAPI blob
        # under the current user+machine -- not proof the file was
        # actually one of this tool's own prior backups. That heuristic
        # is now removed entirely: refreshing ANY existing BackupPath,
        # including one this tool produced moments earlier, requires
        # explicit -Force, exactly like Restore-EnvSecrets already
        # requires for DestinationPath.
        $slot = Join-Path $TestRoot "refresh_slot.backup"
        Backup-EnvSecrets -SourcePath $Source -BackupPath $slot
        $rejected = $false
        try { Backup-EnvSecrets -SourcePath $Source -BackupPath $slot } catch { $rejected = $true }
        $rejected -and (Test-Path -LiteralPath $slot)
    }

    Invoke-Check "backup_force_refreshes_an_existing_backup_slot" {
        $slot = Join-Path $TestRoot "refresh_slot_force.backup"
        Backup-EnvSecrets -SourcePath $Source -BackupPath $slot
        Start-Sleep -Milliseconds 50
        Backup-EnvSecrets -SourcePath $Source -BackupPath $slot -Force
        Test-Path -LiteralPath $slot
    }

    Invoke-Check "backup_force_overwrites_an_unrelated_existing_file_when_explicitly_requested" {
        $unrelated = Join-Path $TestRoot "force_overwrite_target.env"
        "IMPORTANT_UNRELATED_USER_DATA_2" | Set-Content -LiteralPath $unrelated -Encoding utf8 -NoNewline
        Backup-EnvSecrets -SourcePath $Source -BackupPath $unrelated -Force
        (Get-Content -LiteralPath $unrelated -Raw) -ne "IMPORTANT_UNRELATED_USER_DATA_2"
    }

    Invoke-Check "backup_fails_closed_when_the_backup_directory_denies_write" {
        # Independent audit follow-up V3 (PR #365, Work comment
        # 6397370183, point 1): no prior check exercised a genuine
        # ACL/move failure through the REAL Backup-EnvSecrets function
        # (only the bare Move-Item primitive, in isolation, was
        # checked). This injects a real, OS-enforced Deny rule on the
        # backup directory so the function's own temp-file creation
        # genuinely fails, and verifies it fails closed: an existing
        # backup at that path is left byte-for-byte intact, and no
        # stray temp file is left behind.
        $denyDir = Join-Path $TestRoot "deny_write_backup_dir"
        New-Item -ItemType Directory -Path $denyDir -Force | Out-Null
        $slot = Join-Path $denyDir "slot.backup"
        Backup-EnvSecrets -SourcePath $Source -BackupPath $slot -Force
        $beforeHash = (Get-FileHash -LiteralPath $slot -Algorithm SHA256).Hash
        Add-DenyWriteAcl -Path $denyDir
        $threw = $false
        try {
            Backup-EnvSecrets -SourcePath $Source -BackupPath $slot -Force
        } catch {
            $threw = $true
        } finally {
            Remove-DenyWriteAcl -Path $denyDir
        }
        $afterHash = (Get-FileHash -LiteralPath $slot -Algorithm SHA256).Hash
        $noLeftoverTemp = -not (Get-ChildItem -LiteralPath $denyDir -Filter ".envsecrets-*" -Force -ErrorAction SilentlyContinue)
        $threw -and ($beforeHash -eq $afterHash) -and $noLeftoverTemp
    }

    Invoke-Check "restore_fails_closed_when_the_destination_directory_denies_write" {
        # Restore-EnvSecrets counterpart to the check above.
        $denyDir = Join-Path $TestRoot "deny_write_restore_dir"
        New-Item -ItemType Directory -Path $denyDir -Force | Out-Null
        $dest = Join-Path $denyDir "restored_denied.env"
        Add-DenyWriteAcl -Path $denyDir
        $threw = $false
        try {
            Restore-EnvSecrets -BackupPath $Backup -DestinationPath $dest
        } catch {
            $threw = $true
        } finally {
            Remove-DenyWriteAcl -Path $denyDir
        }
        $noPartialOutput = -not (Test-Path -LiteralPath $dest)
        $noLeftoverTemp = -not (Get-ChildItem -LiteralPath $denyDir -Filter ".envsecrets-*" -Force -ErrorAction SilentlyContinue)
        $threw -and $noPartialOutput -and $noLeftoverTemp
    }

    Invoke-Check "backup_default_move_never_corrupts_destination_under_concurrent_creation" {
        # Independent audit follow-up V3 (PR #365, Work comment
        # 6397370183, point 1): best-effort concurrency probe against
        # the REAL Backup-EnvSecrets function (not just the Move-Item
        # primitive in isolation). A background job races to create
        # BackupPath the instant it sees this function's own exclusive
        # temp file appear -- i.e. as close to the final Move-Item as
        # this harness can get from outside the function -- over
        # several attempts. Who wins a given attempt is inherently
        # nondeterministic, so this does not assert a specific winner;
        # it asserts the safety property that must hold regardless:
        # the destination is never left truncated, partial, or
        # garbled, only ever the racer's untouched sentinel content or
        # this tool's own valid, fully-written ciphertext.
        #
        # Codex follow-up (PR #365 comment 4370837902): the previous
        # revision started the background job and immediately called
        # Backup-EnvSecrets with no handshake, so on a machine where
        # Start-Job's own process-spawn latency exceeds how long the
        # whole backup takes, the job could start polling only AFTER
        # Backup-EnvSecrets had already finished -- never observing
        # the temp file, never writing its sentinel, and every attempt
        # would then "pass" without the race ever actually happening.
        # This now (a) makes the main thread wait for the job to
        # signal it is alive and about to enter its poll loop before
        # calling Backup-EnvSecrets, narrowing that gap, and (b) has
        # each job report back whether it actually wrote its sentinel;
        # if not even one of the attempts genuinely raced, this
        # reports SKIP rather than a PASS that proved nothing.
        $raceDir = Join-Path $TestRoot "race_dir"
        New-Item -ItemType Directory -Path $raceDir -Force | Out-Null
        $allClean = $true
        $raceAttempts = 6
        $participatedCount = 0
        for ($i = 0; $i -lt $raceAttempts; $i++) {
            $slot = Join-Path $raceDir ("race_slot_" + $i + ".backup")
            $sentinel = "RACER_SENTINEL_$i"
            $readyFlag = Join-Path $raceDir ("ready_" + $i + ".flag")
            $job = Start-Job -ScriptBlock {
                param($dir, $path, $content, $readyFlag)
                New-Item -ItemType File -Path $readyFlag -Force | Out-Null
                $deadline = (Get-Date).AddSeconds(3)
                while ((Get-Date) -lt $deadline) {
                    $tempFound = Get-ChildItem -LiteralPath $dir -Filter ".envsecrets-*" -Force -ErrorAction SilentlyContinue
                    if ($tempFound) {
                        Set-Content -LiteralPath $path -Value $content -Encoding utf8 -NoNewline -ErrorAction SilentlyContinue
                        return $true
                    }
                }
                return $false
            } -ArgumentList $raceDir, $slot, $sentinel, $readyFlag
            $readyDeadline = (Get-Date).AddSeconds(10)
            while (-not (Test-Path -LiteralPath $readyFlag) -and (Get-Date) -lt $readyDeadline) {
                Start-Sleep -Milliseconds 5
            }
            Remove-Item -LiteralPath $readyFlag -Force -ErrorAction SilentlyContinue
            try {
                Backup-EnvSecrets -SourcePath $Source -BackupPath $slot
            } catch {
                # Expected outcome when the racer creates $slot first.
            }
            Wait-Job $job -Timeout 5 | Out-Null
            $racerWrote = $false
            $jobOutput = Receive-Job $job -ErrorAction SilentlyContinue
            if ($jobOutput -is [array]) {
                if ($jobOutput[-1] -eq $true) { $racerWrote = $true }
            } elseif ($jobOutput -eq $true) {
                $racerWrote = $true
            }
            Remove-Job $job -Force -ErrorAction SilentlyContinue
            if ($racerWrote) { $participatedCount++ }
            if (Test-Path -LiteralPath $slot -PathType Leaf) {
                $content = Get-Content -LiteralPath $slot -Raw
                $isSentinel = $content -eq $sentinel
                $isValidBackup = $false
                if (-not $isSentinel) {
                    try {
                        $secure = ConvertTo-SecureString -String $content -ErrorAction Stop
                        $bstr = [System.Runtime.InteropServices.Marshal]::SecureStringToBSTR($secure)
                        [System.Runtime.InteropServices.Marshal]::ZeroFreeBSTR($bstr)
                        $isValidBackup = $true
                    } catch {
                        $isValidBackup = $false
                    }
                }
                if (-not ($isSentinel -or $isValidBackup)) {
                    $allClean = $false
                }
            }
        }
        if (-not $allClean) {
            $false
        } elseif ($participatedCount -eq 0) {
            Write-Host ("SKIP  backup_default_move_never_corrupts_destination_under_concurrent_creation -- the racer never observed the temp file in time across {0} attempts on this machine; the race was never actually exercised" -f $raceAttempts)
            "SKIP"
        } else {
            $true
        }
    }

    Invoke-Check "move_item_without_force_is_atomic_under_true_concurrent_contention" {
        # Work's own follow-up question on the check above ("どうすれば
        # 競合試験を確実に発生させられるか" -- how to make the race
        # actually fire): an out-of-process racer (Start-Job) can be
        # too slow to even start before the whole operation it is
        # racing against has already finished, which is exactly why
        # the check above SKIPs on this machine. This check instead
        # launches many truly concurrent attempts AT THE SAME unforced
        # Move-Item/File.Move, entirely in-process via .NET Tasks
        # (microsecond startup, no new process), which reliably DOES
        # fire the race every run. It directly proves the one OS-level
        # guarantee Backup-EnvSecrets' and Restore-EnvSecrets' default
        # (non--Force) final move both depend on: the rename is a
        # single atomic filesystem operation -- exactly one concurrent
        # attempt ever succeeds, and the destination is always one
        # complete, uncorrupted attempt's content, never a mix of two.
        # This complements, rather than replaces, the check above: that
        # one probes the real Backup-EnvSecrets function end to end
        # (and is honest about not having fired here); this one proves
        # the specific primitive both functions' safety reduces to.
        $moveRaceDir = Join-Path $TestRoot "move_atomicity_race"
        New-Item -ItemType Directory -Path $moveRaceDir -Force | Out-Null
        $moveRaceDest = Join-Path $moveRaceDir "contended_destination.txt"
        $moveRaceAttempts = 30
        $allTrialsClean = $true
        $anyTrialHadExactlyOneWinner = $true
        $allTrialsHadEveryContenderReady = $true
        for ($trial = 0; $trial -lt 5; $trial++) {
            if (Test-Path -LiteralPath $moveRaceDest) { Remove-Item -LiteralPath $moveRaceDest -Force }
            $sourcePaths = New-Object string[] $moveRaceAttempts
            for ($i = 0; $i -lt $moveRaceAttempts; $i++) {
                $p = Join-Path $moveRaceDir ("contender_" + $trial + "_" + $i + ".txt")
                [System.IO.File]::WriteAllText($p, ("ATTEMPT_CONTENT_" + $trial + "_" + $i))
                $sourcePaths[$i] = $p
            }
            $raceResult = [EnvSecretsVerifyHarness.MoveRaceHelper]::RunRace($sourcePaths, $moveRaceDest)
            if (-not $raceResult.AllContendersReady) { $allTrialsHadEveryContenderReady = $false }
            if ($raceResult.SuccessCount -ne 1) { $anyTrialHadExactlyOneWinner = $false }
            if ($raceResult.DestExists) {
                $matchesOneCompleteAttempt = $false
                for ($i = 0; $i -lt $moveRaceAttempts; $i++) {
                    if ($raceResult.DestContent -eq ("ATTEMPT_CONTENT_" + $trial + "_" + $i)) {
                        $matchesOneCompleteAttempt = $true
                        break
                    }
                }
                if (-not $matchesOneCompleteAttempt) { $allTrialsClean = $false }
            } else {
                $allTrialsClean = $false
            }
        }
        $allTrialsClean -and $anyTrialHadExactlyOneWinner -and $allTrialsHadEveryContenderReady
    }

    if (Test-Path -LiteralPath $VerifyGeminiScript -PathType Leaf) {
        $dummyRepoSrc = Join-Path $RepoRoot "src"
        $dummyRepoVenv = Join-Path $RepoRoot ".venv"
        if ((Test-Path -LiteralPath $dummyRepoSrc -PathType Container) -and (Test-Path -LiteralPath $dummyRepoVenv -PathType Container)) {
            Invoke-Check "verify_gemini_env_key_isolated_dummy_repo_leaves_unrelated_file_untouched" {
                # Independent audit follow-up V3 (PR #365, Work comment
                # 6397370183, point 4): an earlier revision ran
                # verify_gemini_env_key_windows.ps1 against the REAL
                # repository checkout, which requires a real .env there
                # and reads it through the real settings loader --
                # contradicting this harness's own "never touches a
                # real secret" claim and making the outcome depend on
                # whatever .env happens to already exist on the machine
                # running it. This isolates the same check into a
                # disposable dummy repo under $TestRoot: its own
                # placeholder .env this harness fully owns, with src/
                # and .venv LINKED (junctioned, not copied) from the
                # real checkout via $env:IBKR_REPO_DIR, so the genuine
                # production settings-loader code still runs end to
                # end, just against a .env this harness created and
                # disposes of, never the repository's real one.
                # load_ai_settings() checks
                # Path.cwd()/".env" BEFORE the project-root fallback
                # (src/ai_asset_platform/ai/settings.py), so the dummy
                # .env is found first and the real one is never reached.
                $dummyRepo = Join-Path $TestRoot "dummy_gemini_repo"
                New-Item -ItemType Directory -Path $dummyRepo -Force | Out-Null
                New-VerifiedJunction -Junction (Join-Path $dummyRepo "src") -Target $dummyRepoSrc
                New-VerifiedJunction -Junction (Join-Path $dummyRepo ".venv") -Target $dummyRepoVenv
                "GEMINI_API_KEY=dummy-harness-placeholder`nGEMINI_MODEL=gemini-dummy-harness-model" |
                    Set-Content -LiteralPath (Join-Path $dummyRepo ".env") -Encoding utf8 -NoNewline
                $oldFixedTemp = Join-Path $dummyRepo "_verify_gemini_env_key_tmp.py"
                "UNRELATED_PY_CONTENT" | Set-Content -LiteralPath $oldFixedTemp -Encoding utf8 -NoNewline
                $before = (Get-FileHash -LiteralPath $oldFixedTemp -Algorithm SHA256).Hash
                $env:IBKR_REPO_DIR = $dummyRepo
                try {
                    & $VerifyGeminiScript 2>&1 | Out-Null
                } finally {
                    Remove-Item Env:\IBKR_REPO_DIR -ErrorAction SilentlyContinue
                }
                $after = (Get-FileHash -LiteralPath $oldFixedTemp -Algorithm SHA256).Hash
                $before -eq $after
            }
        } else {
            Invoke-Check "verify_gemini_env_key_isolated_dummy_repo_leaves_unrelated_file_untouched" {
                "SKIP"
            }
        }
    }
} finally {
    if (Test-Path -LiteralPath $TestRoot) {
        Remove-Item -LiteralPath $TestRoot -Recurse -Force -ErrorAction SilentlyContinue
    }
}

Write-Host ""
Write-Host "=== backup_restore_env_secrets_windows.ps1 verification harness ==="
Write-Host ("PowerShell version: {0}" -f $PSVersionTable.PSVersion.ToString())
$passCount = @($results | Where-Object { $_.Status -eq "PASS" }).Count
$failCount = @($results | Where-Object { $_.Status -eq "FAIL" }).Count
$skipCount = @($results | Where-Object { $_.Status -eq "SKIP" }).Count
foreach ($r in $results) {
    switch ($r.Status) {
        "PASS" { Write-Host ("PASS  " + $r.Name) }
        "SKIP" { Write-Host ("SKIP  " + $r.Name) }
        "FAIL" { Write-Host ("FAIL  " + $r.Name + "  -- " + $r.Detail) -ForegroundColor Red }
    }
}
Write-Host ""
Write-Host ("Total: {0} passed, {1} failed, {2} skipped (of {3})" -f $passCount, $failCount, $skipCount, $results.Count)

if ($failCount -gt 0) {
    exit 1
}
exit 0
