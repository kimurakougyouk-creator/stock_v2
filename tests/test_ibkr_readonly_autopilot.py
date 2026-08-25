from pathlib import Path


def test_readonly_autopilot_only_invokes_safe_readonly_checks():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert "bash ./ibkr_auto.sh" in script
    assert "python -m ai_asset_platform.brokers.ibkr_multiasset_readonly_audit" in script
    assert "ibkr_auto_close_cycle_once.sh" not in script
    assert "ibkr_overnight_e2e_once.sh" not in script
    assert "YES_CLOSE_ONE_SPY_PAPER" not in script
    assert "AI_ASSET_ENABLE_IBKR_PAPER=true" not in script
    assert "AI_ASSET_ENABLE_LIVE_TRADING" not in script
    assert "AI_ASSET_LIVE_TRADING_UNLOCKED" not in script
    assert "enable_live_trading" not in script.lower()


def test_readonly_autopilot_keeps_running_when_audit_is_not_ready():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert "CHECKPOINT NOT READY" in script
    assert "MULTI-ASSET NOT READY" in script
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
    audit_at = script.index("bash ./ibkr_auto.sh")
    assert switch_at < pull_at < warning_at < audit_at


def test_installer_runs_only_readonly_autopilot_service():
    script = Path("install_ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert "ibkr_readonly_autopilot.sh" in script
    assert "ibkr_auto_close_cycle_once.sh" not in script
    assert "YES_CLOSE_ONE_SPY_PAPER" not in script
