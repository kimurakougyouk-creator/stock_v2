from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
import uuid

import pytest


AUTOPILOT = Path("ibkr_paper_signal_runner_autopilot_windows.ps1")
INSTALLER = Path("install_ibkr_paper_signal_runner_autopilot_windows.ps1")


def _text(path: Path) -> str:
    assert path.exists(), f"missing required file: {path}"
    return path.read_text(encoding="utf-8")


def test_pyc_cleanup_never_uses_literalpath_include_bug_pattern():
    # -Include is silently ignored when combined with -LiteralPath in
    # Windows PowerShell 5.1: Get-ChildItem -LiteralPath $dir -Recurse
    # -Include "*.pyc" enumerates (and the following Remove-Item -Force
    # then attempts to delete) every file AND directory under $dir,
    # including .venv/src/tests. PR #364's -File + extension-check fix
    # closed that specific enumeration bug, but the design still handed a
    # repo-root-rooted recursive scan to Remove-Item. The 2026-10-25
    # incident redesign (this test) replaces that entirely: neither script
    # may pass $RepoDir to any recursive Get-ChildItem/Remove-Item call at
    # all. Cleanup instead asks git -- restricted to the same fixed, narrow
    # path set the Windows source-SHA attestation audits -- which untracked
    # files/directories are ignored-and-present, and deletes only those.
    for script in (_text(AUTOPILOT), _text(INSTALLER)):
        assert '-Include "*.pyc"' not in script
        assert 'Remove-Item -LiteralPath $RepoDir -Recurse' not in script
        assert "git -C $RepoDir ls-files --others --ignored --exclude-standard --directory" in script
        assert '":(top,glob)__pycache__"' in script
        assert '":(top,glob)*.pyc"' in script
        assert '":(top,glob)*.pyo"' in script
        assert "ReparsePoint" in script


def test_pyc_cleanup_never_deletes_by_path_prefix_alone():
    # Codex P1 (PR #365 review comment 4369141645): the git pathspec `--
    # src tests ...` matches by directory PREFIX, so git can hand back any
    # ignored-and-untracked path under src/ or tests/ -- not only cache
    # files -- e.g. a stray secret, image, or backup directory that
    # happens to be gitignored. Each candidate must be independently
    # re-validated by its own name/suffix (literally ".pyc"/".pyo", or a
    # directory literally named "__pycache__"), never accepted merely
    # because it lives under the allowed src/tests prefix.
    for script in (_text(AUTOPILOT), _text(INSTALLER)):
        assert "$isBytecode" in script
        assert "$isCacheDir" in script
        assert "'(^|/)__pycache__$'" in script
        assert "if (-not ($isBytecode -or $isCacheDir)) { continue }" in script


def test_pyc_cleanup_only_recurse_deletes_a_pycache_dir_whose_entire_contents_are_bytecode():
    # A __pycache__-named directory is only ever recursively removed after
    # its full contents are independently verified to be nothing but
    # .pyc/.pyo files with no reparse points anywhere inside -- so a file
    # planted inside a real __pycache__ directory (e.g. a secret dropped
    # there by mistake or by an adversary) blocks deletion of the whole
    # directory, rather than being silently destroyed alongside real cache
    # files. This also means the recursive Get-ChildItem/Remove-Item here
    # never leaves the single, already-narrowed __pycache__ directory that
    # was already matched by the git-restricted allowlist above.
    for script in (_text(AUTOPILOT), _text(INSTALLER)):
        assert "if (-not $isCacheDir) { continue }" in script
        assert "$onlyCacheContents" in script
        assert "Get-ChildItem -LiteralPath $full -Recurse -Force -ErrorAction Stop" in script
        assert '$descendant.Extension -ne ".pyc" -and $descendant.Extension -ne ".pyo"' in script
        assert "Remove-Item -LiteralPath $full -Recurse -Force -ErrorAction Stop" in script


def test_windows_autopilot_only_invokes_paper_trading_runner_and_market_session_check():
    script = _text(AUTOPILOT)
    assert "-m paper_trading_runner" in script
    assert "-m signal_runner" not in script
    assert "evaluate_verified_market_session" in script
    assert "placeOrder(" not in script
    assert "ibkr_auto_close_cycle" not in script
    assert "ibkr_overnight_e2e" not in script
    assert "YES_CLOSE_ONE_SPY_PAPER" not in script
    assert "ibkr_verified_paper_runtime" not in script
    assert '"LIVE ORDER SENT: False"' in script


def test_windows_autopilot_never_enables_or_touches_live_trading():
    script = _text(AUTOPILOT)
    assert "AI_ASSET_ENABLE_LIVE_TRADING" in script
    assert "AI_ASSET_LIVE_TRADING_UNLOCKED" in script
    # Both Live flag names only ever appear in the defensive refuse-to-run
    # guard and the always-False log line, never assigned a truthy value.
    assert '$env:AI_ASSET_ENABLE_LIVE_TRADING = "1"' not in script
    assert '$env:AI_ASSET_LIVE_TRADING_UNLOCKED = "1"' not in script
    assert 'if ($env:AI_ASSET_ENABLE_LIVE_TRADING -or $env:AI_ASSET_LIVE_TRADING_UNLOCKED)' in script


def test_windows_autopilot_explicitly_opts_into_paper_only():
    script = _text(AUTOPILOT)
    assert '$env:AI_ASSET_ENABLE_IBKR_PAPER = "1"' in script


def test_windows_autopilot_never_updates_remote_source_unattended():
    script = _text(AUTOPILOT)
    lower = script.lower()
    assert "git pull" not in lower
    assert "git fetch" not in lower
    assert "git switch" not in lower
    assert "git checkout" not in lower
    assert "$PinnedHead" in script
    assert "AUTOPILOT SOURCE BLOCKED" in script


def test_windows_autopilot_requires_main_pin_and_clean_source_before_runner():
    script = _text(AUTOPILOT)
    branch_at = script.index('$currentBranch = Get-GitSingleLine')
    head_at = script.index('$currentHead = Get-GitSingleLine')
    branch_block_at = script.index('if ($currentBranch -ne "main")')
    head_block_at = script.index('elseif ($currentHead -ne $PinnedHead)')
    clean_block_at = script.index('elseif (-not (Test-TrackedSourceClean))')
    runner_at = script.index('-m paper_trading_runner')
    assert branch_at < branch_block_at < runner_at
    assert head_at < head_block_at < runner_at
    assert clean_block_at < runner_at
    assert "git diff --quiet HEAD -- . ':(exclude)results/**' ':(exclude)data/**'" in script
    assert "git diff --cached --quiet HEAD -- . ':(exclude)results/**' ':(exclude)data/**'" in script


def test_windows_autopilot_skips_runner_when_all_verified_tickers_closed():
    script = _text(AUTOPILOT)
    session_check_at = script.index("evaluate_verified_market_session")
    market_open_at = script.index("$marketOpen = ")
    skip_at = script.index('"VERIFIED TICKER MARKET SESSION CLOSED')
    runner_at = script.index('-m paper_trading_runner')
    assert session_check_at < market_open_at < skip_at < runner_at


def test_windows_autopilot_uses_windows_venv_and_bounded_loop():
    script = _text(AUTOPILOT)
    assert '.venv\\Scripts\\python.exe' in script
    assert "$IntervalSeconds -lt 30 -or $IntervalSeconds -gt 86400" in script
    assert "$MaxLogBytes -lt 1048576 -or $MaxLogBytes -gt 104857600" in script
    assert "Start-Sleep -Seconds $IntervalSeconds" in script
    assert "$RotatedLogFile" in script
    assert "Rotate-AutopilotLogIfNeeded" in script


def test_windows_autopilot_reads_persisted_deadline_and_never_writes_it():
    script = _text(AUTOPILOT)
    assert "$DeadlineFile" in script
    assert "Get-ApprovalDeadlineUtc" in script
    assert "AUTOPILOT EXPIRED" in script
    assert "fresh explicit approval" in script
    assert "break" in script
    # The autopilot script must never create or extend the deadline file
    # itself (only Set-PrivatePinFile -Path $PinFile, never
    # -Path $DeadlineFile) -- otherwise a restart could silently renew its
    # own approval window.
    assert "Set-PrivatePinFile -Path $DeadlineFile" not in script
    # Refuses to start at all if the installer never staged a deadline.
    deadline_missing_check_at = script.index(
        'if (-not (Test-Path -LiteralPath $DeadlineFile -PathType Leaf))'
    )
    loop_at = script.index("while ($true)")
    assert deadline_missing_check_at < loop_at


def test_windows_autopilot_self_disables_task_on_expiry_with_evidence():
    # Work independent audit (PR #369, comment
    # WORK_PAPER_PREP_SCOPE_CORRECTION_V1, 2026-10-27): the previous
    # self-disable was `try { Disable-ScheduledTask ... -ErrorAction
    # SilentlyContinue | Out-Null } catch {}` -- a failed disable call was
    # indistinguishable from a successful one in the log. Replaced with a
    # helper that always records whether the call itself threw and whether
    # the task's state reads back as Disabled afterward. This supersedes
    # the previous (now removed) test_windows_autopilot_self_disables_
    # task_on_expiry, which asserted ordering against the raw
    # Disable-ScheduledTask call directly; that literal now lives inside
    # this helper's definition (checked separately below) rather than at
    # each loop call site.
    script = _text(AUTOPILOT)
    assert "function Disable-AutopilotTaskWithEvidence" in script
    assert "Disable-ScheduledTask -TaskName $TaskName -ErrorAction Stop" in script
    assert "Get-ScheduledTask -TaskName $TaskName -ErrorAction Stop" in script
    assert "AUTOPILOT CRITICAL" in script
    assert "AUTOPILOT PROCESS EXITING" in script

    expired_at = script.index('"AUTOPILOT EXPIRED: approval deadline')
    call_at = script.index("Disable-AutopilotTaskWithEvidence", expired_at)
    break_at = script.index("break", call_at)
    assert expired_at < call_at < break_at


def test_windows_autopilot_rechecks_deadline_immediately_before_runner_start():
    # Work independent audit (PR #369): the deadline was previously checked
    # only once, at the top of each loop iteration -- before git/cleanup/
    # market-session work that itself takes real time -- so a new
    # paper_trading_runner process could still be launched after the
    # approval deadline had already passed. A second, independent check is
    # now required immediately before the runner is started.
    script = _text(AUTOPILOT)
    market_open_at = script.index("if (-not $marketOpen)")
    recheck_at = script.index(
        "approval deadline $($deadlineUtc.ToString('o')) UTC reached "
        "immediately before runner start"
    )
    recheck_disable_at = script.index(
        "Disable-AutopilotTaskWithEvidence", recheck_at
    )
    runner_start_at = script.index("Start-Process -FilePath $PythonExe")
    assert market_open_at < recheck_at < recheck_disable_at < runner_start_at


def test_windows_autopilot_enforces_deadline_during_inprogress_runner_execution():
    # Work independent audit (PR #369): the runner was previously invoked
    # with a single blocking native call (`& $PythonExe -m
    # paper_trading_runner`) with no bound on its own runtime, so a hang (or
    # just a long run) could keep dispatch alive past the approved deadline
    # with no mechanism to stop it. The runner must now be started
    # asynchronously and polled against the deadline, with a forced kill if
    # the deadline passes while it is still running.
    script = _text(AUTOPILOT)
    assert "function Wait-ProcessWithDeadline" in script
    assert "$Process.Kill()" in script
    assert "-m paper_trading_runner" in script

    start_at = script.index("Start-Process -FilePath $PythonExe")
    wait_at = script.index("Wait-ProcessWithDeadline -Process $runnerProc", start_at)
    enforced_at = script.index('"AUTOPILOT DEADLINE ENFORCED', wait_at)
    disable_at = script.index("Disable-AutopilotTaskWithEvidence", enforced_at)
    break_at = script.index("break", disable_at)
    assert start_at < wait_at < enforced_at < disable_at < break_at


def test_windows_autopilot_distinguishes_confirmed_from_unconfirmed_termination():
    # Work's follow-up independent audit (PR #370, comment
    # WORK_AUDIT_PR370_V1, 2026-10-27): the first version of
    # Wait-ProcessWithDeadline discarded Kill()/WaitForExit() exceptions
    # and WaitForExit's own false (timed out), and unconditionally returned
    # a single boolean the caller logged as "forcibly terminated" success.
    # A process that failed to actually terminate within the wait window
    # was therefore indistinguishable from one that genuinely exited.
    #
    # Work's final limited audit (WORK_FINAL_AUDIT_PR370_V2, 2026-10-27):
    # a confirmed termination may still `break` (a clean, routine stop),
    # but an UNCONFIRMED one must not merely `break` either -- a plain
    # break still lets the script reach its end and exit with code 0,
    # indistinguishable from a routine success to anything checking only
    # the process exit code. The unconfirmed branch must route to
    # Exit-AutopilotCritical (a forced non-zero exit), not a bare break.
    script = _text(AUTOPILOT)
    assert "ConfirmedExited" in script
    assert "$Process.HasExited" in script
    assert "AUTOPILOT CRITICAL" in script
    assert "function Exit-AutopilotCritical" in script
    assert "exit 1" in script

    deadline_reached_at = script.index("if ($deadlineResult.DeadlineReached -and $deadlineResult.ConfirmedExited)")
    confirmed_enforced_at = script.index('"AUTOPILOT DEADLINE ENFORCED', deadline_reached_at)
    confirmed_break_at = script.index("break", confirmed_enforced_at)

    not_confirmed_at = script.index("} elseif ($deadlineResult.DeadlineReached) {", confirmed_break_at)
    critical_at = script.index('"AUTOPILOT CRITICAL: approval deadline was reached', not_confirmed_at)
    critical_exit_at = script.index("Exit-AutopilotCritical", critical_at)

    assert deadline_reached_at < confirmed_enforced_at < confirmed_break_at < not_confirmed_at < critical_at < critical_exit_at
    # Never claim a confirmed termination merely because the normal
    # (not-deadline-reached) exit-code branch runs -- that branch must sit
    # strictly after both deadline-reached branches, never between them.
    normal_exit_at = script.index('"PAPER TRADING RUNNER EXIT CODE:')
    assert critical_exit_at < normal_exit_at


def test_windows_autopilot_task_disable_failure_also_forces_a_critical_exit():
    # Work's final limited audit (WORK_FINAL_AUDIT_PR370_V2, 2026-10-27):
    # a failed Disable-ScheduledTask was previously only an AUTOPILOT
    # CRITICAL log line, with no effect on the script's own exit code --
    # a routine expiry where the task failed to disable would still exit
    # 0. Disable-AutopilotTaskWithEvidence must return success/failure,
    # and every call site must route to Exit-AutopilotCritical when it
    # returns false.
    script = _text(AUTOPILOT)
    assert "function Disable-AutopilotTaskWithEvidence" in script
    assert "return $disableSucceeded" in script

    call_sites = [
        m.start() for m in re.finditer(r"Disable-AutopilotTaskWithEvidence -Reason", script)
    ]
    assert len(call_sites) >= 5, f"expected at least 5 call sites, found {len(call_sites)}"
    for call_at in call_sites:
        line_start = script.rfind("\n", 0, call_at) + 1
        line_end = script.find("\n", call_at)
        line = script[line_start:line_end]
        preceding = script[max(0, line_start - 40):line_start]
        is_guarded_call = "if (-not (Disable-AutopilotTaskWithEvidence" in line
        is_fire_and_forget_before_unconditional_exit = "| Out-Null" in line and "elseif" not in preceding
        assert is_guarded_call or is_fire_and_forget_before_unconditional_exit, (
            f"call site not guarded by a disable-failure check: {line!r}"
        )
        if is_guarded_call:
            # The guard's body must reach Exit-AutopilotCritical, not
            # merely log and fall through to a plain break with exit 0.
            brace_at = script.index("{", call_at)
            exit_at = script.index("Exit-AutopilotCritical", brace_at)
            closing_brace_at = script.index("}", exit_at)
            assert brace_at < exit_at < closing_brace_at


@pytest.mark.skipif(sys.platform != "win32", reason="real Disable-ScheduledTask/exit-code behavior is Windows-specific")
def test_disable_autopilot_task_with_evidence_and_critical_exit_on_real_windows():
    # Work's final limited audit (WORK_FINAL_AUDIT_PR370_V2): prove, with
    # the real functions extracted verbatim and run against the real
    # Task Scheduler API (no fake/mock), that (a) Disable-
    # AutopilotTaskWithEvidence returns False for a task name that does
    # not exist (a genuine Disable-ScheduledTask failure, not simulated),
    # (b) it returns True for an existing, already-Disabled task, and
    # (c) Exit-AutopilotCritical actually terminates the whole process
    # with a non-zero exit code rather than merely returning from a
    # function. No Paper/Live order, no task enable/start, no Read-Only
    # or flag change.
    #
    # Codex review (PR #370, finding P1, discussion_r4385795521): the
    # prior version of this test operated directly on the real production
    # task name ('stock_v2 Paper Signal Runner Autopilot'). On a fresh
    # Windows install this test runs before the installer registers that
    # task, so Disable-AutopilotTaskWithEvidence correctly returns False
    # for a task that does not yet exist -- but the test asserted True,
    # aborting installation. On an existing install it also disabled the
    # real task as a side effect of merely running the test suite. This
    # now registers and cleans up its own isolated, harmless test task
    # instead, and never reads, disables, or otherwise touches the real
    # production autopilot task.
    script = _text(AUTOPILOT)
    helper_functions = "\n".join(
        _extract_function_body(script, name)
        for name in (
            "Add-AutopilotLog",
            "Add-AutopilotLogSafe",
            "Disable-AutopilotTaskWithEvidence",
            "Exit-AutopilotCritical",
        )
    )

    test_task_name = f"stock_v2_test_isolated_task_{uuid.uuid4().hex}"

    with tempfile.TemporaryDirectory() as temp_dir:
        log_file = Path(temp_dir) / "evidence_test.log"
        nonexistent_task = f"stock_v2_test_nonexistent_task_{uuid.uuid4().hex}"

        try:
            register = subprocess.run(
                [
                    "powershell.exe", "-NoProfile", "-Command",
                    "$ErrorActionPreference = 'Stop'; "
                    "$action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument '/c exit 0'; "
                    f"Register-ScheduledTask -TaskName '{test_task_name}' -Action $action | Out-Null; "
                    f"Disable-ScheduledTask -TaskName '{test_task_name}' | Out-Null",
                ],
                capture_output=True, text=True, timeout=20,
            )
            assert register.returncode == 0, (
                f"failed to register isolated test task: {register.stdout} {register.stderr}"
            )

            driver_part1 = (
                "$ErrorActionPreference = 'Stop'\n"
                f"$LogFile = '{log_file}'\n"
                f"{helper_functions}\n"
                f"$TaskName = '{nonexistent_task}'\n"
                "$r1 = Disable-AutopilotTaskWithEvidence -Reason 'test: nonexistent task'\n"
                "Write-Output \"NONEXISTENT_TASK_DISABLE_RESULT=$r1\"\n"
                f"$TaskName = '{test_task_name}'\n"
                "$r2 = Disable-AutopilotTaskWithEvidence -Reason 'test: isolated already-disabled task'\n"
                "Write-Output \"ISOLATED_TASK_DISABLE_RESULT=$r2\"\n"
            )
            with tempfile.NamedTemporaryFile(
                mode="w", suffix=".ps1", delete=False, encoding="utf-8"
            ) as handle:
                handle.write(driver_part1)
                driver_path1 = handle.name
            try:
                result1 = subprocess.run(
                    ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", driver_path1],
                    capture_output=True, text=True, timeout=30,
                )
            finally:
                Path(driver_path1).unlink(missing_ok=True)

            combined1 = result1.stdout + result1.stderr
            assert "NONEXISTENT_TASK_DISABLE_RESULT=False" in combined1, combined1
            assert "ISOLATED_TASK_DISABLE_RESULT=True" in combined1, combined1

            # Confirm the isolated test task (never the real production
            # autopilot task) is still Disabled after this test interacted
            # with it.
            state_check = subprocess.run(
                [
                    "powershell.exe", "-NoProfile", "-Command",
                    f"(Get-ScheduledTask -TaskName '{test_task_name}').State.ToString()",
                ],
                capture_output=True, text=True, timeout=15,
            )
            assert state_check.stdout.strip() == "Disabled", state_check.stdout + state_check.stderr
        finally:
            subprocess.run(
                [
                    "powershell.exe", "-NoProfile", "-Command",
                    f"Unregister-ScheduledTask -TaskName '{test_task_name}' -Confirm:$false "
                    "-ErrorAction SilentlyContinue",
                ],
                capture_output=True, text=True, timeout=15,
            )

        driver_part2 = (
            "$ErrorActionPreference = 'Stop'\n"
            f"$LogFile = '{log_file}'\n"
            f"{helper_functions}\n"
            "Exit-AutopilotCritical -Reason 'test: confirm non-zero exit terminates the process'\n"
            "Write-Output 'SHOULD_NOT_BE_REACHED'\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".ps1", delete=False, encoding="utf-8"
        ) as handle:
            handle.write(driver_part2)
            driver_path2 = handle.name
        try:
            result2 = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", driver_path2],
                capture_output=True, text=True, timeout=30,
            )
        finally:
            Path(driver_path2).unlink(missing_ok=True)

        combined2 = result2.stdout + result2.stderr
        assert "SHOULD_NOT_BE_REACHED" not in combined2, combined2
        assert result2.returncode == 1, (
            f"expected non-zero exit code, got {result2.returncode}: {combined2}"
        )


def test_windows_autopilot_logging_failure_never_blocks_a_safety_stop():
    # Work's follow-up independent audit (PR #370): an exception thrown by
    # Add-AutopilotLog at a safety-critical stop decision (deadline
    # expiry, termination-confirmation failure) would previously propagate
    # to the outer per-cycle catch, which only logs a generic warning and
    # then sleeps and retries -- silently resuming a new cycle exactly
    # when the script had already decided it must not. Every terminal/
    # critical log call must use the fail-safe wrapper instead, so a
    # logging failure can never prevent the actual stop (Disable-
    # ScheduledTask attempt + break) from happening.
    script = _text(AUTOPILOT)
    assert "function Add-AutopilotLogSafe" in script
    # Every expiry/critical branch must log via the safe wrapper, not the
    # raw function that can throw and divert control to the outer catch.
    for marker in (
        '"AUTOPILOT EXPIRED: approval deadline file is missing',
        '"AUTOPILOT EXPIRED: approval deadline file is unreadable',
        '"AUTOPILOT EXPIRED: approval deadline $($deadlineUtc.ToString(\'o\')) UTC reached. Exiting',
        '"AUTOPILOT EXPIRED: approval deadline $($deadlineUtc.ToString(\'o\')) UTC reached immediately before runner start',
        '"AUTOPILOT DEADLINE ENFORCED',
        '"AUTOPILOT CRITICAL: approval deadline was reached',
    ):
        marker_at = script.index(marker)
        line_start = script.rfind("\n", 0, marker_at) + 1
        preceding = script[max(0, line_start - 80):line_start]
        assert "Add-AutopilotLogSafe" in preceding, (
            f"expected Add-AutopilotLogSafe immediately before: {marker!r}"
        )


def _extract_function_body(script: str, func_name: str) -> str:
    pattern = r"function\s+" + re.escape(func_name) + r"\s*\{"
    match = re.search(pattern, script)
    assert match, f"could not find function {func_name}"
    depth = 1
    index = match.end()
    while depth > 0:
        char = script[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
        index += 1
    return script[match.start():index]


@pytest.mark.skipif(sys.platform != "win32", reason="real process kill timing is Windows-specific")
def test_wait_process_with_deadline_actually_kills_a_hanging_process_on_windows():
    # Extracted verbatim from the real script (not reimplemented), per this
    # project's rule that a fix must be proven against the actual function
    # body. Runs a genuinely long-running (30s) child process against a
    # 1-second deadline and proves it is forcibly killed well before it
    # would naturally finish. No broker/order code is involved.
    script = _text(AUTOPILOT)
    function_body = _extract_function_body(script, "Wait-ProcessWithDeadline")

    driver = (
        "$ErrorActionPreference = 'Stop'\n"
        f"{function_body}\n"
        "$proc = Start-Process -FilePath 'powershell.exe' "
        "-ArgumentList '-NoProfile -Command Start-Sleep -Seconds 30' "
        "-PassThru -NoNewWindow\n"
        "$deadline = (Get-Date).ToUniversalTime().AddSeconds(1)\n"
        "$result = Wait-ProcessWithDeadline -Process $proc "
        "-DeadlineUtc $deadline -PollMilliseconds 200\n"
        "Write-Output \"DEADLINE_REACHED=$($result.DeadlineReached)\"\n"
        "Write-Output \"CONFIRMED_EXITED=$($result.ConfirmedExited)\"\n"
        "Write-Output \"EXITED=$($proc.HasExited)\"\n"
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ps1", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(driver)
        driver_path = handle.name

    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                driver_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        Path(driver_path).unlink(missing_ok=True)

    combined = result.stdout + result.stderr
    assert "DEADLINE_REACHED=True" in combined, combined
    assert "CONFIRMED_EXITED=True" in combined, combined
    assert "EXITED=True" in combined, combined


@pytest.mark.skipif(sys.platform != "win32", reason="real process kill timing is Windows-specific")
def test_wait_process_with_deadline_never_claims_success_when_termination_cannot_be_confirmed():
    # Work's follow-up independent audit (PR #370, comment
    # WORK_AUDIT_PR370_V1): deterministically prove, with the real function
    # body extracted verbatim (not reimplemented), that a process which
    # does NOT actually exit after Kill()+WaitForExit is reported as
    # unconfirmed (ConfirmedExited=False) -- never silently treated as a
    # successful termination. A real OS process cannot be reliably forced
    # to survive TerminateProcess, so this uses a duck-typed PowerShell
    # class double exposing the same HasExited/Kill()/WaitForExit(ms)/Id
    # members Wait-ProcessWithDeadline actually calls; $Process is
    # intentionally untyped in the real function precisely so this works.
    script = _text(AUTOPILOT)
    function_body = _extract_function_body(script, "Wait-ProcessWithDeadline")

    driver = (
        "$ErrorActionPreference = 'Stop'\n"
        f"{function_body}\n"
        "class FakeNeverExitingProcess {\n"
        "    [bool]$HasExited = $false\n"
        "    [int]$Id = 99999\n"
        "    [void] Kill() { }\n"
        "    [bool] WaitForExit([int]$ms) { Start-Sleep -Milliseconds 50; return $false }\n"
        "}\n"
        "class FakeExitsAfterKillProcess {\n"
        "    [bool]$HasExited = $false\n"
        "    [int]$Id = 88888\n"
        "    [void] Kill() { $this.HasExited = $true }\n"
        "    [bool] WaitForExit([int]$ms) { return $this.HasExited }\n"
        "}\n"
        "$pastDeadline = (Get-Date).ToUniversalTime().AddSeconds(-1)\n"
        "$neverExiting = [FakeNeverExitingProcess]::new()\n"
        "$r1 = Wait-ProcessWithDeadline -Process $neverExiting -DeadlineUtc $pastDeadline -PollMilliseconds 50 -KillConfirmWaitMilliseconds 100\n"
        "Write-Output \"UNCONFIRMED_DEADLINE_REACHED=$($r1.DeadlineReached)\"\n"
        "Write-Output \"UNCONFIRMED_CONFIRMED_EXITED=$($r1.ConfirmedExited)\"\n"
        "$exitsAfterKill = [FakeExitsAfterKillProcess]::new()\n"
        "$r2 = Wait-ProcessWithDeadline -Process $exitsAfterKill -DeadlineUtc $pastDeadline -PollMilliseconds 50 -KillConfirmWaitMilliseconds 100\n"
        "Write-Output \"CONFIRMED_DEADLINE_REACHED=$($r2.DeadlineReached)\"\n"
        "Write-Output \"CONFIRMED_CONFIRMED_EXITED=$($r2.ConfirmedExited)\"\n"
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ps1", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(driver)
        driver_path = handle.name

    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                driver_path,
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
    finally:
        Path(driver_path).unlink(missing_ok=True)

    combined = result.stdout + result.stderr
    assert "UNCONFIRMED_DEADLINE_REACHED=True" in combined, combined
    assert "UNCONFIRMED_CONFIRMED_EXITED=False" in combined, combined
    assert "CONFIRMED_DEADLINE_REACHED=True" in combined, combined
    assert "CONFIRMED_CONFIRMED_EXITED=True" in combined, combined


@pytest.mark.skipif(sys.platform != "win32", reason="real Windows process-tree verification, no broker/order code")
def test_venv_python_launcher_leaves_no_orphaned_child_process_after_kill():
    # Work's follow-up independent audit (PR #370): verify, using the
    # real .venv\\Scripts\\python.exe launcher this script actually
    # invokes (not a fake/mocked process), that killing that process
    # leaves no order-processing descendant process still running. The
    # dummy workload is a bare time.sleep(); no broker/runner code or
    # order is ever invoked.
    #
    # Work's final limited audit (WORK_FINAL_AUDIT_PR370_V2, 2026-10-27):
    # the original version of this test never checked either CIM/Get-
    # Process query's own returncode -- a query failure (empty stdout)
    # would be silently read as "no children found" and the test would
    # PASS without having actually observed anything. Every diagnostic
    # query below now asserts its own returncode is 0 before its output
    # is trusted, so a query failure fails the test loudly instead of
    # masquerading as a clean result. This does not claim to prove
    # descendant termination in every possible situation -- only that
    # what was actually, successfully observed in this run showed no
    # orphan.
    #
    # Codex review (PR #370, finding P2, discussion_r4385795529): on
    # Windows PowerShell 5.1, wrapping a cmdlet call in parentheses (as
    # the prior version did) lets a non-terminating query error still
    # leave `$?` true, so `powershell.exe -Command` can return exit code
    # 0 even though the query itself failed -- exactly the "returncode
    # == 0 but no real result" case the returncode assertion above was
    # meant to catch, bypassed. Each query now explicitly sets
    # `-ErrorAction Stop` inside a try/catch so any query failure becomes
    # a terminating exception (exit 1), while "process not found" (the
    # expected, non-error outcome for a genuinely dead child) is caught
    # specifically and reported as 'False' rather than treated as a
    # failure.
    repo_root = Path(__file__).resolve().parent.parent
    python_exe = repo_root / ".venv" / "Scripts" / "python.exe"
    assert python_exe.exists(), f"missing venv python: {python_exe}"

    proc = subprocess.Popen([str(python_exe), "-c", "import time; time.sleep(30)"])
    try:
        time.sleep(1.5)  # let it actually start before inspecting children

        children_check = subprocess.run(
            [
                "powershell.exe", "-NoProfile", "-Command",
                "$ErrorActionPreference = 'Stop'; try { "
                f"(Get-CimInstance Win32_Process -Filter \"ParentProcessId={proc.pid}\" -ErrorAction Stop "
                "| Select-Object -ExpandProperty ProcessId) -join ',' "
                "} catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }",
            ],
            capture_output=True, text=True, timeout=15,
        )
        assert children_check.returncode == 0, (
            "child-process CIM query itself failed (cannot be read as "
            f"'no children'): returncode={children_check.returncode} "
            f"stdout={children_check.stdout!r} stderr={children_check.stderr!r}"
        )
        children_before = [p for p in children_check.stdout.strip().split(",") if p]

        proc.kill()
        proc.wait(timeout=10)
        time.sleep(1.0)

        leftover = []
        for child_pid in children_before:
            still_alive = subprocess.run(
                [
                    "powershell.exe", "-NoProfile", "-Command",
                    "$ErrorActionPreference = 'Stop'; try { "
                    f"Get-Process -Id {child_pid} -ErrorAction Stop | Out-Null; Write-Output 'True' "
                    "} catch [Microsoft.PowerShell.Commands.ProcessCommandException] { Write-Output 'False' } "
                    "catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }",
                ],
                capture_output=True, text=True, timeout=10,
            )
            assert still_alive.returncode == 0, (
                f"liveness query for child PID {child_pid} itself failed "
                "(cannot be read as 'not alive'): "
                f"returncode={still_alive.returncode} "
                f"stdout={still_alive.stdout!r} stderr={still_alive.stderr!r}"
            )
            assert still_alive.stdout.strip() in ("True", "False"), (
                f"liveness query for child PID {child_pid} returned an "
                f"unrecognized result: stdout={still_alive.stdout!r} "
                f"stderr={still_alive.stderr!r}"
            )
            if still_alive.stdout.strip() == "True":
                leftover.append(child_pid)

        assert leftover == [], (
            f"orphaned child process(es) still running after parent kill: {leftover} "
            f"(children observed before kill: {children_before})"
        )
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait(timeout=10)


def test_windows_autopilot_disables_bytecode_writes_and_cleans_stale_caches():
    script = _text(AUTOPILOT)
    assert '$env:PYTHONDONTWRITEBYTECODE = "1"' in script
    bytecode_env_at = script.index('$env:PYTHONDONTWRITEBYTECODE = "1"')
    cleanup_def_at = script.index("function Remove-StalePycacheArtifacts")
    cleanup_call_at = script.index("Remove-StalePycacheArtifacts", cleanup_def_at + 1)
    runner_at = script.index("-m paper_trading_runner")
    assert bytecode_env_at < cleanup_def_at < cleanup_call_at < runner_at
    assert "__pycache__" in script
    assert "git -C $RepoDir ls-files --others --ignored --exclude-standard --directory" in script
    assert "Remove-Item -LiteralPath $RepoDir -Recurse" not in script


def _extract_here_string(script: str, var_name: str) -> str:
    pattern = r"\$" + re.escape(var_name) + r"\s*=\s*@'\r?\n(.*?)\r?\n'@"
    match = re.search(pattern, script, re.DOTALL)
    assert match, f"could not find single-quoted here-string for ${var_name}"
    return match.group(1)


def test_market_session_check_never_uses_double_quoted_python_literals():
    # 2026-10-26 incident: Windows PowerShell 5.1 silently strips embedded
    # double-quote characters when a multi-line string is passed as a
    # single argument to a native executable's -c flag. With double quotes
    # (tickers = ["AAPL", "SPY", "9432.T"]), python received
    # tickers = [AAPL, SPY, 9432.T] and raised "SyntaxError: invalid decimal
    # literal" on 9432.T -- caught by the surrounding try/catch and logged
    # as an opaque "AUTOPILOT WARNING", so this check never once reached
    # OPEN/CLOSED and paper_trading_runner never ran on a real Windows box.
    # This is a static guard against reintroducing double quotes; the
    # execution test below proves the current snippet actually runs.
    script = _text(AUTOPILOT)
    assert "$MarketSessionCheck = @'" in script
    snippet = _extract_here_string(script, "MarketSessionCheck")
    assert '"' not in snippet


@pytest.mark.skipif(sys.platform != "win32", reason="real native-arg passing to -c is Windows PowerShell 5.1 specific")
def test_market_session_check_snippet_actually_executes_on_windows():
    # Extracted verbatim from the real script (not reimplemented) and run
    # through the real powershell.exe -> python.exe -c native-argument path,
    # per this project's rule that a fix for a Windows native-arg bug must
    # be proven against the actual function body, not a reimplementation.
    script = _text(AUTOPILOT)
    snippet = _extract_here_string(script, "MarketSessionCheck")

    driver = (
        "$ErrorActionPreference = 'Stop'\n"
        "$MarketSessionCheck = @'\n"
        f"{snippet}\n"
        "'@\n"
        f"& '{sys.executable}' -c $MarketSessionCheck 2>&1\n"
        "exit $LASTEXITCODE\n"
    )

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".ps1", delete=False, encoding="utf-8"
    ) as handle:
        handle.write(driver)
        driver_path = handle.name

    try:
        result = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-File",
                driver_path,
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
    finally:
        Path(driver_path).unlink(missing_ok=True)

    combined = result.stdout + result.stderr
    assert "SyntaxError" not in combined, combined
    assert result.returncode == 0, combined
    assert "OPEN" in combined or "CLOSED" in combined, combined


def test_windows_installer_computes_and_persists_approval_deadline():
    script = _text(INSTALLER)
    assert "$MaxRuntimeHours" in script
    assert "= 24" in script or "24\n" in script
    assert "$MaxRuntimeHours -lt 1 -or $MaxRuntimeHours -gt 8760" in script
    assert "$ApprovalDeadlineUtc = (Get-Date).ToUniversalTime().AddHours($MaxRuntimeHours)" in script
    assert "Set-PrivatePinFile -Path $DeadlineFile -Value $ApprovalDeadlineUtc.ToString(\"o\")" in script


def test_windows_installer_disables_bytecode_writes_and_cleans_stale_caches_before_tests():
    script = _text(INSTALLER)
    assert '$env:PYTHONDONTWRITEBYTECODE = "1"' in script
    bytecode_env_at = script.index('$env:PYTHONDONTWRITEBYTECODE = "1"')
    pytest_at = script.index("-m pytest")
    assert bytecode_env_at < pytest_at
    assert script.count("__pycache__") >= 2
    assert script.count("git -C $RepoDir ls-files --others --ignored --exclude-standard --directory") >= 1
    assert "Remove-Item -LiteralPath $RepoDir -Recurse" not in script


def test_windows_installer_is_fail_closed_non_elevated_and_stages_disabled():
    script = _text(INSTALLER)
    assert '$branch -ne "main"' in script
    assert "-RunLevel Limited" in script
    assert "-LogonType Interactive" in script
    assert "Disable-ScheduledTask" in script
    assert "if ($staged.State -ne \"Disabled\")" in script
    assert "-AtLogOn" in script
    assert "test_ibkr_windows_paper_signal_runner_autopilot.py" in script
    assert "test_signal_runner_windows_source_sha.py" in script
    assert "test_paper_trading_runner.py" in script
