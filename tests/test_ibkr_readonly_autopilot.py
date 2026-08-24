from pathlib import Path


def test_readonly_autopilot_only_invokes_safe_readonly_checks():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert "bash ./ibkr_auto.sh" in script
    assert "python -m ai_asset_platform.brokers.ibkr_multiasset_readonly_audit" in script
    assert "ibkr_auto_close_cycle_once.sh" not in script
    assert "ibkr_overnight_e2e_once.sh" not in script
    assert "YES_CLOSE_ONE_SPY_PAPER" not in script
    assert "AI_ASSET_ENABLE_IBKR_PAPER=true" not in script
    assert "enable_live_trading" not in script.lower()


def test_readonly_autopilot_keeps_running_when_audit_is_not_ready():
    script = Path("ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert "CHECKPOINT NOT READY" in script
    assert "MULTI-ASSET NOT READY" in script
    assert "sleep \"$INTERVAL_SECONDS\"" in script


def test_installer_runs_only_readonly_autopilot_service():
    script = Path("install_ibkr_readonly_autopilot.sh").read_text(encoding="utf-8")
    assert "ibkr_readonly_autopilot.sh" in script
    assert "ibkr_auto_close_cycle_once.sh" not in script
    assert "YES_CLOSE_ONE_SPY_PAPER" not in script
