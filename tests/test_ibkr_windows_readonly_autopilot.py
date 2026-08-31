from pathlib import Path


AUTOPILOT = Path("ibkr_readonly_autopilot_windows.ps1")
INSTALLER = Path("install_ibkr_readonly_autopilot_windows.ps1")
STRICT_MONITOR = "ai_asset_platform.brokers.ibkr_paper_operations_monitor_strict"


def _text(path: Path) -> str:
    assert path.exists(), f"missing required file: {path}"
    return path.read_text(encoding="utf-8")


def test_windows_autopilot_only_invokes_strict_readonly_monitor():
    script = _text(AUTOPILOT)
    lower = script.lower()
    assert STRICT_MONITOR in script
    assert "placeOrder(" not in script
    assert "ibkr_auto_close_cycle" not in script
    assert "ibkr_overnight_e2e" not in script
    assert "YES_CLOSE_ONE_SPY_PAPER" not in script
    assert "RUN_VERIFIED_PAPER_ONLY" not in script
    assert "ibkr_verified_paper_runtime" not in script
    assert "AI_ASSET_ENABLE_LIVE_TRADING" not in script
    assert "AI_ASSET_LIVE_TRADING_UNLOCKED" not in script
    assert "enable_live_trading" not in lower
    assert '"ORDER API REQUEST SENT: False"' in script
    assert '"LIVE ORDER SENT: False"' in script


def test_windows_autopilot_never_updates_remote_source_unattended():
    script = _text(AUTOPILOT)
    lower = script.lower()
    assert "git pull" not in lower
    assert "git fetch" not in lower
    assert "git switch" not in lower
    assert "git checkout" not in lower
    assert "$PinnedHead" in script
    assert "AUTOPILOT SOURCE BLOCKED" in script


def test_windows_autopilot_requires_main_pin_and_clean_source_before_monitor():
    script = _text(AUTOPILOT)
    branch_at = script.index('$currentBranch = Get-GitSingleLine')
    head_at = script.index('$currentHead = Get-GitSingleLine')
    branch_block_at = script.index('if ($currentBranch -ne "main")')
    head_block_at = script.index('elseif ($currentHead -ne $PinnedHead)')
    clean_block_at = script.index('elseif (-not (Test-TrackedSourceClean))')
    monitor_at = script.index(STRICT_MONITOR)
    assert branch_at < branch_block_at < monitor_at
    assert head_at < head_block_at < monitor_at
    assert clean_block_at < monitor_at
    assert "git diff --quiet HEAD -- . ':(exclude)results/**' ':(exclude)data/**'" in script
    assert "git diff --cached --quiet HEAD -- . ':(exclude)results/**' ':(exclude)data/**'" in script


def test_windows_autopilot_uses_windows_venv_and_bounded_loop():
    script = _text(AUTOPILOT)
    assert '.venv\\Scripts\\python.exe' in script
    assert "300" in script
    assert "$IntervalSeconds -lt 30 -or $IntervalSeconds -gt 86400" in script
    assert "5242880" in script
    assert "$MaxLogBytes -lt 1048576 -or $MaxLogBytes -gt 104857600" in script
    assert "Start-Sleep -Seconds $IntervalSeconds" in script
    assert "$RotatedLogFile" in script
    assert "Rotate-AutopilotLogIfNeeded" in script


def test_windows_autopilot_preserves_monitor_policy_defaults():
    script = _text(AUTOPILOT)
    assert 'IBKR_PAPER_MONITOR_MAX_RUNTIME_AGE_HOURS = "96"' in script
    assert 'IBKR_PAPER_MONITOR_MAX_HISTORY_BYTES = "10485760"' in script
    assert 'IBKR_PAPER_MONITOR_EMAIL_ALERTS = "auto"' in script
    assert 'IBKR_PAPER_MONITOR_EMAIL_COOLDOWN_HOURS = "12"' in script


def test_windows_installer_is_fail_closed_and_non_elevated():
    script = _text(INSTALLER)
    lower = script.lower()
    assert '$branch -ne "main"' in script
    assert "$PinnedHead -notmatch '^[0-9a-f]{40}$'" in script
    assert "Test-TrackedSourceClean" in script
    assert "tests/test_ibkr_windows_readonly_autopilot.py" in script
    assert "tests/test_ibkr_paper_operations_monitor_strict.py" in script
    assert "Language.Parser]::ParseFile" in script
    assert "-RunLevel Limited" in script
    assert "-AtLogOn" in script
    assert "-RestartCount 999" in script
    assert "-RestartInterval (New-TimeSpan -Minutes 1)" in script
    assert "-ExecutionTimeLimit ([TimeSpan]::Zero)" in script
    assert "-AllowStartIfOnBatteries" in script
    assert "-DontStopIfGoingOnBatteries" in script
    assert "-MultipleInstances IgnoreNew" in script
    assert "Register-ScheduledTask" in script
    assert "Disable-ScheduledTask" in script
    assert "Start-ScheduledTask" not in script
    assert "RunLevel Highest" not in script
    assert "placeorder(" not in lower
    assert "enable_live_trading" not in lower


def test_windows_installer_stages_disabled_after_revision_pin():
    script = _text(INSTALLER)
    pin_at = script.index("Set-PrivatePinFile -Path $PinFile -Value $PinnedHead")
    register_at = script.index("Register-ScheduledTask")
    disable_at = script.index("Disable-ScheduledTask")
    state_check_at = script.index('$staged.State -ne "Disabled"')
    assert pin_at < register_at < disable_at < state_check_at
    assert 'Write-Host "TASK STATE: Disabled"' in script
    assert 'Write-Host "MONITOR STARTED: False"' in script


def test_windows_autopilot_marks_all_order_paths_false_even_after_error():
    script = _text(AUTOPILOT)
    assert script.count('"ORDER API REQUEST SENT: False"') >= 2
    assert script.count('"REAL ORDER SENT: False"') >= 2
    assert script.count('"LIVE ORDER SENT: False"') >= 2
    assert "Never compensate by issuing an order" in script
