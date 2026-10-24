from pathlib import Path


AUTOPILOT = Path("ibkr_paper_signal_runner_autopilot_windows.ps1")
INSTALLER = Path("install_ibkr_paper_signal_runner_autopilot_windows.ps1")


def _text(path: Path) -> str:
    assert path.exists(), f"missing required file: {path}"
    return path.read_text(encoding="utf-8")


def test_windows_autopilot_only_invokes_signal_runner_and_market_session_check():
    script = _text(AUTOPILOT)
    lower = script.lower()
    assert "-m signal_runner" in script
    assert "evaluate_verified_market_session" in script
    assert "placeOrder(" not in script
    assert "ibkr_auto_close_cycle" not in script
    assert "ibkr_overnight_e2e" not in script
    assert "YES_CLOSE_ONE_SPY_PAPER" not in script
    assert "ibkr_verified_paper_runtime" not in script
    assert '"LIVE ORDER SENT: False"' in script


def test_windows_autopilot_never_enables_or_touches_live_trading():
    script = _text(AUTOPILOT)
    lower = script.lower()
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
    runner_at = script.index('-m signal_runner')
    assert branch_at < branch_block_at < runner_at
    assert head_at < head_block_at < runner_at
    assert clean_block_at < runner_at
    assert "git diff --quiet HEAD -- . ':(exclude)results/**' ':(exclude)data/**'" in script
    assert "git diff --cached --quiet HEAD -- . ':(exclude)results/**' ':(exclude)data/**'" in script


def test_windows_autopilot_skips_signal_runner_when_all_verified_tickers_closed():
    script = _text(AUTOPILOT)
    session_check_at = script.index("evaluate_verified_market_session")
    market_open_at = script.index("$marketOpen = ")
    skip_at = script.index('"VERIFIED TICKER MARKET SESSION CLOSED')
    runner_at = script.index('-m signal_runner')
    assert session_check_at < market_open_at < skip_at < runner_at


def test_windows_autopilot_uses_windows_venv_and_bounded_loop():
    script = _text(AUTOPILOT)
    assert '.venv\\Scripts\\python.exe' in script
    assert "$IntervalSeconds -lt 30 -or $IntervalSeconds -gt 86400" in script
    assert "$MaxLogBytes -lt 1048576 -or $MaxLogBytes -gt 104857600" in script
    assert "Start-Sleep -Seconds $IntervalSeconds" in script
    assert "$RotatedLogFile" in script
    assert "Rotate-AutopilotLogIfNeeded" in script


def test_windows_autopilot_self_expires_and_requires_fresh_approval_to_resume():
    script = _text(AUTOPILOT)
    assert "$MaxRuntimeHours -lt 1 -or $MaxRuntimeHours -gt 8760" in script
    assert "AUTOPILOT EXPIRED" in script
    assert "fresh explicit approval" in script
    assert "break" in script


def test_windows_installer_is_fail_closed_non_elevated_and_stages_disabled():
    script = _text(INSTALLER)
    lower = script.lower()
    assert '$branch -ne "main"' in script
    assert "-RunLevel Limited" in script
    assert "-LogonType Interactive" in script
    assert "Disable-ScheduledTask" in script
    assert "if ($staged.State -ne \"Disabled\")" in script
    assert "-AtLogOn" in script
    assert "test_ibkr_windows_paper_signal_runner_autopilot.py" in script
