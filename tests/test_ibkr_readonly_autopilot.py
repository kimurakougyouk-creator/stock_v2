from pathlib import Path
import subprocess


STRICT_MONITOR = "python -m ai_asset_platform.brokers.ibkr_paper_operations_monitor_strict"


def test_readonly_autopilot_has_valid_bash_syntax():
    result = subprocess.run(
        ["bash", "-n", "ibkr_readonly_autopilot.sh"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_readonly_autopilot_only_invokes_strict_readonly_monitor():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert STRICT_MONITOR in script
    assert "bash ./ibkr_auto.sh" not in script
    assert "ibkr_operator_checkpoint" not in script
    assert "ibkr_overnight_whatif" not in script
    assert "placeOrder(" not in script
    assert "ibkr_auto_close_cycle_once.sh" not in script
    assert "ibkr_overnight_e2e_once.sh" not in script
    assert "YES_CLOSE_ONE_SPY_PAPER" not in script
    assert "AI_ASSET_ENABLE_IBKR_PAPER=true" not in script
    assert "AI_ASSET_ENABLE_LIVE_TRADING" not in script
    assert "AI_ASSET_LIVE_TRADING_UNLOCKED" not in script
    assert "enable_live_trading" not in script.lower()
    assert "RUN_VERIFIED_PAPER_ONLY" not in script
    assert "ibkr_verified_paper_runtime_once.sh" not in script
    assert 'echo "ORDER API REQUEST SENT: False"' in script


def test_readonly_autopilot_keeps_running_when_monitor_is_not_ready():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert "PAPER OPERATIONS CRITICAL" in script
    assert "PAPER OPERATIONS WARNING" in script
    assert "sleep \"$INTERVAL_SECONDS\"" in script


def test_readonly_autopilot_self_reloads_after_successful_fast_forward():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert 'before_head="$(git rev-parse HEAD)"' in script
    assert "if git pull --ff-only origin main; then" in script
    assert 'after_head="$(git rev-parse HEAD)"' in script
    assert '[[ "$after_head" != "$before_head" ]]' in script
    assert 'exec /usr/bin/env bash "$REPO_DIR/ibkr_readonly_autopilot.sh"' in script
    assert script.index("if git pull --ff-only origin main; then") < script.index("exec /usr/bin/env bash")


def test_readonly_autopilot_requires_main_but_tolerates_remote_outage():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    switch_at = script.index("git switch main")
    pull_at = script.index("if git pull --ff-only origin main; then")
    warning_at = script.index("origin/main unavailable; continuing from unchanged local main")
    monitor_at = script.index(STRICT_MONITOR)
    assert switch_at < pull_at < warning_at < monitor_at


def test_readonly_autopilot_bounds_interval_and_log_growth():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert 'INTERVAL_SECONDS="${IBKR_AUTOPILOT_INTERVAL_SECONDS:-300}"' in script
    assert "INTERVAL_SECONDS < 30 || INTERVAL_SECONDS > 86400" in script
    assert 'MAX_LOG_BYTES="${IBKR_AUTOPILOT_MAX_LOG_BYTES:-5242880}"' in script
    assert "MAX_LOG_BYTES < 1048576 || MAX_LOG_BYTES > 104857600" in script
    assert 'ROTATED_LOG_FILE="$LOG_FILE.1"' in script
    assert "rotate_autopilot_log_if_needed" in script
    assert 'mv -f "$LOG_FILE" "$ROTATED_LOG_FILE"' in script
    assert "rm -f" not in script


def test_installer_runs_only_readonly_autopilot_service():
    script = Path("install_ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert "ibkr_readonly_autopilot.sh" in script
    assert "ibkr_auto_close_cycle_once.sh" not in script
    assert "YES_CLOSE_ONE_SPY_PAPER" not in script
    assert "UMask=0077" in script
    assert "IBKR_PAPER_MONITOR_MAX_RUNTIME_AGE_HOURS=96" in script
    assert "IBKR_PAPER_MONITOR_MAX_HISTORY_BYTES=10485760" in script
    assert "IBKR_PAPER_MONITOR_EMAIL_ALERTS=auto" in script
    assert "IBKR_PAPER_MONITOR_EMAIL_COOLDOWN_HOURS=12" in script
    assert "tests/test_ibkr_paper_operations_monitor.py" in script
    assert "tests/test_ibkr_paper_operations_monitor_strict.py" in script
    assert "systemctl --user enable ibkr-readonly-autopilot.service" in script
    assert "systemctl --user restart ibkr-readonly-autopilot.service" in script
    assert "systemctl --user enable --now ibkr-readonly-autopilot.service" not in script


def test_paper_operations_monitor_once_wrapper_is_readonly():
    script = Path("ibkr_paper_operations_monitor_once.sh").read_text(encoding="utf-8")
    assert STRICT_MONITOR in script
    assert "tests/test_ibkr_paper_operations_monitor_strict.py" in script
    assert "RUN_VERIFIED_PAPER_ONLY" not in script
    assert "AI_ASSET_ENABLE_IBKR_PAPER" not in script
    assert "ibkr_verified_paper_runtime_once.sh" not in script
    result = subprocess.run(
        ["bash", "-n", "ibkr_paper_operations_monitor_once.sh"],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
